"""Tests del módulo de Reportes (contrato C1).

- Lógica pura (sin BD): armado de los **12 meses** (relleno con "0.00") y
  `pct_presente` (incluye el caso total = 0).
- Tests marcados `db` (requieren Postgres migrado + RLS): ingresos refleja un
  pago CONFIRMADO y trae 12 meses; asistencia devuelve `pct` coherente con las
  marcas; **403 para ENTRENADOR** en ambos endpoints.

Se siembra con `owner_engine` (salta RLS) y se ejercita el servicio con una
Session sobre `app_engine` (rol `latinosport_app`, NOBYPASSRLS) bajo RLS real. El
403 se prueba contra la API real con un token de ENTRENADOR emitido en memoria
(el gate de rol corre antes de tocar datos). Skip si no hay BD (ver conftest).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from app.services import reportes as svc
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session


# --------------------------------------------------------------------------- #
# Lógica pura (sin BD)
# --------------------------------------------------------------------------- #
def test_armar_meses_devuelve_12_meses() -> None:
    """Siempre 12 meses; los ausentes se rellenan con "0.00" / 0."""
    datos = {3: (Decimal("1500"), 2), 12: (Decimal("300.5"), 1)}
    meses, total, n_pagos = svc.armar_meses(2026, datos)

    assert len(meses) == 12
    assert [m.mes for m in meses] == list(range(1, 13))
    assert meses[0].etiqueta == "ene"
    assert meses[11].etiqueta == "dic"
    # Mes vacío -> "0.00" / 0.
    assert meses[0].monto == "0.00"
    assert meses[0].n_pagos == 0
    # Marzo (index 2) refleja el agregado.
    assert meses[2].monto == "1500.00"
    assert meses[2].n_pagos == 2
    # Totales.
    assert total == Decimal("1800.5")
    assert n_pagos == 3


def test_pct_presente_total_cero_es_cero() -> None:
    assert svc.pct_presente(0, 0) == 0.0


def test_pct_presente_redondea_a_un_decimal() -> None:
    # 2/3 -> 66.666... -> 66.7
    assert svc.pct_presente(2, 3) == 66.7
    assert svc.pct_presente(5, 10) == 50.0


# --------------------------------------------------------------------------- #
# Fixture de datos con BD (1 org, 1 sucursal, 1 categoría, 2 alumnos)
# --------------------------------------------------------------------------- #
@pytest.fixture()
def rep_fixture(owner_engine: Engine) -> Iterator[dict]:
    """Org + sucursal + categoría + 2 alumnos + 1 usuario; pago e inscripción.

    Siembra (saltando RLS): un pago CONFIRMADO en marzo 2026 + una sesión con
    asistencia (1 PRESENTE, 1 AUSENTE). Limpia al final en orden FK-safe.
    """
    org = uuid.uuid4()
    suc = uuid.uuid4()
    cat = uuid.uuid4()
    al1 = uuid.uuid4()
    al2 = uuid.uuid4()
    usuario = uuid.uuid4()
    pago = uuid.uuid4()
    sesion = uuid.uuid4()

    with owner_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO organizacion (id, nombre, pais, moneda, modo_cobro_default, "
                "prorratea_primer_periodo, created_at, updated_at) "
                "VALUES (:id,'Org Rep (test)','BO','BOB','ANIVERSARIO',true,now(),now())"
            ),
            {"id": str(org)},
        )
        conn.execute(
            text(
                "INSERT INTO usuario (id, org_id, email, password_hash, role, nombre, activo, "
                "created_at, updated_at) "
                "VALUES (:id,:org,:email,'x','ADMIN','Admin Rep',true,now(),now())"
            ),
            {"id": str(usuario), "org": str(org), "email": f"rep_{uuid.uuid4().hex}@test.bo"},
        )
        conn.execute(
            text(
                "INSERT INTO sucursal (id, org_id, nombre, created_at, updated_at) "
                "VALUES (:id,:org,'Suc Central',now(),now())"
            ),
            {"id": str(suc), "org": str(org)},
        )
        conn.execute(
            text(
                "INSERT INTO categoria (id, org_id, sucursal_id, nombre, nivel, "
                "created_at, updated_at) "
                "VALUES (:id,:org,:suc,'Sub-14','PRINCIPIANTE',now(),now())"
            ),
            {"id": str(cat), "org": str(org), "suc": str(suc)},
        )
        for al_id, nom in ((al1, "Ana"), (al2, "Bruno")):
            conn.execute(
                text(
                    "INSERT INTO alumno (id, org_id, sucursal_id, categoria_id, nombres, "
                    "created_at, updated_at) "
                    "VALUES (:id,:org,:suc,:cat,:nom,now(),now())"
                ),
                {
                    "id": str(al_id),
                    "org": str(org),
                    "suc": str(suc),
                    "cat": str(cat),
                    "nom": nom,
                },
            )
        # Pago CONFIRMADO en marzo 2026 (mes 3) -> debe reflejarse en ingresos.
        # (El `pago` no tiene FK a inscripción/cuota; ingresos cuenta el pago, no
        # las cuotas, para no doblar — por eso no hace falta sembrar inscripción.)
        conn.execute(
            text(
                "INSERT INTO pago (id, org_id, metodo, estado, monto, pagado_en, "
                "registrado_por, created_at) "
                "VALUES (:id,:org,'EFECTIVO','CONFIRMADO',300.00,"
                ":pagado, :reg, now())"
            ),
            {
                "id": str(pago),
                "org": str(org),
                "pagado": datetime(2026, 3, 15, 10, 0, tzinfo=UTC),
                "reg": str(usuario),
            },
        )
        # Sesión + asistencia (1 PRESENTE, 1 AUSENTE) en marzo 2026.
        conn.execute(
            text(
                "INSERT INTO sesion (id, org_id, categoria_id, fecha, created_at) "
                "VALUES (:id,:org,:cat,:fecha,now())"
            ),
            {"id": str(sesion), "org": str(org), "cat": str(cat), "fecha": date(2026, 3, 15)},
        )
        for al_id, estado in ((al1, "PRESENTE"), (al2, "AUSENTE")):
            conn.execute(
                text(
                    "INSERT INTO asistencia (id, org_id, sesion_id, alumno_id, estado, "
                    "registrado_por, created_at, updated_at) "
                    "VALUES (:id,:org,:ses,:al,:estado,:reg,now(),now())"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "org": str(org),
                    "ses": str(sesion),
                    "al": str(al_id),
                    "estado": estado,
                    "reg": str(usuario),
                },
            )

    yield {
        "org": org,
        "suc": suc,
        "cat": cat,
        "al1": al1,
        "al2": al2,
        "usuario": usuario,
    }

    with owner_engine.begin() as conn:
        conn.execute(text("DELETE FROM asistencia WHERE org_id = :o"), {"o": str(org)})
        conn.execute(text("DELETE FROM sesion WHERE org_id = :o"), {"o": str(org)})
        conn.execute(text("DELETE FROM pago WHERE org_id = :o"), {"o": str(org)})
        conn.execute(text("DELETE FROM alumno WHERE org_id = :o"), {"o": str(org)})
        conn.execute(text("DELETE FROM categoria WHERE org_id = :o"), {"o": str(org)})
        conn.execute(text("DELETE FROM sucursal WHERE org_id = :o"), {"o": str(org)})
        conn.execute(text("DELETE FROM usuario WHERE org_id = :o"), {"o": str(org)})
        conn.execute(text("DELETE FROM organizacion WHERE id = :o"), {"o": str(org)})


def _set_org(db: Session, org: uuid.UUID) -> None:
    db.execute(text("SELECT set_config('app.current_org', :o, true)"), {"o": str(org)})


# --------------------------------------------------------------------------- #
# Tests con BD — servicio
# --------------------------------------------------------------------------- #
@pytest.mark.db
def test_ingresos_12_meses_y_pago_confirmado(app_engine: Engine, rep_fixture: dict) -> None:
    """Ingresos: 12 meses; marzo refleja el pago CONFIRMADO; total/n_pagos del año."""
    org = rep_fixture["org"]
    with Session(app_engine) as db:
        _set_org(db, org)
        rep = svc.ingresos_por_mes(db, anio=2026)

    assert rep.anio == 2026
    assert len(rep.meses) == 12
    marzo = rep.meses[2]
    assert marzo.mes == 3
    assert marzo.etiqueta == "mar"
    assert marzo.monto == "300.00"
    assert marzo.n_pagos == 1
    # Un mes sin pagos -> "0.00".
    assert rep.meses[0].monto == "0.00"
    # Total y n_pagos del año (solo el pago de marzo en esta org).
    assert rep.total == "300.00"
    assert rep.n_pagos == 1


@pytest.mark.db
def test_ingresos_otro_anio_vacio(app_engine: Engine, rep_fixture: dict) -> None:
    """Año sin pagos: 12 meses en "0.00" y total "0.00"."""
    org = rep_fixture["org"]
    with Session(app_engine) as db:
        _set_org(db, org)
        rep = svc.ingresos_por_mes(db, anio=2099)
    assert len(rep.meses) == 12
    assert rep.total == "0.00"
    assert rep.n_pagos == 0
    assert all(m.monto == "0.00" for m in rep.meses)


@pytest.mark.db
def test_asistencia_pct_coherente(app_engine: Engine, rep_fixture: dict) -> None:
    """Asistencia: 1 PRESENTE / 1 AUSENTE -> 50.0% global y por categoría."""
    org = rep_fixture["org"]
    with Session(app_engine) as db:
        _set_org(db, org)
        rep = svc.asistencia_reporte(db, desde=date(2026, 3, 1), hasta=date(2026, 3, 31))

    assert rep.global_.total_marcas == 2
    assert rep.global_.presentes == 1
    assert rep.global_.ausentes == 1
    assert rep.global_.sesiones == 1
    assert rep.global_.pct_presente == 50.0

    assert len(rep.por_categoria) == 1
    fila = rep.por_categoria[0]
    assert fila.categoria.id == rep_fixture["cat"]
    assert fila.categoria.nombre == "Sub-14"
    assert fila.sucursal.nombre == "Suc Central"
    assert fila.total_marcas == 2
    assert fila.pct_presente == 50.0


@pytest.mark.db
def test_asistencia_fuera_de_rango_vacia(app_engine: Engine, rep_fixture: dict) -> None:
    """Rango sin sesiones -> global en 0 y sin categorías."""
    org = rep_fixture["org"]
    with Session(app_engine) as db:
        _set_org(db, org)
        rep = svc.asistencia_reporte(db, desde=date(2026, 1, 1), hasta=date(2026, 1, 31))
    assert rep.global_.total_marcas == 0
    assert rep.global_.pct_presente == 0.0
    assert rep.por_categoria == []


# --------------------------------------------------------------------------- #
# Tests con BD — API (gate de rol: 403 para ENTRENADOR)
# --------------------------------------------------------------------------- #
def _client_or_skip():
    import os

    if not os.getenv("DATABASE_URL"):
        pytest.skip("DATABASE_URL no definido; requiere Postgres migrado")
    from app.main import app
    from fastapi.testclient import TestClient

    return TestClient(app)


def _entrenador_token() -> str:
    """Emite un token de ENTRENADOR (el gate de rol corre antes de tocar datos)."""
    from app.core.security import create_access_token

    return create_access_token(
        user_id=str(uuid.uuid4()),
        org_id=str(uuid.uuid4()),
        role="ENTRENADOR",
        sucursal_ids=[],
    )


@pytest.mark.db
def test_ingresos_403_entrenador() -> None:
    client = _client_or_skip()
    token = _entrenador_token()
    resp = client.get(
        "/api/v1/reportes/ingresos?anio=2026",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


@pytest.mark.db
def test_asistencia_403_entrenador() -> None:
    client = _client_or_skip()
    token = _entrenador_token()
    resp = client.get(
        "/api/v1/reportes/asistencia",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


@pytest.mark.db
def test_reportes_sin_token_401() -> None:
    client = _client_or_skip()
    assert client.get("/api/v1/reportes/ingresos").status_code == 401
    assert client.get("/api/v1/reportes/asistencia").status_code == 401


def test_asistencia_response_usa_clave_global() -> None:
    """El JSON expone `global` (alias), no `global_` (espejo de C1). Sin BD."""
    from app.schemas.reportes import AsistenciaGlobal, AsistenciaReporte

    rep = AsistenciaReporte(
        desde="2026-03-01",
        hasta="2026-03-31",
        global_=AsistenciaGlobal(
            sesiones=1, presentes=1, ausentes=1, total_marcas=2, pct_presente=50.0
        ),
        por_categoria=[],
    )
    dumped = rep.model_dump(by_alias=True)
    assert "global" in dumped
    assert "global_" not in dumped
    assert dumped["global"]["pct_presente"] == 50.0
