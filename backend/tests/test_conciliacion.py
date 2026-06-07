"""Tests de conciliación del webhook (C3) — requieren BD migrada.

Criterio de aceptación: webhook con referencia inexistente o monto que no cuadra
⇒ fila en `conciliacion_pendiente`, ningún pago perdido; responde 200 (el servicio
devuelve "conciliacion"). Skip si no hay BD.
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
def org_con_pago_qr(owner_engine: Engine) -> Iterator[dict]:
    """Org + inscripción + cuota + pago QR PENDIENTE (monto 250). Limpia al final."""
    org = uuid.uuid4()
    suc = uuid.uuid4()
    al = uuid.uuid4()
    insc = uuid.uuid4()
    cuota = uuid.uuid4()
    pago = uuid.uuid4()
    qr_ref = f"qr_conc_{uuid.uuid4().hex}"
    monto = Decimal("250.00")

    with owner_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO organizacion (id, nombre, pais, moneda, modo_cobro_default, "
                "prorratea_primer_periodo, created_at, updated_at) "
                "VALUES (:id,'Org Conc (test)','BO','BOB','ANIVERSARIO',true,now(),now())"
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
                "INSERT INTO deportista (id, org_id, sucursal_id, nombres, created_at, updated_at) "
                "VALUES (:id,:org,:suc,'Deportista Conc',now(),now())"
            ),
            {"id": str(al), "org": str(org), "suc": str(suc)},
        )
        conn.execute(
            text(
                "INSERT INTO inscripcion (id, org_id, deportista_id, fecha_inscripcion, "
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

    yield {"org": org, "pago": pago, "qr_ref": qr_ref, "monto": monto}

    with owner_engine.begin() as conn:
        conn.execute(text("DELETE FROM pago_cuota WHERE org_id = :o"), {"o": str(org)})
        conn.execute(text("DELETE FROM pago WHERE org_id = :o"), {"o": str(org)})
        conn.execute(text("DELETE FROM cuota WHERE org_id = :o"), {"o": str(org)})
        conn.execute(text("DELETE FROM inscripcion WHERE org_id = :o"), {"o": str(org)})
        conn.execute(text("DELETE FROM deportista WHERE org_id = :o"), {"o": str(org)})
        conn.execute(text("DELETE FROM sucursal WHERE org_id = :o"), {"o": str(org)})
        conn.execute(text("DELETE FROM organizacion WHERE id = :o"), {"o": str(org)})


def _conc_count(owner_engine: Engine, *, referencia: str) -> int:
    with owner_engine.begin() as conn:
        return conn.execute(
            text("SELECT count(*) FROM conciliacion_pendiente WHERE referencia = :r"),
            {"r": referencia},
        ).scalar_one()


def _limpiar_conc(owner_engine: Engine, *, referencia: str) -> None:
    with owner_engine.begin() as conn:
        conn.execute(
            text("DELETE FROM conciliacion_pendiente WHERE referencia = :r"),
            {"r": referencia},
        )


def test_referencia_inexistente_va_a_conciliacion(app_engine: Engine, owner_engine: Engine) -> None:
    from app.services import pagos as pagos_svc

    ref_inexistente = f"qr_noexiste_{uuid.uuid4().hex}"
    try:
        with Session(app_engine) as db:
            res = pagos_svc.procesar_webhook(
                db,
                transaccion_id=f"tx_{uuid.uuid4().hex}",
                referencia=ref_inexistente,
                monto=Decimal("100.00"),
            )
            db.commit()
        assert res == "conciliacion"
        assert _conc_count(owner_engine, referencia=ref_inexistente) == 1
    finally:
        _limpiar_conc(owner_engine, referencia=ref_inexistente)


def test_monto_no_cuadra_va_a_conciliacion(
    app_engine: Engine, owner_engine: Engine, org_con_pago_qr: dict
) -> None:
    from app.services import pagos as pagos_svc

    qr_ref = org_con_pago_qr["qr_ref"]
    org = org_con_pago_qr["org"]
    # monto esperado 250; enviamos 999 -> conciliación.
    with Session(app_engine) as db:
        res = pagos_svc.procesar_webhook(
            db,
            transaccion_id=f"tx_{uuid.uuid4().hex}",
            referencia=qr_ref,
            monto=Decimal("999.00"),
        )
        db.commit()
    assert res == "conciliacion"
    assert _conc_count(owner_engine, referencia=qr_ref) == 1

    # El pago NO se perdió ni se confirmó: sigue PENDIENTE.
    with app_engine.begin() as conn:
        conn.execute(text("SELECT set_config('app.current_org', :o, true)"), {"o": str(org)})
        estado = conn.execute(
            text("SELECT estado FROM pago WHERE id = :p"),
            {"p": str(org_con_pago_qr["pago"])},
        ).scalar_one()
    assert estado == "PENDIENTE"
