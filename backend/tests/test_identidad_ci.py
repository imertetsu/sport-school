"""Tests de identidad CI / recuperar-por-CI (S3).

Cubre el contrato S3 sobre `app/services/deportista.py` (la lógica vive ahí; el
router solo traduce a HTTP):

- (a) dedup deportista: mismo CI en la MISMA org -> `CIDuplicado` (=> 409).
- (b) múltiples deportistas/tutores con `ci=NULL` permitidos (índice parcial).
- (c) mismo CI en orgs DISTINTAS permitido (unicidad POR ORG, RLS).
- (d) `buscar_deportista_por_ci` recupera el existente / None si no hay.
- (e) tutor recuperado por CI en el alta + teléfono actualizado (sin duplicar).
- (f) tutor SIN CI se crea normal (no se reusa, no choca con el índice parcial).

Dos capas, igual que el resto de la suite:
- Sin BD (siempre): comportamiento puro del 422 schema ya vive en
  `test_deportistas_api.py`; aquí los tests sin BD verifican el error de negocio
  como clase (import + jerarquía).
- Con BD (`@pytest.mark.db`): requiere Postgres migrado **con 0017** (índices únicos
  parciales `(org_id, ci) WHERE ci IS NOT NULL`) + RLS + rol `latinosport_app`. Se
  siembra con `owner_engine` (salta RLS) y se ejercita el servicio con una `Session`
  sobre `app_engine` bajo el contexto de tenant real. Skip si no hay BD (ver conftest).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import pytest
from app.schemas.deportista import (
    ConsentimientoIn,
    DeportistaCreate,
    TutorIn,
)
from app.services import deportista as svc
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session


# --------------------------------------------------------------------------- #
# Sin BD: el error de negocio existe y es traducible a 409
# --------------------------------------------------------------------------- #
def test_ci_duplicado_es_deportista_error() -> None:
    assert issubclass(svc.CIDuplicado, svc.DeportistaError)
    assert issubclass(svc.CIDuplicado, Exception)


# --------------------------------------------------------------------------- #
# Fixture: 2 orgs con 1 sucursal cada una (sembrado como owner, salta RLS)
# --------------------------------------------------------------------------- #
@pytest.fixture()
def ci_fixture(owner_engine: Engine) -> Iterator[dict]:
    org_a = uuid.uuid4()
    org_b = uuid.uuid4()
    suc_a = uuid.uuid4()
    suc_b = uuid.uuid4()

    with owner_engine.begin() as conn:
        for org_id, nombre in ((org_a, "Org A CI (test)"), (org_b, "Org B CI (test)")):
            conn.execute(
                text(
                    "INSERT INTO organizacion (id, nombre, pais, moneda, modo_cobro_default, "
                    "prorratea_primer_periodo, created_at, updated_at) "
                    "VALUES (:id,:nom,'BO','BOB','ANIVERSARIO',true,now(),now())"
                ),
                {"id": str(org_id), "nom": nombre},
            )
        for org_id, suc_id in ((org_a, suc_a), (org_b, suc_b)):
            conn.execute(
                text(
                    "INSERT INTO sucursal (id, org_id, nombre, created_at, updated_at) "
                    "VALUES (:id,:org,'Sucursal',now(),now())"
                ),
                {"id": str(suc_id), "org": str(org_id)},
            )

    yield {"org_a": org_a, "org_b": org_b, "suc_a": suc_a, "suc_b": suc_b}

    # Limpieza respetando FKs (hijos primero). Como owner -> salta RLS.
    with owner_engine.begin() as conn:
        for org_id in (org_a, org_b):
            conn.execute(text("DELETE FROM consentimiento WHERE org_id = :o"), {"o": str(org_id)})
            conn.execute(text("DELETE FROM deportista_tutor WHERE org_id = :o"), {"o": str(org_id)})
            conn.execute(text("DELETE FROM tutor WHERE org_id = :o"), {"o": str(org_id)})
            conn.execute(text("DELETE FROM deportista WHERE org_id = :o"), {"o": str(org_id)})
            conn.execute(text("DELETE FROM sucursal WHERE org_id = :o"), {"o": str(org_id)})
            conn.execute(text("DELETE FROM organizacion WHERE id = :o"), {"o": str(org_id)})


def _set_org(db: Session, org: uuid.UUID) -> None:
    db.execute(text("SELECT set_config('app.current_org', :o, true)"), {"o": str(org)})


def _body(
    *,
    suc_id: uuid.UUID,
    nombres: str,
    ci: str | None,
    tutores: list[TutorIn],
) -> DeportistaCreate:
    return DeportistaCreate(
        sucursal_id=suc_id,
        nombres=nombres,
        ci=ci,
        tutores=tutores,
        consentimiento=ConsentimientoIn(version_terminos="v1", canal="PRESENCIAL"),
    )


def _tutor(nombres: str, *, ci: str | None = None, telefono: str | None = None) -> TutorIn:
    return TutorIn(nombres=nombres, telefono=telefono, ci=ci, responsable_pago=True)


# --------------------------------------------------------------------------- #
# (a) dedup deportista: mismo CI en la misma org -> CIDuplicado (409)
# --------------------------------------------------------------------------- #
@pytest.mark.db
def test_dedup_deportista_mismo_ci_misma_org(app_engine: Engine, ci_fixture: dict) -> None:
    org_a, suc_a = ci_fixture["org_a"], ci_fixture["suc_a"]
    ci = f"CI-{uuid.uuid4().hex[:10]}"

    with Session(app_engine, expire_on_commit=False) as db:
        _set_org(db, org_a)
        svc.crear_deportista(
            db, _body(suc_id=suc_a, nombres="Primero", ci=ci, tutores=[_tutor("T1")]), org_id=org_a
        )
        db.commit()

    # Segundo con el MISMO CI en la MISMA org -> CIDuplicado (pre-chequeo).
    with Session(app_engine, expire_on_commit=False) as db:
        _set_org(db, org_a)
        with pytest.raises(svc.CIDuplicado):
            svc.crear_deportista(
                db,
                _body(suc_id=suc_a, nombres="Segundo", ci=ci, tutores=[_tutor("T2")]),
                org_id=org_a,
            )


# --------------------------------------------------------------------------- #
# (b) múltiples deportistas con ci=NULL permitidos (índice único PARCIAL)
# --------------------------------------------------------------------------- #
@pytest.mark.db
def test_multiples_ci_null_permitidos(app_engine: Engine, ci_fixture: dict) -> None:
    org_a, suc_a = ci_fixture["org_a"], ci_fixture["suc_a"]
    with Session(app_engine, expire_on_commit=False) as db:
        _set_org(db, org_a)
        # Dos deportistas sin CI y dos tutores sin CI: no debe haber colisión.
        svc.crear_deportista(
            db,
            _body(suc_id=suc_a, nombres="SinCI 1", ci=None, tutores=[_tutor("Tut sin CI 1")]),
            org_id=org_a,
        )
        svc.crear_deportista(
            db,
            _body(suc_id=suc_a, nombres="SinCI 2", ci=None, tutores=[_tutor("Tut sin CI 2")]),
            org_id=org_a,
        )
        db.commit()
        # Ambos persistieron (sin IntegrityError).
        total = db.execute(
            text("SELECT count(*) FROM deportista WHERE org_id = :o AND ci IS NULL"),
            {"o": str(org_a)},
        ).scalar_one()
    assert total == 2


# --------------------------------------------------------------------------- #
# (c) mismo CI en orgs DISTINTAS permitido (unicidad POR ORG)
# --------------------------------------------------------------------------- #
@pytest.mark.db
def test_mismo_ci_orgs_distintas_permitido(app_engine: Engine, ci_fixture: dict) -> None:
    org_a, suc_a = ci_fixture["org_a"], ci_fixture["suc_a"]
    org_b, suc_b = ci_fixture["org_b"], ci_fixture["suc_b"]
    ci = f"CI-{uuid.uuid4().hex[:10]}"

    with Session(app_engine, expire_on_commit=False) as db:
        _set_org(db, org_a)
        svc.crear_deportista(
            db, _body(suc_id=suc_a, nombres="En A", ci=ci, tutores=[_tutor("Ta")]), org_id=org_a
        )
        db.commit()

    # Mismo CI, otra org -> NO debe chocar (índice parcial es por (org_id, ci)).
    with Session(app_engine, expire_on_commit=False) as db:
        _set_org(db, org_b)
        dep_b = svc.crear_deportista(
            db, _body(suc_id=suc_b, nombres="En B", ci=ci, tutores=[_tutor("Tb")]), org_id=org_b
        )
        db.commit()
    assert dep_b.ci == ci and dep_b.org_id == org_b


# --------------------------------------------------------------------------- #
# (d) buscar_deportista_por_ci recupera / None
# --------------------------------------------------------------------------- #
@pytest.mark.db
def test_buscar_deportista_por_ci(app_engine: Engine, ci_fixture: dict) -> None:
    org_a, suc_a = ci_fixture["org_a"], ci_fixture["suc_a"]
    org_b = ci_fixture["org_b"]
    ci = f"CI-{uuid.uuid4().hex[:10]}"

    with Session(app_engine, expire_on_commit=False) as db:
        _set_org(db, org_a)
        creado = svc.crear_deportista(
            db, _body(suc_id=suc_a, nombres="Buscable", ci=ci, tutores=[_tutor("Td")]), org_id=org_a
        )
        db.commit()
        creado_id = creado.id

    # En A: lo recupera.
    with Session(app_engine, expire_on_commit=False) as db:
        _set_org(db, org_a)
        encontrado = svc.buscar_deportista_por_ci(db, ci)
        assert encontrado is not None and encontrado.id == creado_id
        # CI inexistente -> None.
        assert svc.buscar_deportista_por_ci(db, "CI-no-existe-xyz") is None

    # En B (otra org): RLS lo oculta -> None (no se filtra cross-org).
    with Session(app_engine, expire_on_commit=False) as db:
        _set_org(db, org_b)
        assert svc.buscar_deportista_por_ci(db, ci) is None


# --------------------------------------------------------------------------- #
# (e) tutor recuperado por CI en el alta + teléfono actualizado (sin duplicar)
# --------------------------------------------------------------------------- #
@pytest.mark.db
def test_tutor_recuperado_por_ci_actualiza_telefono(app_engine: Engine, ci_fixture: dict) -> None:
    org_a, suc_a = ci_fixture["org_a"], ci_fixture["suc_a"]
    tutor_ci = f"CIT-{uuid.uuid4().hex[:10]}"

    # Primer deportista con un tutor que tiene CI + teléfono inicial.
    with Session(app_engine, expire_on_commit=False) as db:
        _set_org(db, org_a)
        svc.crear_deportista(
            db,
            _body(
                suc_id=suc_a,
                nombres="Hijo 1",
                ci=f"CI-{uuid.uuid4().hex[:10]}",
                tutores=[_tutor("Papá", ci=tutor_ci, telefono="70000001")],
            ),
            org_id=org_a,
        )
        db.commit()
        tutor_id_1 = svc.buscar_tutor_por_ci(db, tutor_ci).id  # type: ignore[union-attr]

    # Segundo deportista con el MISMO tutor_ci pero teléfono NUEVO -> reusa el tutor
    # (mismo id) y actualiza el teléfono. No se crea un tutor duplicado.
    with Session(app_engine, expire_on_commit=False) as db:
        _set_org(db, org_a)
        svc.crear_deportista(
            db,
            _body(
                suc_id=suc_a,
                nombres="Hijo 2",
                ci=f"CI-{uuid.uuid4().hex[:10]}",
                tutores=[_tutor("Papá", ci=tutor_ci, telefono="79999999")],
            ),
            org_id=org_a,
        )
        db.commit()

    with Session(app_engine, expire_on_commit=False) as db:
        _set_org(db, org_a)
        tutor = svc.buscar_tutor_por_ci(db, tutor_ci)
        assert tutor is not None
        assert tutor.id == tutor_id_1, "se reusa el MISMO tutor (no duplica)"
        assert tutor.telefono == "79999999", "teléfono actualizado al valor entrante"
        # Solo existe UN tutor con ese CI en la org.
        n = db.execute(
            text("SELECT count(*) FROM tutor WHERE org_id = :o AND ci = :ci"),
            {"o": str(org_a), "ci": tutor_ci},
        ).scalar_one()
    assert n == 1


# --------------------------------------------------------------------------- #
# (f) tutor SIN CI se crea normal (no se reusa, múltiples NULL conviven)
# --------------------------------------------------------------------------- #
@pytest.mark.db
def test_tutor_sin_ci_se_crea_normal(app_engine: Engine, ci_fixture: dict) -> None:
    org_a, suc_a = ci_fixture["org_a"], ci_fixture["suc_a"]
    with Session(app_engine, expire_on_commit=False) as db:
        _set_org(db, org_a)
        svc.crear_deportista(
            db,
            _body(
                suc_id=suc_a,
                nombres="Con tutor sin CI A",
                ci=f"CI-{uuid.uuid4().hex[:10]}",
                tutores=[_tutor("Tutor anónimo A", ci=None, telefono="70000010")],
            ),
            org_id=org_a,
        )
        svc.crear_deportista(
            db,
            _body(
                suc_id=suc_a,
                nombres="Con tutor sin CI B",
                ci=f"CI-{uuid.uuid4().hex[:10]}",
                tutores=[_tutor("Tutor anónimo B", ci=None, telefono="70000011")],
            ),
            org_id=org_a,
        )
        db.commit()
        n = db.execute(
            text("SELECT count(*) FROM tutor WHERE org_id = :o AND ci IS NULL"),
            {"o": str(org_a)},
        ).scalar_one()
    # Dos tutores SIN CI conviven (no se reusan entre sí).
    assert n == 2
