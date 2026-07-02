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


def test_disciplina_invalida_es_deportista_error() -> None:
    """`DisciplinaInvalida` (S3) es un error de negocio traducible a 422 por el router."""
    assert issubclass(svc.DisciplinaInvalida, svc.DeportistaError)
    assert issubclass(svc.DisciplinaInvalida, Exception)


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
    ci: str,
    tutores: list[TutorIn],
    disciplina_id: uuid.UUID | None = None,
) -> DeportistaCreate:
    # El CI del deportista es OPCIONAL; este helper siempre pasa uno explícito.
    return DeportistaCreate(
        sucursal_id=suc_id,
        nombres=nombres,
        ci=ci,
        tutores=tutores,
        disciplina_id=disciplina_id,
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
# (b) múltiples TUTORES con ci=NULL permitidos (índice único PARCIAL)
#
# El "múltiples NULL conviven" aplica tanto a TUTORES como a DEPORTISTAS (el CI del
# deportista es opcional). Aquí los deportistas llevan CI propio y se prueba que dos
# tutores con `ci=None` no chocan con el índice parcial `(org_id, ci) WHERE ci IS NOT NULL`.
# --------------------------------------------------------------------------- #
@pytest.mark.db
def test_multiples_ci_null_permitidos(app_engine: Engine, ci_fixture: dict) -> None:
    org_a, suc_a = ci_fixture["org_a"], ci_fixture["suc_a"]
    with Session(app_engine, expire_on_commit=False) as db:
        _set_org(db, org_a)
        # Deportistas con CI propio (obligatorio) + tutores SIN CI: no debe colisionar.
        svc.crear_deportista(
            db,
            _body(
                suc_id=suc_a,
                nombres="Dep 1",
                ci=f"CI-{uuid.uuid4().hex[:10]}",
                tutores=[_tutor("Tut sin CI 1", ci=None)],
            ),
            org_id=org_a,
        )
        svc.crear_deportista(
            db,
            _body(
                suc_id=suc_a,
                nombres="Dep 2",
                ci=f"CI-{uuid.uuid4().hex[:10]}",
                tutores=[_tutor("Tut sin CI 2", ci=None)],
            ),
            org_id=org_a,
        )
        db.commit()
        # Re-fijar el contexto: `db.commit()` cerró la transacción y
        # `set_config(..., true)` es transaction-local -> sin re-fijar, la query de
        # verificación cae en RLS fail-closed (0 filas).
        _set_org(db, org_a)
        # Ambos tutores SIN CI persistieron (sin IntegrityError por el índice parcial).
        total = db.execute(
            text("SELECT count(*) FROM tutor WHERE org_id = :o AND ci IS NULL"),
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
        # El commit resetea `app.current_org` (set_config local); re-fijar para que el
        # lookup no caiga en RLS fail-closed.
        _set_org(db, org_a)
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
        # Re-fijar contexto tras commit (set_config local -> sino RLS fail-closed -> 0).
        _set_org(db, org_a)
        n = db.execute(
            text("SELECT count(*) FROM tutor WHERE org_id = :o AND ci IS NULL"),
            {"o": str(org_a)},
        ).scalar_one()
    # Dos tutores SIN CI conviven (no se reusan entre sí).
    assert n == 2


# --------------------------------------------------------------------------- #
# (g) Nombre del deportista SIEMPRE en MAYÚSCULAS (modelo `@validates`, sin BD)
# --------------------------------------------------------------------------- #
def test_nombre_deportista_se_guarda_en_mayusculas() -> None:
    from app.models.deportista import Deportista

    d = Deportista(nombres="ana maría", ap_paterno="pérez", ap_materno=None)
    assert d.nombres == "ANA MARÍA"  # respeta acentos
    assert d.ap_paterno == "PÉREZ"
    assert d.ap_materno is None  # None se conserva (no se fuerza string vacío)


# --------------------------------------------------------------------------- #
# (h) CI "0" = placeholder "presentará luego": no identifica (buscar -> None, sin BD)
# --------------------------------------------------------------------------- #
def test_buscar_por_ci_cero_no_identifica_sin_bd() -> None:
    # El guard de "0" retorna None ANTES de tocar la BD (db no se usa); también vacío.
    assert svc.buscar_deportista_por_ci(None, "0") is None  # type: ignore[arg-type]
    assert svc.buscar_deportista_por_ci(None, " 0 ") is None  # type: ignore[arg-type]
    assert svc.buscar_deportista_por_ci(None, "") is None  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# (i) CI "0" permite VARIOS deportistas (placeholder, índice parcial lo excluye)
# --------------------------------------------------------------------------- #
@pytest.mark.db
def test_ci_cero_placeholder_permite_varios(app_engine: Engine, ci_fixture: dict) -> None:
    org_a, suc_a = ci_fixture["org_a"], ci_fixture["suc_a"]
    with Session(app_engine, expire_on_commit=False) as db:
        _set_org(db, org_a)
        # Dos deportistas con CI "0" ("presentará luego") -> ambos OK, SIN CIDuplicado.
        d1 = svc.crear_deportista(
            db,
            _body(suc_id=suc_a, nombres="sin doc uno", ci="0", tutores=[_tutor("T1")]),
            org_id=org_a,
        )
        svc.crear_deportista(
            db,
            _body(suc_id=suc_a, nombres="sin doc dos", ci="0", tutores=[_tutor("T2")]),
            org_id=org_a,
        )
        db.commit()
        assert d1.nombres == "SIN DOC UNO", "el nombre se guarda en mayúsculas"
        _set_org(db, org_a)
        # "0" no identifica -> no se recupera-por-CI (evita MultipleResultsFound).
        assert svc.buscar_deportista_por_ci(db, "0") is None
        n = db.execute(
            text("SELECT count(*) FROM deportista WHERE org_id = :o AND ci = '0'"),
            {"o": str(org_a)},
        ).scalar_one()
    assert n == 2


# --------------------------------------------------------------------------- #
# disciplina_id (S3): FK canónica al catálogo GLOBAL en el alta de deportista
# --------------------------------------------------------------------------- #
@pytest.fixture()
def disciplina_seed(owner_engine: Engine) -> Iterator[dict]:
    """Siembra una disciplina ACTIVA y una INACTIVA en el catálogo global (sin RLS).

    Teardown: nulifica referencias en `deportista` (FK SET NULL no aplica al borrar la
    fila por DELETE de catálogo bajo RESTRICT en categoría; deportista es SET NULL pero
    nulificamos explícito para no depender del orden de fixtures) y hard-deletea.
    """
    activa = uuid.uuid4()
    inactiva = uuid.uuid4()
    suf = uuid.uuid4().hex[:6]
    with owner_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO disciplina (id, nombre, activo, created_at, updated_at) "
                "VALUES (:id, :nom, true, now(), now())"
            ),
            {"id": str(activa), "nom": f"Disc Activa {suf}"},
        )
        conn.execute(
            text(
                "INSERT INTO disciplina (id, nombre, activo, created_at, updated_at) "
                "VALUES (:id, :nom, false, now(), now())"
            ),
            {"id": str(inactiva), "nom": f"Disc Inactiva {suf}"},
        )
    yield {"activa": activa, "inactiva": inactiva}
    with owner_engine.begin() as conn:
        ids = [str(activa), str(inactiva)]
        conn.execute(
            text("UPDATE deportista SET disciplina_id = NULL WHERE disciplina_id = ANY(:ids)"),
            {"ids": ids},
        )
        conn.execute(text("DELETE FROM disciplina WHERE id = ANY(:ids)"), {"ids": ids})


@pytest.mark.db
def test_crear_deportista_con_disciplina_id_persiste(
    app_engine: Engine, ci_fixture: dict, disciplina_seed: dict
) -> None:
    """Alta con `disciplina_id` válido (activo) lo persiste en la FK del deportista."""
    org_a, suc_a = ci_fixture["org_a"], ci_fixture["suc_a"]
    disc_activa = disciplina_seed["activa"]
    ci = f"CI-{uuid.uuid4().hex[:10]}"

    with Session(app_engine, expire_on_commit=False) as db:
        _set_org(db, org_a)
        dep = svc.crear_deportista(
            db,
            _body(
                suc_id=suc_a,
                nombres="Con disciplina",
                ci=ci,
                tutores=[_tutor("Td")],
                disciplina_id=disc_activa,
            ),
            org_id=org_a,
        )
        db.commit()
        dep_id = dep.id

    with Session(app_engine, expire_on_commit=False) as db:
        _set_org(db, org_a)
        persistido = db.execute(
            text("SELECT disciplina_id FROM deportista WHERE id = :i"), {"i": str(dep_id)}
        ).scalar_one()
    assert persistido == disc_activa


@pytest.mark.db
def test_crear_deportista_disciplina_id_inexistente_422(
    app_engine: Engine, ci_fixture: dict
) -> None:
    """`disciplina_id` inexistente -> DisciplinaInvalida (router => 422, NO 500 por FK)."""
    org_a, suc_a = ci_fixture["org_a"], ci_fixture["suc_a"]
    with Session(app_engine, expire_on_commit=False) as db:
        _set_org(db, org_a)
        with pytest.raises(svc.DisciplinaInvalida):
            svc.crear_deportista(
                db,
                _body(
                    suc_id=suc_a,
                    nombres="Disc fantasma",
                    ci=f"CI-{uuid.uuid4().hex[:10]}",
                    tutores=[_tutor("Tx")],
                    disciplina_id=uuid.uuid4(),  # no existe en el catálogo
                ),
                org_id=org_a,
            )


@pytest.mark.db
def test_crear_deportista_disciplina_id_inactiva_422(
    app_engine: Engine, ci_fixture: dict, disciplina_seed: dict
) -> None:
    """`disciplina_id` de una disciplina INACTIVA -> DisciplinaInvalida (=> 422)."""
    org_a, suc_a = ci_fixture["org_a"], ci_fixture["suc_a"]
    with Session(app_engine, expire_on_commit=False) as db:
        _set_org(db, org_a)
        with pytest.raises(svc.DisciplinaInvalida):
            svc.crear_deportista(
                db,
                _body(
                    suc_id=suc_a,
                    nombres="Disc inactiva",
                    ci=f"CI-{uuid.uuid4().hex[:10]}",
                    tutores=[_tutor("Ti")],
                    disciplina_id=disciplina_seed["inactiva"],
                ),
                org_id=org_a,
            )


@pytest.mark.db
def test_por_ci_devuelve_disciplina_id(
    app_engine: Engine, ci_fixture: dict, disciplina_seed: dict
) -> None:
    """El armado del detalle (recuperar-por-CI) expone `disciplina_id` para precargar
    el select en el front. Se verifica que el campo viaja en el schema de salida."""
    from app.api.v1.deportistas import get_deportista
    from app.core.tenant import CurrentUser

    org_a, suc_a = ci_fixture["org_a"], ci_fixture["suc_a"]
    disc_activa = disciplina_seed["activa"]
    ci = f"CI-{uuid.uuid4().hex[:10]}"

    with Session(app_engine, expire_on_commit=False) as db:
        _set_org(db, org_a)
        dep = svc.crear_deportista(
            db,
            _body(
                suc_id=suc_a,
                nombres="Precarga",
                ci=ci,
                tutores=[_tutor("Tp")],
                disciplina_id=disc_activa,
            ),
            org_id=org_a,
        )
        db.commit()
        dep_id = dep.id

    with Session(app_engine, expire_on_commit=False) as db:
        _set_org(db, org_a)
        user = CurrentUser(
            user_id=str(uuid.uuid4()), org_id=str(org_a), role="ADMIN", sucursal_ids=[]
        )
        detalle = get_deportista(deportista_id=dep_id, user=user, db=db)
    assert detalle.disciplina_id == disc_activa
