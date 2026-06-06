"""Tests del módulo de Asistencia (contrato C2).

- Lógica pura (sin BD): contadores del resumen + scoping de sucursales por rol.
- Tests marcados `db` (requieren Postgres migrado con 0004 + RLS): roster
  (get-or-create lógico), guardar + re-guardar idempotente (no duplica filas),
  y scoping por rol (ENTRENADOR fuera de su sucursal -> CategoriaFuera = 403).

Se usa `owner_engine` para sembrar (saltando RLS) y una Session sobre
`app_engine` (rol `latinosport_app`, NOBYPASSRLS) para ejercitar el servicio bajo RLS
real. Skip si no hay BD (ver conftest).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import date

import pytest
from app.services import asistencia as svc
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session


# --------------------------------------------------------------------------- #
# Lógica pura (sin BD)
# --------------------------------------------------------------------------- #
def test_contar_resumen_cuenta_estados() -> None:
    presentes, ausentes, total = svc.contar_resumen(
        ["PRESENTE", "AUSENTE", "PRESENTE", None]
    )
    assert presentes == 2
    assert ausentes == 1
    assert total == 4  # total = filas (incluye sin marcar)


def test_contar_resumen_vacio() -> None:
    assert svc.contar_resumen([]) == (0, 0, 0)


def test_admin_ve_todas_las_sucursales() -> None:
    """ADMIN -> None (sin restricción de sucursal)."""
    assert svc._sucursales_permitidas("ADMIN", ["no-importa"]) is None


def test_entrenador_limitado_a_sus_sucursales() -> None:
    s1 = str(uuid.uuid4())
    s2 = str(uuid.uuid4())
    permitidas = svc._sucursales_permitidas("ENTRENADOR", [s1, s2, "invalido"])
    assert permitidas == {uuid.UUID(s1), uuid.UUID(s2)}


def test_entrenador_sin_sucursales_no_ve_nada() -> None:
    assert svc._sucursales_permitidas("ENTRENADOR", []) == set()


# --------------------------------------------------------------------------- #
# Fixture de datos (2 sucursales A/B, 1 categoría + alumnos cada una)
# --------------------------------------------------------------------------- #
@pytest.fixture()
def asis_fixture(owner_engine: Engine) -> Iterator[dict]:
    """Org + sucursales A/B + categoría A/B + 2 alumnos en A, 1 en B + 1 usuario.

    Devuelve ids. Limpia al final (orden FK-safe: asistencia -> sesion -> ...).
    """
    org = uuid.uuid4()
    suc_a = uuid.uuid4()
    suc_b = uuid.uuid4()
    cat_a = uuid.uuid4()
    cat_b = uuid.uuid4()
    al_a1 = uuid.uuid4()
    al_a2 = uuid.uuid4()
    al_b1 = uuid.uuid4()
    usuario = uuid.uuid4()

    with owner_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO organizacion (id, nombre, pais, moneda, modo_cobro_default, "
                "prorratea_primer_periodo, created_at, updated_at) "
                "VALUES (:id,'Org Asis (test)','BO','BOB','ANIVERSARIO',true,now(),now())"
            ),
            {"id": str(org)},
        )
        conn.execute(
            text(
                "INSERT INTO usuario (id, org_id, email, password_hash, role, nombre, activo, "
                "created_at, updated_at) "
                "VALUES (:id,:org,:email,'x','ADMIN','Admin Test',true,now(),now())"
            ),
            {"id": str(usuario), "org": str(org), "email": f"asis_{uuid.uuid4().hex}@test.bo"},
        )
        for suc_id, nom in ((suc_a, "Suc A"), (suc_b, "Suc B")):
            conn.execute(
                text(
                    "INSERT INTO sucursal (id, org_id, nombre, created_at, updated_at) "
                    "VALUES (:id,:org,:nom,now(),now())"
                ),
                {"id": str(suc_id), "org": str(org), "nom": nom},
            )
        for cat_id, suc_id, nom in (
            (cat_a, suc_a, "Cat A"),
            (cat_b, suc_b, "Cat B"),
        ):
            conn.execute(
                text(
                    "INSERT INTO categoria (id, org_id, sucursal_id, nombre, nivel, "
                    "created_at, updated_at) "
                    "VALUES (:id,:org,:suc,:nom,'PRINCIPIANTE',now(),now())"
                ),
                {"id": str(cat_id), "org": str(org), "suc": str(suc_id), "nom": nom},
            )
        for al_id, suc_id, cat_id, nom in (
            (al_a1, suc_a, cat_a, "Ana"),
            (al_a2, suc_a, cat_a, "Bruno"),
            (al_b1, suc_b, cat_b, "Carla"),
        ):
            conn.execute(
                text(
                    "INSERT INTO alumno (id, org_id, sucursal_id, categoria_id, nombres, "
                    "created_at, updated_at) "
                    "VALUES (:id,:org,:suc,:cat,:nom,now(),now())"
                ),
                {
                    "id": str(al_id),
                    "org": str(org),
                    "suc": str(suc_id),
                    "cat": str(cat_id),
                    "nom": nom,
                },
            )

    yield {
        "org": org,
        "suc_a": suc_a,
        "suc_b": suc_b,
        "cat_a": cat_a,
        "cat_b": cat_b,
        "al_a1": al_a1,
        "al_a2": al_a2,
        "al_b1": al_b1,
        "usuario": usuario,
    }

    with owner_engine.begin() as conn:
        conn.execute(text("DELETE FROM asistencia WHERE org_id = :o"), {"o": str(org)})
        conn.execute(text("DELETE FROM sesion WHERE org_id = :o"), {"o": str(org)})
        conn.execute(text("DELETE FROM alumno WHERE org_id = :o"), {"o": str(org)})
        conn.execute(text("DELETE FROM categoria WHERE org_id = :o"), {"o": str(org)})
        conn.execute(text("DELETE FROM sucursal WHERE org_id = :o"), {"o": str(org)})
        conn.execute(text("DELETE FROM usuario WHERE org_id = :o"), {"o": str(org)})
        conn.execute(text("DELETE FROM organizacion WHERE id = :o"), {"o": str(org)})


def _set_org(db: Session, org: uuid.UUID) -> None:
    db.execute(text("SELECT set_config('app.current_org', :o, true)"), {"o": str(org)})


# --------------------------------------------------------------------------- #
# Tests con BD
# --------------------------------------------------------------------------- #
@pytest.mark.db
def test_roster_sin_sesion_estados_null(app_engine: Engine, asis_fixture: dict) -> None:
    """Roster get-or-create lógico: sin sesión -> sesion None y estados null."""
    org = asis_fixture["org"]
    with Session(app_engine) as db:
        _set_org(db, org)
        cat, sesion, alumnos, estados = svc.obtener_roster(
            db,
            categoria_id=asis_fixture["cat_a"],
            fecha=date(2026, 6, 1),
            role="ADMIN",
            sucursal_ids=[],
        )
    assert sesion is None
    assert estados == {}
    assert {a.id for a in alumnos} == {asis_fixture["al_a1"], asis_fixture["al_a2"]}
    assert cat.id == asis_fixture["cat_a"]


@pytest.mark.db
def test_guardar_y_reguardar_idempotente(app_engine: Engine, asis_fixture: dict) -> None:
    """Guardar crea sesión + marcas; re-guardar actualiza sin duplicar (UNIQUE)."""
    org = asis_fixture["org"]
    fecha = date(2026, 6, 2)

    # 1) Primer guardado: Ana PRESENTE, Bruno AUSENTE.
    with Session(app_engine) as db:
        _set_org(db, org)
        _cat, sesion = svc.guardar_asistencia(
            db,
            org_id=org,
            categoria_id=asis_fixture["cat_a"],
            fecha=fecha,
            hora=None,
            marcas=[
                (asis_fixture["al_a1"], "PRESENTE"),
                (asis_fixture["al_a2"], "AUSENTE"),
            ],
            registrado_por=asis_fixture["usuario"],
            role="ADMIN",
            sucursal_ids=[],
        )
        sesion_id = sesion.id
        db.commit()

    with app_engine.begin() as conn:
        conn.execute(text("SELECT set_config('app.current_org', :o, true)"), {"o": str(org)})
        n_ses = conn.execute(
            text("SELECT count(*) FROM sesion WHERE org_id=:o"), {"o": str(org)}
        ).scalar_one()
        n_asis = conn.execute(
            text("SELECT count(*) FROM asistencia WHERE sesion_id=:s"), {"s": str(sesion_id)}
        ).scalar_one()
    assert n_ses == 1
    assert n_asis == 2

    # 2) Re-guardado mismo (categoria, fecha): cambia Bruno a PRESENTE.
    with Session(app_engine) as db:
        _set_org(db, org)
        _cat, sesion2 = svc.guardar_asistencia(
            db,
            org_id=org,
            categoria_id=asis_fixture["cat_a"],
            fecha=fecha,
            hora=None,
            marcas=[
                (asis_fixture["al_a1"], "PRESENTE"),
                (asis_fixture["al_a2"], "PRESENTE"),
            ],
            registrado_por=asis_fixture["usuario"],
            role="ADMIN",
            sucursal_ids=[],
        )
        # Capturar el id ANTES del commit (expire_on_commit detacha el objeto).
        sesion2_id = sesion2.id
        db.commit()
    assert sesion2_id == sesion_id, "Re-guardar debe reusar la misma sesión (no crea otra)"

    # Idempotencia real: no se duplicaron filas y Bruno quedó PRESENTE (upsert).
    with app_engine.begin() as conn:
        conn.execute(text("SELECT set_config('app.current_org', :o, true)"), {"o": str(org)})
        n_ses2 = conn.execute(
            text("SELECT count(*) FROM sesion WHERE org_id=:o"), {"o": str(org)}
        ).scalar_one()
        n_asis2 = conn.execute(
            text("SELECT count(*) FROM asistencia WHERE sesion_id=:s"), {"s": str(sesion_id)}
        ).scalar_one()
        bruno = conn.execute(
            text("SELECT estado FROM asistencia WHERE sesion_id=:s AND alumno_id=:a"),
            {"s": str(sesion_id), "a": str(asis_fixture["al_a2"])},
        ).scalar_one()
    assert n_ses2 == 1, "Re-guardar no debe crear otra sesión"
    assert n_asis2 == 2, "Re-guardar no debe duplicar filas de asistencia"
    assert bruno == "PRESENTE", "El upsert debe actualizar el estado de Bruno"

    with app_engine.begin() as conn:
        conn.execute(text("SELECT set_config('app.current_org', :o, true)"), {"o": str(org)})
        n_ses = conn.execute(
            text("SELECT count(*) FROM sesion WHERE org_id=:o"), {"o": str(org)}
        ).scalar_one()
        n_asis = conn.execute(
            text("SELECT count(*) FROM asistencia WHERE sesion_id=:s"), {"s": str(sesion_id)}
        ).scalar_one()
        presentes = conn.execute(
            text(
                "SELECT count(*) FROM asistencia WHERE sesion_id=:s AND estado='PRESENTE'"
            ),
            {"s": str(sesion_id)},
        ).scalar_one()
    assert n_ses == 1, "No debe duplicar la sesión"
    assert n_asis == 2, "No debe duplicar filas de asistencia (UNIQUE sesion_id, alumno_id)"
    assert presentes == 2, "El re-guardado debe ACTUALIZAR el estado de Bruno"


@pytest.mark.db
def test_entrenador_no_ve_categoria_de_otra_sucursal(
    app_engine: Engine, asis_fixture: dict
) -> None:
    """ENTRENADOR con solo Suc A: pedir Cat B (de Suc B) -> CategoriaFuera (403)."""
    org = asis_fixture["org"]
    coach_sucs = [str(asis_fixture["suc_a"])]

    with Session(app_engine) as db:
        _set_org(db, org)
        # Su propia categoría (Cat A) sí la ve.
        cat, _sesion, _alumnos, _estados = svc.obtener_roster(
            db,
            categoria_id=asis_fixture["cat_a"],
            fecha=date(2026, 6, 3),
            role="ENTRENADOR",
            sucursal_ids=coach_sucs,
        )
        assert cat.id == asis_fixture["cat_a"]

        # Cat B (otra sucursal) -> fuera de alcance.
        with pytest.raises(svc.CategoriaFuera):
            svc.obtener_roster(
                db,
                categoria_id=asis_fixture["cat_b"],
                fecha=date(2026, 6, 3),
                role="ENTRENADOR",
                sucursal_ids=coach_sucs,
            )

        # Tampoco puede guardar en Cat B.
        with pytest.raises(svc.CategoriaFuera):
            svc.guardar_asistencia(
                db,
                org_id=org,
                categoria_id=asis_fixture["cat_b"],
                fecha=date(2026, 6, 3),
                hora=None,
                marcas=[(asis_fixture["al_b1"], "PRESENTE")],
                registrado_por=asis_fixture["usuario"],
                role="ENTRENADOR",
                sucursal_ids=coach_sucs,
            )


@pytest.mark.db
def test_categorias_listadas_por_rol(app_engine: Engine, asis_fixture: dict) -> None:
    """ADMIN ve A y B; ENTRENADOR (Suc A) solo A, con total_alumnos correcto."""
    org = asis_fixture["org"]
    with Session(app_engine) as db:
        _set_org(db, org)
        admin = svc.listar_categorias(db, role="ADMIN", sucursal_ids=[])
        coach = svc.listar_categorias(
            db, role="ENTRENADOR", sucursal_ids=[str(asis_fixture["suc_a"])]
        )

    admin_ids = {c.id for (c, _t) in admin}
    assert asis_fixture["cat_a"] in admin_ids
    assert asis_fixture["cat_b"] in admin_ids

    coach_ids = {c.id: t for (c, t) in coach}
    assert set(coach_ids) == {asis_fixture["cat_a"]}, "ENTRENADOR solo ve su sucursal"
    assert coach_ids[asis_fixture["cat_a"]] == 2, "Cat A tiene 2 alumnos"
