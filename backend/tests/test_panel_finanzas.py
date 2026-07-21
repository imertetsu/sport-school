"""Tests del bloque financiero del Panel de cobranza (egresos + utilidad).

Cubre lo que agrega el epic "Panel: egresos y utilidad del mes":
- `egresos_mes` con desglose efectivo/QR (`egreso.metodo`, migración 0027);
- `utilidad_mes` = ingresos - egresos, método a método (puede ser NEGATIVA);
- `por_sucursal`: las 3 métricas abiertas por sucursal, donde los ingresos se
  atribuyen por la sucursal del deportista de las cuotas del pago;
- un pago que cubre VARIAS cuotas se cuenta UNA sola vez (el DISTINCT del
  subquery pago→sucursal es lo que evita doblar el ingreso);
- los egresos sin sucursal caen en su propia fila, de modo que las filas de
  `por_sucursal` SUMAN exactamente los totales del panel;
- los egresos del mes siguiente no se cuelan en el mes corriente.

Se siembra con `owner_engine` (salta RLS) y se ejercita el endpoint real con una
Session sobre `app_engine` (rol `latinosport_app`, NOBYPASSRLS) bajo RLS. Skip si
no hay BD (ver conftest).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from dateutil.relativedelta import relativedelta
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

# El panel siempre mira el MES CORRIENTE, así que la siembra se ancla a hoy.
HOY = datetime.now(UTC).date()
INICIO_MES = HOY.replace(day=1)


def _en_mes(dia: int) -> date:
    """Una fecha del mes corriente (acota `dia` para no pasarse de mes)."""
    return INICIO_MES.replace(day=min(dia, 28))


def _mes_siguiente() -> date:
    """El día 1 del mes que viene (para probar que NO entra en el KPI)."""
    return INICIO_MES + relativedelta(months=1)


@pytest.fixture()
def panel_fixture(owner_engine: Engine) -> Iterator[dict]:
    """Org con 2 sucursales, 2 deportistas, pagos e egresos del mes corriente.

    Sucursal Norte: 1 pago EFECTIVO de 300 que cubre DOS cuotas (150 + 150) — el
    caso que doblaría el ingreso si el subquery no hiciera DISTINCT.
    Sucursal Sur:   1 pago QR de 200.
    Egresos: 120 EFECTIVO en Norte, 80 QR en Sur, 50 EFECTIVO a nivel org, y uno
    de 999 el mes que viene (no debe contarse).
    """
    org = uuid.uuid4()
    suc_norte, suc_sur = uuid.uuid4(), uuid.uuid4()
    dep_n, dep_s = uuid.uuid4(), uuid.uuid4()
    ins_n, ins_s = uuid.uuid4(), uuid.uuid4()
    cuota_n1, cuota_n2, cuota_s = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    pago_n, pago_s = uuid.uuid4(), uuid.uuid4()
    usuario = uuid.uuid4()

    with owner_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO organizacion (id, nombre, pais, moneda, modo_cobro_default, "
                "prorratea_primer_periodo, created_at, updated_at) "
                "VALUES (:id,'Org Panel (test)','BO','BOB','ANIVERSARIO',true,now(),now())"
            ),
            {"id": str(org)},
        )
        conn.execute(
            text(
                "INSERT INTO usuario (id, org_id, email, password_hash, role, nombre, activo, "
                "created_at, updated_at) "
                "VALUES (:id,:org,:email,'x','ADMIN','Admin Panel',true,now(),now())"
            ),
            {"id": str(usuario), "org": str(org), "email": f"panel_{uuid.uuid4().hex}@test.bo"},
        )
        for suc_id, nombre in ((suc_norte, "Norte"), (suc_sur, "Sur")):
            conn.execute(
                text(
                    "INSERT INTO sucursal (id, org_id, nombre, created_at, updated_at) "
                    "VALUES (:id,:org,:nom,now(),now())"
                ),
                {"id": str(suc_id), "org": str(org), "nom": nombre},
            )
        for dep_id, suc_id, nom in ((dep_n, suc_norte, "Ana"), (dep_s, suc_sur, "Bruno")):
            conn.execute(
                text(
                    "INSERT INTO deportista (id, org_id, sucursal_id, nombres, activo, "
                    "created_at, updated_at) "
                    "VALUES (:id,:org,:suc,:nom,true,now(),now())"
                ),
                {"id": str(dep_id), "org": str(org), "suc": str(suc_id), "nom": nom},
            )
        for ins_id, dep_id in ((ins_n, dep_n), (ins_s, dep_s)):
            conn.execute(
                text(
                    "INSERT INTO inscripcion (id, org_id, deportista_id, estado, monto_mensual, "
                    "created_at, updated_at) "
                    "VALUES (:id,:org,:dep,'ACTIVA',150.00,now(),now())"
                ),
                {"id": str(ins_id), "org": str(org), "dep": str(dep_id)},
            )
        # Dos cuotas para Norte (las cubre UN solo pago) y una para Sur.
        cuotas = (
            (cuota_n1, ins_n, _en_mes(1), Decimal("150.00")),
            (cuota_n2, ins_n, _en_mes(2), Decimal("150.00")),
            (cuota_s, ins_s, _en_mes(1), Decimal("200.00")),
        )
        for cuota_id, ins_id, periodo, monto in cuotas:
            conn.execute(
                text(
                    "INSERT INTO cuota (id, org_id, inscripcion_id, periodo_inicio, periodo_fin, "
                    "vence_el, monto, estado, monto_pagado, generada_en) "
                    "VALUES (:id,:org,:ins,:pi,:pf,:v,:m,'PAGADO',:m,now())"
                ),
                {
                    "id": str(cuota_id),
                    "org": str(org),
                    "ins": str(ins_id),
                    "pi": periodo,
                    "pf": periodo,
                    "v": periodo,
                    "m": monto,
                },
            )
        pagos = (
            (pago_n, "EFECTIVO", Decimal("300.00")),
            (pago_s, "QR", Decimal("200.00")),
        )
        for pago_id, metodo, monto in pagos:
            conn.execute(
                text(
                    "INSERT INTO pago (id, org_id, metodo, estado, monto, pagado_en, "
                    "registrado_por, created_at) "
                    "VALUES (:id,:org,:met,'CONFIRMADO',:m,:pagado,:reg,now())"
                ),
                {
                    "id": str(pago_id),
                    "org": str(org),
                    "met": metodo,
                    "m": monto,
                    "pagado": datetime.combine(_en_mes(5), datetime.min.time(), tzinfo=UTC),
                    "reg": str(usuario),
                },
            )
        # El pago de Norte se reparte entre SUS DOS cuotas (150 + 150 = 300).
        aplicaciones = (
            (pago_n, cuota_n1, Decimal("150.00")),
            (pago_n, cuota_n2, Decimal("150.00")),
            (pago_s, cuota_s, Decimal("200.00")),
        )
        for pago_id, cuota_id, monto in aplicaciones:
            conn.execute(
                text(
                    "INSERT INTO pago_cuota (id, org_id, pago_id, cuota_id, monto_aplicado) "
                    "VALUES (:id,:org,:p,:c,:m)"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "org": str(org),
                    "p": str(pago_id),
                    "c": str(cuota_id),
                    "m": monto,
                },
            )
        egresos = (
            (suc_norte, "EFECTIVO", Decimal("120.00"), _en_mes(6)),
            (suc_sur, "QR", Decimal("80.00"), _en_mes(7)),
            (None, "EFECTIVO", Decimal("50.00"), _en_mes(8)),
            # Mes que viene: NO debe entrar en el KPI del mes corriente.
            (suc_norte, "EFECTIVO", Decimal("999.00"), _mes_siguiente()),
        )
        for suc_id, metodo, monto, fecha in egresos:
            conn.execute(
                text(
                    "INSERT INTO egreso (id, org_id, sucursal_id, categoria_gasto, monto, "
                    "metodo, fecha, registrado_por, created_at) "
                    "VALUES (:id,:org,:suc,'Varios',:m,:met,:f,:reg,now())"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "org": str(org),
                    "suc": str(suc_id) if suc_id else None,
                    "m": monto,
                    "met": metodo,
                    "f": fecha,
                    "reg": str(usuario),
                },
            )

    yield {"org": org, "suc_norte": suc_norte, "suc_sur": suc_sur, "usuario": usuario}

    with owner_engine.begin() as conn:
        for tabla in (
            "credito",
            "egreso",
            "pago_cuota",
            "pago",
            "cuota",
            "inscripcion",
            "deportista",
            "sucursal",
            "usuario",
        ):
            conn.execute(text(f"DELETE FROM {tabla} WHERE org_id = :o"), {"o": str(org)})
        conn.execute(text("DELETE FROM organizacion WHERE id = :o"), {"o": str(org)})


def _panel(app_engine: Engine, org: uuid.UUID):
    """Llama al endpoint del panel con el contexto de tenant fijado (RLS)."""
    from app.api.v1.cobranza import panel

    with Session(app_engine) as db:
        db.execute(text("SELECT set_config('app.current_org', :o, true)"), {"o": str(org)})
        return panel(_user=None, db=db)  # type: ignore[arg-type]


@pytest.mark.db
def test_egresos_mes_desglosa_por_metodo(app_engine: Engine, panel_fixture: dict) -> None:
    """Egresos del mes: 120 EFECTIVO + 80 QR + 50 EFECTIVO (org) = 250."""
    out = _panel(app_engine, panel_fixture["org"])
    assert out.egresos_mes.monto == Decimal("250.00")
    assert out.egresos_mes.efectivo == Decimal("170.00")  # 120 + 50
    assert out.egresos_mes.qr == Decimal("80.00")


@pytest.mark.db
def test_egreso_del_mes_siguiente_no_cuenta(app_engine: Engine, panel_fixture: dict) -> None:
    """El egreso de 999 con fecha del mes que viene queda fuera del KPI."""
    out = _panel(app_engine, panel_fixture["org"])
    assert out.egresos_mes.monto == Decimal("250.00")  # sin los 999


@pytest.mark.db
def test_utilidad_mes_resta_metodo_a_metodo(app_engine: Engine, panel_fixture: dict) -> None:
    """Utilidad = ingresos (300 EFE + 200 QR) - egresos (170 EFE + 80 QR)."""
    out = _panel(app_engine, panel_fixture["org"])
    assert out.ingresos_mes.monto == Decimal("500.00")
    assert out.utilidad_mes.efectivo == Decimal("130.00")  # 300 - 170
    assert out.utilidad_mes.qr == Decimal("120.00")  # 200 - 80
    assert out.utilidad_mes.monto == Decimal("250.00")


@pytest.mark.db
def test_pago_de_dos_cuotas_no_se_cuenta_dos_veces(
    app_engine: Engine, panel_fixture: dict
) -> None:
    """Norte cobró UN pago de 300 sobre DOS cuotas: debe figurar 300, no 600."""
    out = _panel(app_engine, panel_fixture["org"])
    norte = next(s for s in out.por_sucursal if s.sucursal_id == panel_fixture["suc_norte"])
    assert norte.ingresos.monto == Decimal("300.00")
    assert norte.ingresos.efectivo == Decimal("300.00")
    assert norte.ingresos.qr == Decimal("0")


@pytest.mark.db
def test_por_sucursal_incluye_las_tres_metricas(app_engine: Engine, panel_fixture: dict) -> None:
    """Cada sucursal trae ingresos, egresos y utilidad con su desglose."""
    out = _panel(app_engine, panel_fixture["org"])
    norte = next(s for s in out.por_sucursal if s.sucursal_id == panel_fixture["suc_norte"])
    sur = next(s for s in out.por_sucursal if s.sucursal_id == panel_fixture["suc_sur"])

    assert norte.nombre == "Norte"
    assert norte.egresos.efectivo == Decimal("120.00")
    assert norte.utilidad.monto == Decimal("180.00")  # 300 - 120

    assert sur.ingresos.qr == Decimal("200.00")
    assert sur.egresos.qr == Decimal("80.00")
    assert sur.utilidad.monto == Decimal("120.00")  # 200 - 80


@pytest.mark.db
def test_egreso_sin_sucursal_tiene_su_propia_fila(
    app_engine: Engine, panel_fixture: dict
) -> None:
    """El gasto a nivel org va en la fila `sucursal_id=None` (utilidad negativa)."""
    out = _panel(app_engine, panel_fixture["org"])
    sin_suc = next(s for s in out.por_sucursal if s.sucursal_id is None)
    assert sin_suc.egresos.monto == Decimal("50.00")
    assert sin_suc.ingresos.monto == Decimal("0")
    # Solo gastos, ningún ingreso -> la fila cierra en pérdida.
    assert sin_suc.utilidad.monto == Decimal("-50.00")


@pytest.mark.db
def test_credito_de_inscripcion_dada_de_baja_no_suma(
    app_engine: Engine, owner_engine: Engine, panel_fixture: dict
) -> None:
    """El saldo a favor de un alumno de baja NO cuenta en el KPI de crédito.

    Es la misma regla que ya aplican cuotas pendientes/vencidas: la plata a favor
    de quien se fue no es aplicable, y sumarla mostraba un KPI sin dueño.
    """
    org = panel_fixture["org"]
    # Crédito de 30 en la inscripción de Norte, y luego se da de baja al alumno.
    with owner_engine.begin() as conn:
        ins_id = conn.execute(
            text(
                "SELECT i.id FROM inscripcion i JOIN deportista d ON d.id = i.deportista_id "
                "WHERE i.org_id = :o AND d.nombres = 'Ana'"
            ),
            {"o": str(org)},
        ).scalar_one()
        conn.execute(
            text(
                "INSERT INTO credito (id, org_id, inscripcion_id, saldo, created_at, updated_at) "
                "VALUES (:id,:o,:i,30.00,now(),now())"
            ),
            {"id": str(uuid.uuid4()), "o": str(org), "i": str(ins_id)},
        )

    # Activo: el crédito cuenta.
    assert _panel(app_engine, org).credito_total == Decimal("30.00")

    with owner_engine.begin() as conn:
        conn.execute(
            text("UPDATE inscripcion SET estado = 'INACTIVA' WHERE id = :i"),
            {"i": str(ins_id)},
        )

    # Dado de baja: deja de contar.
    assert _panel(app_engine, org).credito_total == Decimal("0")


@pytest.mark.db
def test_filas_por_sucursal_suman_los_totales(app_engine: Engine, panel_fixture: dict) -> None:
    """Invariante del panel: Σ filas == totales del mes (no se pierde plata)."""
    out = _panel(app_engine, panel_fixture["org"])
    for campo in ("monto", "efectivo", "qr"):
        assert sum(getattr(s.ingresos, campo) for s in out.por_sucursal) == getattr(
            out.ingresos_mes, campo
        )
        assert sum(getattr(s.egresos, campo) for s in out.por_sucursal) == getattr(
            out.egresos_mes, campo
        )
        assert sum(getattr(s.utilidad, campo) for s in out.por_sucursal) == getattr(
            out.utilidad_mes, campo
        )
