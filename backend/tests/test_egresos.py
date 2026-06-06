"""Tests del módulo de Egresos (RF-FIN-07, contratos C1/C2).

Dos capas, igual que el resto de la suite:

- **Sin BD** (rápidos, siempre corren): validación de schema (`monto <= 0` y
  `categoria_gasto` vacío -> 422) y autorización pura de `require_role` (ADMIN
  pasa / ENTRENADOR -> 403), sin tocar Postgres.
- **Con BD** (`@pytest.mark.db`, requieren Postgres migrado con `0005` + RLS + rol
  `latinosport_app`): aislamiento RLS de `egreso` (fail-closed sin contexto, org A no
  ve org B), `total_monto` = SUM sobre TODO el filtro (no la página), alta auditada
  (`registrado_por` = usuario del token), y el egreso a nivel org (`sucursal_id`
  NULL) excluido del filtro por sucursal y mostrado con `sucursal: null`.

Se usa `owner_engine` para sembrar (saltando RLS) y una `Session` sobre
`app_engine` (rol `latinosport_app`, NOBYPASSRLS) para ejercitar el servicio bajo RLS
real. Skip si no hay BD (ver conftest). Los `@pytest.mark.db` los corre main en F4
contra Postgres.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import date
from decimal import Decimal

import pytest
from app.core.tenant import CurrentUser, require_role
from app.schemas.egreso import EgresoCreate
from app.services import egreso as svc
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session


# --------------------------------------------------------------------------- #
# Validación de schema (sin BD) — caso (d): monto <= 0 / categoría vacía -> 422
# --------------------------------------------------------------------------- #
def test_egreso_create_schema_ok() -> None:
    obj = EgresoCreate(
        sucursal_id=None,
        categoria_gasto="Alquiler de cancha",
        monto=Decimal("1500.00"),
        fecha=date(2026, 6, 1),
        descripcion="  Junio  ",
    )
    assert obj.categoria_gasto == "Alquiler de cancha"
    assert obj.descripcion == "Junio"  # normaliza (strip)


def test_egreso_create_monto_cero_falla() -> None:
    """`monto == 0` -> ValidationError (=> 422 en la API)."""
    with pytest.raises(ValidationError):
        EgresoCreate(
            categoria_gasto="X",
            monto=Decimal("0"),
            fecha=date(2026, 6, 1),
        )


def test_egreso_create_monto_negativo_falla() -> None:
    """`monto < 0` -> ValidationError (=> 422 en la API)."""
    with pytest.raises(ValidationError):
        EgresoCreate(
            categoria_gasto="X",
            monto=Decimal("-10.00"),
            fecha=date(2026, 6, 1),
        )


def test_egreso_create_categoria_vacia_falla() -> None:
    """`categoria_gasto` en blanco -> ValidationError (=> 422 en la API)."""
    with pytest.raises(ValidationError):
        EgresoCreate(
            categoria_gasto="   ",
            monto=Decimal("100.00"),
            fecha=date(2026, 6, 1),
        )


def test_egreso_create_descripcion_blanca_a_none() -> None:
    """`descripcion` en blanco se normaliza a None (no string vacío)."""
    obj = EgresoCreate(
        categoria_gasto="X",
        monto=Decimal("100.00"),
        fecha=date(2026, 6, 1),
        descripcion="   ",
    )
    assert obj.descripcion is None


# --------------------------------------------------------------------------- #
# Autorización (sin BD) — caso (b): ADMIN pasa / ENTRENADOR -> 403
# --------------------------------------------------------------------------- #
def _user(role: str) -> CurrentUser:
    return CurrentUser(user_id=str(uuid.uuid4()), org_id=str(uuid.uuid4()), role=role)


def test_require_role_admin_pasa() -> None:
    """ADMIN supera `require_role('ADMIN')` y recibe de vuelta su CurrentUser."""
    checker = require_role("ADMIN")
    user = _user("ADMIN")
    # `set_tenant_context` no se ejecuta aquí (lo inyecta FastAPI); probamos la
    # rama de autorización pasándole el user directamente.
    assert checker(user=user) is user


def test_require_role_entrenador_403() -> None:
    """ENTRENADOR -> HTTPException 403 (rol fuera del alcance financiero)."""
    checker = require_role("ADMIN")
    with pytest.raises(HTTPException) as exc:
        checker(user=_user("ENTRENADOR"))
    assert exc.value.status_code == 403


# --------------------------------------------------------------------------- #
# Fixture de datos con BD: 2 orgs, sucursal en A, 1 usuario admin en A.
# Org A: varios egresos (con/sin sucursal, fechas/categorías variadas).
# Org B: 1 egreso (para el cruce de aislamiento).
# --------------------------------------------------------------------------- #
@pytest.fixture()
def egreso_fixture(owner_engine: Engine) -> Iterator[dict]:
    org_a = uuid.uuid4()
    org_b = uuid.uuid4()
    suc_a = uuid.uuid4()
    usuario_a = uuid.uuid4()

    # Egresos de org A: 3 en sucursal Centro + 1 a nivel org (sin sucursal).
    # Total org A = 1500 + 800 + 500 + 320 = 3120; sucursal = 1500+800+500 = 2800.
    egresos_a = [
        (uuid.uuid4(), suc_a, "Alquiler de cancha", Decimal("1500.00"), date(2026, 6, 1)),
        (uuid.uuid4(), suc_a, "Material deportivo", Decimal("800.00"), date(2026, 6, 2)),
        (uuid.uuid4(), suc_a, "Material deportivo", Decimal("500.00"), date(2026, 6, 3)),
        (uuid.uuid4(), None, "Servicios", Decimal("320.00"), date(2026, 6, 4)),
    ]
    egreso_b = (uuid.uuid4(), "Gasto de B", Decimal("999.00"), date(2026, 6, 1))

    with owner_engine.begin() as conn:
        for org_id, nombre in ((org_a, "Org A Egr (test)"), (org_b, "Org B Egr (test)")):
            conn.execute(
                text(
                    "INSERT INTO organizacion (id, nombre, pais, moneda, modo_cobro_default, "
                    "prorratea_primer_periodo, created_at, updated_at) "
                    "VALUES (:id,:nom,'BO','BOB','ANIVERSARIO',true,now(),now())"
                ),
                {"id": str(org_id), "nom": nombre},
            )
        conn.execute(
            text(
                "INSERT INTO sucursal (id, org_id, nombre, created_at, updated_at) "
                "VALUES (:id,:org,'Centro',now(),now())"
            ),
            {"id": str(suc_a), "org": str(org_a)},
        )
        conn.execute(
            text(
                "INSERT INTO usuario (id, org_id, email, password_hash, role, nombre, activo, "
                "created_at, updated_at) "
                "VALUES (:id,:org,:email,'x','ADMIN','Admin Egr',true,now(),now())"
            ),
            {"id": str(usuario_a), "org": str(org_a), "email": f"egr_{uuid.uuid4().hex}@test.bo"},
        )
        for eid, suc_id, cat, monto, fecha in egresos_a:
            conn.execute(
                text(
                    "INSERT INTO egreso (id, org_id, sucursal_id, categoria_gasto, monto, "
                    "fecha, registrado_por, created_at) "
                    "VALUES (:id,:org,:suc,:cat,:m,:f,:rp,now())"
                ),
                {
                    "id": str(eid),
                    "org": str(org_a),
                    "suc": str(suc_id) if suc_id is not None else None,
                    "cat": cat,
                    "m": monto,
                    "f": fecha,
                    "rp": str(usuario_a),
                },
            )
        beid, bcat, bmonto, bfecha = egreso_b
        conn.execute(
            text(
                "INSERT INTO egreso (id, org_id, sucursal_id, categoria_gasto, monto, "
                "fecha, created_at) "
                "VALUES (:id,:org,NULL,:cat,:m,:f,now())"
            ),
            {"id": str(beid), "org": str(org_b), "cat": bcat, "m": bmonto, "f": bfecha},
        )

    yield {
        "org_a": org_a,
        "org_b": org_b,
        "suc_a": suc_a,
        "usuario_a": usuario_a,
        "egresos_a": egresos_a,
        "egreso_b": egreso_b,
    }

    with owner_engine.begin() as conn:
        for org_id in (org_a, org_b):
            conn.execute(text("DELETE FROM egreso WHERE org_id = :o"), {"o": str(org_id)})
        conn.execute(text("DELETE FROM usuario WHERE org_id = :o"), {"o": str(org_a)})
        conn.execute(text("DELETE FROM sucursal WHERE org_id = :o"), {"o": str(org_a)})
        for org_id in (org_a, org_b):
            conn.execute(text("DELETE FROM organizacion WHERE id = :o"), {"o": str(org_id)})


def _set_org(db: Session, org: uuid.UUID) -> None:
    db.execute(text("SELECT set_config('app.current_org', :o, true)"), {"o": str(org)})


# --------------------------------------------------------------------------- #
# Caso (a): RLS fail-closed + aislamiento org A vs org B
# --------------------------------------------------------------------------- #
@pytest.mark.db
def test_egreso_sin_contexto_no_devuelve_filas(app_engine: Engine, egreso_fixture: dict) -> None:
    """Sin `app.current_org` (GUC nunca seteado) -> 0 filas (fail-closed, no 500)."""
    with app_engine.connect() as conn:
        count = conn.execute(text("SELECT count(*) FROM egreso")).scalar_one()
    assert count == 0, "Sin contexto de tenant, egreso debe devolver 0 filas (fail-closed)"


@pytest.mark.db
def test_egreso_guc_reseteado_no_devuelve_filas(app_engine: Engine, egreso_fixture: dict) -> None:
    """GUC reseteado a '' (patrón NULLIF) -> 0 filas, no `invalid input syntax`."""
    with app_engine.begin() as conn:
        conn.execute(text("SELECT set_config('app.current_org', '', true)"))
        count = conn.execute(text("SELECT count(*) FROM egreso")).scalar_one()
    assert count == 0, "Con GUC '' (reseteado) egreso debe dar 0 filas, no error de cast"


@pytest.mark.db
def test_egreso_org_a_no_ve_org_b(app_engine: Engine, egreso_fixture: dict) -> None:
    """Con org A fijada se ven egresos de A y NINGUNO de B."""
    org_a = egreso_fixture["org_a"]
    org_b = egreso_fixture["org_b"]
    with app_engine.begin() as conn:
        conn.execute(text("SELECT set_config('app.current_org', :o, true)"), {"o": str(org_a)})
        org_ids = {str(r) for r in conn.execute(text("SELECT org_id FROM egreso")).scalars().all()}
    assert str(org_a) in org_ids, "Con org A fijada se deben ver sus egresos"
    assert str(org_b) not in org_ids, "Con org A fijada NO se deben ver egresos de org B"


# --------------------------------------------------------------------------- #
# Caso (c): total_monto = SUM sobre TODO el filtro (no la página)
# --------------------------------------------------------------------------- #
@pytest.mark.db
def test_total_monto_respeta_filtro_no_pagina(app_engine: Engine, egreso_fixture: dict) -> None:
    """`total_monto` suma TODO el filtro aunque la página traiga menos filas.

    Org A tiene 4 egresos (total 3120). Con `page_size=2` la página trae 2 items,
    pero `total` = 4 y `total_monto` = 3120 (no la suma de la página).
    """
    org_a = egreso_fixture["org_a"]
    with Session(app_engine) as db:
        _set_org(db, org_a)
        items, total, total_monto = svc.listar(db, page=1, page_size=2)

    assert len(items) == 2, "page_size=2 limita la página a 2 items"
    assert total == 4, "total = conteo de TODAS las filas que matchean (no la página)"
    assert total_monto == Decimal("3120.00"), "total_monto = SUM sobre TODO el filtro"
    # La suma de la página (1500 + 800, orden fecha desc) es 2300 != total_monto.
    suma_pagina = sum((it.monto for it in items), Decimal("0"))
    assert suma_pagina != total_monto, "total_monto NO debe ser la suma de la página"


@pytest.mark.db
def test_total_monto_respeta_filtro_categoria(app_engine: Engine, egreso_fixture: dict) -> None:
    """Filtrar por categoría acota `total` y `total_monto` a esa categoría."""
    org_a = egreso_fixture["org_a"]
    with Session(app_engine) as db:
        _set_org(db, org_a)
        items, total, total_monto = svc.listar(db, categoria="Material deportivo")
    assert total == 2, "Dos egresos de 'Material deportivo'"
    assert total_monto == Decimal("1300.00"), "800 + 500"
    assert all(it.categoria_gasto == "Material deportivo" for it in items)


# --------------------------------------------------------------------------- #
# Caso (e): POST setea registrado_por del token (auditoría RNF-03)
# --------------------------------------------------------------------------- #
@pytest.mark.db
def test_crear_setea_registrado_por_del_token(app_engine: Engine, egreso_fixture: dict) -> None:
    """`crear` persiste `registrado_por` = usuario pasado por el router (token)."""
    org_a = egreso_fixture["org_a"]
    usuario_a = egreso_fixture["usuario_a"]
    suc_a = egreso_fixture["suc_a"]

    with Session(app_engine) as db:
        _set_org(db, org_a)
        item = svc.crear(
            db,
            EgresoCreate(
                sucursal_id=suc_a,
                categoria_gasto="Sueldo entrenador",
                monto=Decimal("2000.00"),
                fecha=date(2026, 6, 10),
                descripcion=None,
            ),
            org_id=org_a,
            usuario_id=usuario_a,
        )
        creado_id = item.id
        db.commit()

    assert item.registrado_por_nombre == "Admin Egr", "Resuelve el nombre del usuario del token"
    assert item.sucursal is not None and item.sucursal.id == suc_a

    # Verifica en BD que `registrado_por` quedó con el usuario del token (no NULL).
    with app_engine.begin() as conn:
        conn.execute(text("SELECT set_config('app.current_org', :o, true)"), {"o": str(org_a)})
        rp = conn.execute(
            text("SELECT registrado_por FROM egreso WHERE id = :id"),
            {"id": str(creado_id)},
        ).scalar_one()
    assert str(rp) == str(usuario_a), "registrado_por = usuario del token (auditoría)"


# --------------------------------------------------------------------------- #
# Caso (f): egreso sin sucursal -> sucursal null + excluido del filtro por sucursal
# --------------------------------------------------------------------------- #
@pytest.mark.db
def test_egreso_nivel_org_sucursal_null_y_fuera_del_filtro(
    app_engine: Engine, egreso_fixture: dict
) -> None:
    """Egreso sin `sucursal_id`: se lista con `sucursal: null` y el filtro por
    sucursal NO lo incluye (solo trae los atados a esa sucursal)."""
    org_a = egreso_fixture["org_a"]
    suc_a = egreso_fixture["suc_a"]

    with Session(app_engine) as db:
        _set_org(db, org_a)
        # Sin filtro: aparece el egreso a nivel org con sucursal None.
        todos, total_todos, _ = svc.listar(db, page_size=100)
        a_nivel_org = [it for it in todos if it.sucursal is None]

        # Filtrando por la sucursal Centro: NO debe aparecer el de nivel org.
        de_sucursal, total_suc, monto_suc = svc.listar(db, sucursal_id=suc_a, page_size=100)

    assert total_todos == 4
    assert len(a_nivel_org) == 1, "Hay exactamente 1 egreso a nivel org (sucursal null)"
    assert a_nivel_org[0].categoria_gasto == "Servicios"

    assert total_suc == 3, "El filtro por sucursal solo trae los 3 atados a Centro"
    assert all(it.sucursal is not None and it.sucursal.id == suc_a for it in de_sucursal)
    assert monto_suc == Decimal("2800.00"), "1500 + 800 + 500 (excluye el de nivel org)"
