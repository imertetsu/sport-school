"""Tests con BD del alta retroactiva de cuotas (epic cuotas históricas).

- `generar_cuotas_historicas`: rellena las cuotas de una inscripción desde su
  `fecha_inscripcion`, idempotente (no duplica al re-correr).
- `reajustar_monto_cuotas_futuras`: al cambiar la cuota, solo toca las cuotas del
  período corriente en adelante sin pago (PENDIENTE/VENCIDO, `monto_pagado == 0`);
  respeta pagadas y períodos ya vencidos.

Patrón (igual que test_recibo): siembra como owner (salta RLS) y ejercita el servicio
en una `Session` sobre `app_engine` (rol `latinosport_app`) bajo RLS real, fijando
`app.current_org`. Requiere Postgres migrado → `@pytest.mark.db`.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import date
from decimal import Decimal

import pytest
from app.services import generacion
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

# "Hoy" fijo para deterministas: inscripción en enero, hoy a inicios de julio.
_HOY = date(2026, 7, 2)


def _seed_inscripcion(conn, *, org: uuid.UUID, monto: str, fecha: date) -> uuid.UUID:
    """Siembra org + sucursal + deportista + inscripción ACTIVA. Devuelve inscripcion_id."""
    suc = uuid.uuid4()
    al = uuid.uuid4()
    insc = uuid.uuid4()
    conn.execute(
        text(
            "INSERT INTO organizacion (id, nombre, pais, moneda, modo_cobro_default, "
            "prorratea_primer_periodo, created_at, updated_at) "
            "VALUES (:id,'Org Retro (test)','BO','BOB','ANIVERSARIO',false,now(),now()) "
            "ON CONFLICT (id) DO NOTHING"
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
            "VALUES (:id,:org,:suc,'Retro',now(),now())"
        ),
        {"id": str(al), "org": str(org), "suc": str(suc)},
    )
    conn.execute(
        text(
            "INSERT INTO inscripcion (id, org_id, deportista_id, fecha_inscripcion, "
            "monto_mensual, estado, created_at, updated_at) "
            "VALUES (:id,:org,:al,:f,:m,'ACTIVA',now(),now())"
        ),
        {"id": str(insc), "org": str(org), "al": str(al), "f": fecha, "m": monto},
    )
    return insc


def _seed_cuota(
    conn,
    *,
    org: uuid.UUID,
    insc: uuid.UUID,
    inicio: date,
    vence: date,
    monto: str,
    estado: str = "PENDIENTE",
    monto_pagado: str = "0",
) -> None:
    conn.execute(
        text(
            "INSERT INTO cuota (id, org_id, inscripcion_id, periodo_inicio, periodo_fin, "
            "vence_el, monto, monto_pagado, estado, es_prorrateo, generada_en) "
            "VALUES (:id,:org,:insc,:pi,:pf,:v,:m,:mp,:e,false,now())"
        ),
        {
            "id": str(uuid.uuid4()),
            "org": str(org),
            "insc": str(insc),
            "pi": inicio,
            "pf": vence,
            "v": vence,
            "m": monto,
            "mp": monto_pagado,
            "e": estado,
        },
    )


@pytest.fixture()
def retro_org(owner_engine: Engine) -> Iterator[dict]:
    """Una org con un deportista inscrito el 11-ene-2026 a Bs 60 (sin cuotas)."""
    org = uuid.uuid4()
    with owner_engine.begin() as conn:
        insc = _seed_inscripcion(conn, org=org, monto="60", fecha=date(2026, 1, 11))
    yield {"org": org, "inscripcion": insc}
    with owner_engine.begin() as conn:
        conn.execute(text("DELETE FROM cuota WHERE org_id = :o"), {"o": str(org)})
        conn.execute(text("DELETE FROM inscripcion WHERE org_id = :o"), {"o": str(org)})
        conn.execute(text("DELETE FROM deportista WHERE org_id = :o"), {"o": str(org)})
        conn.execute(text("DELETE FROM sucursal WHERE org_id = :o"), {"o": str(org)})
        conn.execute(text("DELETE FROM organizacion WHERE id = :o"), {"o": str(org)})


def _con_org(db: Session, org: uuid.UUID) -> None:
    db.execute(text("SELECT set_config('app.current_org', :o, true)"), {"o": str(org)})


@pytest.mark.db
def test_backfill_rellena_desde_enero_y_es_idempotente(app_engine: Engine, retro_org: dict) -> None:
    org = retro_org["org"]
    insc = retro_org["inscripcion"]

    with Session(app_engine) as db:
        _con_org(db, org)
        creadas = generacion.generar_cuotas_historicas(db, inscripcion_id=insc, hoy=_HOY)
        db.commit()
    assert creadas == 6  # ene..jun (cohorte aniversario del día 11)

    # Re-correr no duplica (idempotente).
    with Session(app_engine) as db:
        _con_org(db, org)
        creadas2 = generacion.generar_cuotas_historicas(db, inscripcion_id=insc, hoy=_HOY)
        db.commit()
    assert creadas2 == 0

    with app_engine.begin() as conn:
        conn.execute(text("SELECT set_config('app.current_org', :o, true)"), {"o": str(org)})
        n = conn.execute(
            text("SELECT count(*) FROM cuota WHERE inscripcion_id = :i"), {"i": str(insc)}
        ).scalar_one()
        montos = (
            conn.execute(
                text("SELECT DISTINCT monto FROM cuota WHERE inscripcion_id = :i"), {"i": str(insc)}
            )
            .scalars()
            .all()
        )
    assert n == 6
    assert montos == [Decimal("60.00")]  # todas al monto de la inscripción


@pytest.mark.db
def test_backfill_no_duplica_cuota_ya_existente(app_engine: Engine, retro_org: dict) -> None:
    """Con una cuota ya existente (p.ej. la corriente), backfill crea solo las que faltan."""
    org = retro_org["org"]
    insc = retro_org["inscripcion"]
    # La cohorte de junio (corriente) ya existe con monto viejo 120.
    with app_engine.begin() as conn:
        conn.execute(text("SELECT set_config('app.current_org', :o, true)"), {"o": str(org)})
        _seed_cuota(
            conn, org=org, insc=insc, inicio=date(2026, 6, 11), vence=date(2026, 7, 11), monto="120"
        )

    with Session(app_engine) as db:
        _con_org(db, org)
        creadas = generacion.generar_cuotas_historicas(db, inscripcion_id=insc, hoy=_HOY)
        db.commit()
    assert creadas == 5  # ene..may (jun ya existía)

    with app_engine.begin() as conn:
        conn.execute(text("SELECT set_config('app.current_org', :o, true)"), {"o": str(org)})
        # La existente conserva su monto viejo (backfill no reescribe).
        monto_jun = conn.execute(
            text("SELECT monto FROM cuota WHERE inscripcion_id = :i AND periodo_inicio = :pi"),
            {"i": str(insc), "pi": date(2026, 6, 11)},
        ).scalar_one()
    assert monto_jun == Decimal("120.00")


@pytest.mark.db
def test_reajuste_solo_toca_futuras_sin_pago(app_engine: Engine, retro_org: dict) -> None:
    org = retro_org["org"]
    insc = retro_org["inscripcion"]
    # 3 cuotas: pasada sin pago, futura sin pago, futura pagada.
    with app_engine.begin() as conn:
        conn.execute(text("SELECT set_config('app.current_org', :o, true)"), {"o": str(org)})
        _seed_cuota(
            conn, org=org, insc=insc, inicio=date(2026, 4, 11), vence=date(2026, 5, 11), monto="60"
        )  # pasada (vence < hoy), sin pago
        _seed_cuota(
            conn, org=org, insc=insc, inicio=date(2026, 7, 11), vence=date(2026, 8, 11), monto="60"
        )  # futura (vence >= hoy), sin pago
        _seed_cuota(
            conn,
            org=org,
            insc=insc,
            inicio=date(2026, 8, 11),
            vence=date(2026, 9, 11),
            monto="60",
            estado="PAGADO",
            monto_pagado="60",
        )  # futura, pagada

    with Session(app_engine) as db:
        _con_org(db, org)
        n = generacion.reajustar_monto_cuotas_futuras(
            db, inscripcion_id=insc, nuevo_monto=Decimal("120"), hoy=_HOY
        )
        db.commit()
    assert n == 1  # solo la futura sin pago

    with app_engine.begin() as conn:
        conn.execute(text("SELECT set_config('app.current_org', :o, true)"), {"o": str(org)})
        rows = conn.execute(
            text("SELECT vence_el, monto FROM cuota WHERE inscripcion_id = :i"), {"i": str(insc)}
        ).all()
    montos = {r.vence_el: r.monto for r in rows}
    assert montos[date(2026, 5, 11)] == Decimal("60.00")  # pasada sin pago: NO se toca
    assert montos[date(2026, 8, 11)] == Decimal("120.00")  # futura sin pago: reajustada
    assert montos[date(2026, 9, 11)] == Decimal("60.00")  # futura pagada: NO se toca
