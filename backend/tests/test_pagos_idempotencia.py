"""Tests de idempotencia de pagos/webhook (C3) — requieren BD migrada.

Criterio de aceptación: el mismo `transaccion_id` reenviado ⇒ sin doble pago,
doble comprobante ni doble `pago_cuota`. Skip si no hay BD.

Se usa `owner_engine` para sembrar (saltando RLS) y una Session sobre `app_engine`
(rol `latinosport_app`, NOBYPASSRLS) para ejercitar el servicio bajo RLS real.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

pytestmark = pytest.mark.db


@pytest.fixture()
def cobranza_fixture(owner_engine: Engine) -> Iterator[dict]:
    """Org + sucursal + alumno + inscripción + 1 cuota PENDIENTE + pago QR PENDIENTE.

    Devuelve ids y `qr_ref`. Limpia al final (orden FK-safe).
    """
    org = uuid.uuid4()
    suc = uuid.uuid4()
    al = uuid.uuid4()
    insc = uuid.uuid4()
    cuota = uuid.uuid4()
    pago = uuid.uuid4()
    qr_ref = f"qr_test_{uuid.uuid4().hex}"
    monto = Decimal("250.00")

    with owner_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO organizacion (id, nombre, pais, moneda, modo_cobro_default, "
                "prorratea_primer_periodo, created_at, updated_at) "
                "VALUES (:id,'Org Pagos (test)','BO','BOB','ANIVERSARIO',true,now(),now())"
            ),
            {"id": str(org)},
        )
        conn.execute(
            text(
                "INSERT INTO sucursal (id, org_id, nombre, created_at, updated_at) "
                "VALUES (:id,:org,'Suc',now(),now())"
            ),
            {"id": str(suc), "org": str(org)},
        )
        conn.execute(
            text(
                "INSERT INTO alumno (id, org_id, sucursal_id, nombres, created_at, updated_at) "
                "VALUES (:id,:org,:suc,'Alumno Pago',now(),now())"
            ),
            {"id": str(al), "org": str(org), "suc": str(suc)},
        )
        conn.execute(
            text(
                "INSERT INTO inscripcion (id, org_id, alumno_id, fecha_inscripcion, "
                "monto_mensual, estado, created_at, updated_at) "
                "VALUES (:id,:org,:al,:f,:m,'ACTIVA',now(),now())"
            ),
            {"id": str(insc), "org": str(org), "al": str(al), "f": date(2025, 1, 10), "m": monto},
        )
        conn.execute(
            text(
                "INSERT INTO cuota (id, org_id, inscripcion_id, periodo_inicio, periodo_fin, "
                "vence_el, monto, estado, es_prorrateo, generada_en) "
                "VALUES (:id,:org,:insc,:pi,:pf,:v,:m,'PENDIENTE',false,now())"
            ),
            {
                "id": str(cuota),
                "org": str(org),
                "insc": str(insc),
                "pi": date(2025, 1, 10),
                "pf": date(2025, 2, 10),
                "v": date(2025, 2, 10),
                "m": monto,
            },
        )
        conn.execute(
            text(
                "INSERT INTO pago (id, org_id, metodo, estado, monto, qr_ref, created_at) "
                "VALUES (:id,:org,'QR','PENDIENTE',:m,:qr,now())"
            ),
            {"id": str(pago), "org": str(org), "m": monto, "qr": qr_ref},
        )
        conn.execute(
            text(
                "INSERT INTO pago_cuota (id, org_id, pago_id, cuota_id, monto_aplicado) "
                "VALUES (:id,:org,:p,:c,:m)"
            ),
            {"id": str(uuid.uuid4()), "org": str(org), "p": str(pago), "c": str(cuota), "m": monto},
        )

    yield {
        "org": org,
        "cuota": cuota,
        "pago": pago,
        "qr_ref": qr_ref,
        "monto": monto,
    }

    with owner_engine.begin() as conn:
        conn.execute(text("DELETE FROM pago_cuota WHERE org_id = :o"), {"o": str(org)})
        conn.execute(text("DELETE FROM pago WHERE org_id = :o"), {"o": str(org)})
        conn.execute(text("DELETE FROM cuota WHERE org_id = :o"), {"o": str(org)})
        conn.execute(text("DELETE FROM inscripcion WHERE org_id = :o"), {"o": str(org)})
        conn.execute(text("DELETE FROM alumno WHERE org_id = :o"), {"o": str(org)})
        conn.execute(text("DELETE FROM sucursal WHERE org_id = :o"), {"o": str(org)})
        conn.execute(
            text("DELETE FROM conciliacion_pendiente WHERE referencia = :r"),
            {"r": str(qr_ref)},
        )
        conn.execute(text("DELETE FROM organizacion WHERE id = :o"), {"o": str(org)})


def _counts(conn, org: uuid.UUID, qr_ref: str) -> dict:
    pagos = conn.execute(
        text("SELECT count(*) FROM pago WHERE org_id=:o"), {"o": str(org)}
    ).scalar_one()
    confirmados = conn.execute(
        text("SELECT count(*) FROM pago WHERE org_id=:o AND estado='CONFIRMADO'"),
        {"o": str(org)},
    ).scalar_one()
    puentes = conn.execute(
        text("SELECT count(*) FROM pago_cuota WHERE org_id=:o"), {"o": str(org)}
    ).scalar_one()
    cuotas_pagadas = conn.execute(
        text("SELECT count(*) FROM cuota WHERE org_id=:o AND estado='PAGADO'"),
        {"o": str(org)},
    ).scalar_one()
    return {
        "pagos": pagos,
        "confirmados": confirmados,
        "puentes": puentes,
        "cuotas_pagadas": cuotas_pagadas,
    }


def test_webhook_confirma_y_es_idempotente(app_engine: Engine, cobranza_fixture: dict) -> None:
    from app.services import pagos as pagos_svc

    org = cobranza_fixture["org"]
    qr_ref = cobranza_fixture["qr_ref"]
    monto = cobranza_fixture["monto"]
    tx = f"tx_{uuid.uuid4().hex}"

    # 1) Primera entrega -> confirma.
    with Session(app_engine) as db:
        res = pagos_svc.procesar_webhook(db, transaccion_id=tx, referencia=qr_ref, monto=monto)
        db.commit()
    assert res == "confirmado"

    with app_engine.begin() as conn:
        conn.execute(text("SELECT set_config('app.current_org', :o, true)"), {"o": str(org)})
        c1 = _counts(conn, org, qr_ref)
    assert c1["confirmados"] == 1
    assert c1["puentes"] == 1
    assert c1["cuotas_pagadas"] == 1

    # 2) Reenvío del MISMO transaccion_id -> idempotente (sin doble nada).
    with Session(app_engine) as db:
        res2 = pagos_svc.procesar_webhook(db, transaccion_id=tx, referencia=qr_ref, monto=monto)
        db.commit()
    assert res2 == "idempotente"

    with app_engine.begin() as conn:
        conn.execute(text("SELECT set_config('app.current_org', :o, true)"), {"o": str(org)})
        c2 = _counts(conn, org, qr_ref)
    assert c2 == c1, "El reenvío no debe crear doble pago/puente ni repagar cuotas"


def test_webhook_distinto_tx_pago_ya_confirmado_idempotente(
    app_engine: Engine, cobranza_fixture: dict
) -> None:
    """Un segundo webhook con OTRO transaccion_id sobre un pago ya confirmado no
    reaplica (idempotencia por estado del pago)."""
    from app.services import pagos as pagos_svc

    org = cobranza_fixture["org"]
    qr_ref = cobranza_fixture["qr_ref"]
    monto = cobranza_fixture["monto"]

    with Session(app_engine) as db:
        pagos_svc.procesar_webhook(
            db, transaccion_id=f"tx_{uuid.uuid4().hex}", referencia=qr_ref, monto=monto
        )
        db.commit()
    with Session(app_engine) as db:
        res = pagos_svc.procesar_webhook(
            db, transaccion_id=f"tx_{uuid.uuid4().hex}", referencia=qr_ref, monto=monto
        )
        db.commit()
    assert res == "idempotente"

    with app_engine.begin() as conn:
        conn.execute(text("SELECT set_config('app.current_org', :o, true)"), {"o": str(org)})
        c = _counts(conn, org, qr_ref)
    assert c["confirmados"] == 1
    assert c["puentes"] == 1
