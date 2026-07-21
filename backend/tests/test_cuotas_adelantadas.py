"""Tests con BD del cobro por adelantado (`generar_cuotas_adelantadas`).

El generador diario corta en el período corriente: la cuota de agosto no existe
hasta que agosto llega, así que una familia al día que quiere pagar meses por
adelantado no tiene nada que seleccionar. Este servicio las proyecta a pedido.

Se cubre lo que puede salir mal:
- proyecta los meses correctos con el motor real (respeta día de corte y monto);
- **"asegurar N", no "agregar N"**: re-llamar no acumula meses de más (deshacerlo
  obligaría a borrar cuota por cuota);
- pedir más meses después solo crea los que faltan;
- un deportista con VARIAS inscripciones (multi-disciplina) las adelanta todas;
- una inscripción dada de baja no genera nada.

Patrón (igual que test_alta_retroactiva): siembra como owner (salta RLS) y
ejercita el servicio en una `Session` sobre `app_engine` (rol `latinosport_app`)
bajo RLS real. Requiere Postgres migrado → `@pytest.mark.db`.
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

# "Hoy" fijo (determinista): inscripción el 7-jul, hoy el 21-jul. El período
# corriente (7-jul..7-ago) ya empezó, así que adelantar debe proyectar 7-ago y
# 7-sep — el caso real que reportó la escuela.
_HOY = date(2026, 7, 21)
_INSCRIPCION = date(2026, 7, 7)


@pytest.fixture()
def adelanto_org(owner_engine: Engine) -> Iterator[dict]:
    """Org ANIVERSARIO con un deportista inscrito el 7-jul-2026 a Bs 80, sin cuotas."""
    org = uuid.uuid4()
    suc = uuid.uuid4()
    dep = uuid.uuid4()
    insc = uuid.uuid4()

    with owner_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO organizacion (id, nombre, pais, moneda, modo_cobro_default, "
                "prorratea_primer_periodo, created_at, updated_at) "
                "VALUES (:id,'Org Adelanto (test)','BO','BOB','ANIVERSARIO',false,now(),now())"
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
                "INSERT INTO deportista (id, org_id, sucursal_id, nombres, activo, "
                "created_at, updated_at) "
                "VALUES (:id,:org,:suc,'Adelanto',true,now(),now())"
            ),
            {"id": str(dep), "org": str(org), "suc": str(suc)},
        )
        conn.execute(
            text(
                "INSERT INTO inscripcion (id, org_id, deportista_id, fecha_inscripcion, "
                "monto_mensual, estado, created_at, updated_at) "
                "VALUES (:id,:org,:d,:f,80.00,'ACTIVA',now(),now())"
            ),
            {"id": str(insc), "org": str(org), "d": str(dep), "f": _INSCRIPCION},
        )

    yield {"org": org, "deportista": dep, "inscripcion": insc, "sucursal": suc}

    with owner_engine.begin() as conn:
        for tabla in ("cuota", "inscripcion", "deportista", "sucursal"):
            conn.execute(text(f"DELETE FROM {tabla} WHERE org_id = :o"), {"o": str(org)})
        conn.execute(text("DELETE FROM organizacion WHERE id = :o"), {"o": str(org)})


def _con_org(db: Session, org: uuid.UUID) -> None:
    db.execute(text("SELECT set_config('app.current_org', :o, true)"), {"o": str(org)})


def _adelantar(app_engine: Engine, org: uuid.UUID, dep: uuid.UUID, meses: int) -> int:
    with Session(app_engine) as db:
        _con_org(db, org)
        creadas = generacion.generar_cuotas_adelantadas(
            db, deportista_id=dep, meses=meses, hoy=_HOY
        )
        db.commit()
    return creadas


def _vencimientos(app_engine: Engine, org: uuid.UUID, insc: uuid.UUID) -> list[date]:
    with app_engine.begin() as conn:
        conn.execute(text("SELECT set_config('app.current_org', :o, true)"), {"o": str(org)})
        return list(
            conn.execute(
                text("SELECT vence_el FROM cuota WHERE inscripcion_id = :i ORDER BY vence_el"),
                {"i": str(insc)},
            )
            .scalars()
            .all()
        )


@pytest.mark.db
def test_adelantar_proyecta_los_meses_siguientes(
    app_engine: Engine, adelanto_org: dict
) -> None:
    """Adelantar 2 deja disponibles agosto y septiembre (además del corriente)."""
    org, dep, insc = adelanto_org["org"], adelanto_org["deportista"], adelanto_org["inscripcion"]
    _adelantar(app_engine, org, dep, 2)

    assert _vencimientos(app_engine, org, insc) == [
        date(2026, 7, 7),  # período corriente (lo completa la cadena)
        date(2026, 8, 7),
        date(2026, 9, 7),
    ]


@pytest.mark.db
def test_adelantar_respeta_el_monto_de_la_inscripcion(
    app_engine: Engine, adelanto_org: dict
) -> None:
    """Las cuotas adelantadas salen al monto vigente, no a uno inventado."""
    org, dep, insc = adelanto_org["org"], adelanto_org["deportista"], adelanto_org["inscripcion"]
    _adelantar(app_engine, org, dep, 2)
    with app_engine.begin() as conn:
        conn.execute(text("SELECT set_config('app.current_org', :o, true)"), {"o": str(org)})
        montos = (
            conn.execute(
                text("SELECT DISTINCT monto FROM cuota WHERE inscripcion_id = :i"),
                {"i": str(insc)},
            )
            .scalars()
            .all()
        )
    assert montos == [Decimal("80.00")]


@pytest.mark.db
def test_adelantar_dos_veces_no_acumula_meses(app_engine: Engine, adelanto_org: dict) -> None:
    """"Asegurar N", no "agregar N": el doble clic no deja 4 meses generados."""
    org, dep, insc = adelanto_org["org"], adelanto_org["deportista"], adelanto_org["inscripcion"]
    _adelantar(app_engine, org, dep, 2)
    creadas2 = _adelantar(app_engine, org, dep, 2)

    assert creadas2 == 0
    assert _vencimientos(app_engine, org, insc) == [
        date(2026, 7, 7),
        date(2026, 8, 7),
        date(2026, 9, 7),
    ]


@pytest.mark.db
def test_pedir_mas_meses_crea_solo_los_que_faltan(
    app_engine: Engine, adelanto_org: dict
) -> None:
    """De 2 a 3 meses: crea uno solo (octubre), no tres más."""
    org, dep, insc = adelanto_org["org"], adelanto_org["deportista"], adelanto_org["inscripcion"]
    _adelantar(app_engine, org, dep, 2)
    creadas = _adelantar(app_engine, org, dep, 3)

    assert creadas == 1
    assert _vencimientos(app_engine, org, insc)[-1] == date(2026, 10, 7)


@pytest.mark.db
def test_adelanta_todas_las_inscripciones_activas(
    app_engine: Engine, owner_engine: Engine, adelanto_org: dict
) -> None:
    """Multi-disciplina: debe las dos, así que se adelantan las dos."""
    org, dep = adelanto_org["org"], adelanto_org["deportista"]
    insc2 = uuid.uuid4()
    with owner_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO inscripcion (id, org_id, deportista_id, fecha_inscripcion, "
                "monto_mensual, estado, created_at, updated_at) "
                "VALUES (:id,:org,:d,:f,50.00,'ACTIVA',now(),now())"
            ),
            {"id": str(insc2), "org": str(org), "d": str(dep), "f": _INSCRIPCION},
        )

    _adelantar(app_engine, org, dep, 2)

    assert _vencimientos(app_engine, org, adelanto_org["inscripcion"]) == [
        date(2026, 7, 7),
        date(2026, 8, 7),
        date(2026, 9, 7),
    ]
    assert _vencimientos(app_engine, org, insc2) == [
        date(2026, 7, 7),
        date(2026, 8, 7),
        date(2026, 9, 7),
    ]


@pytest.mark.db
def test_inscripcion_dada_de_baja_no_genera(
    app_engine: Engine, owner_engine: Engine, adelanto_org: dict
) -> None:
    """A un alumno dado de baja no se le proyectan cuotas futuras."""
    org, dep, insc = adelanto_org["org"], adelanto_org["deportista"], adelanto_org["inscripcion"]
    with owner_engine.begin() as conn:
        conn.execute(
            text("UPDATE inscripcion SET estado = 'INACTIVA' WHERE id = :i"),
            {"i": str(insc)},
        )

    assert _adelantar(app_engine, org, dep, 2) == 0
    assert _vencimientos(app_engine, org, insc) == []


@pytest.mark.db
def test_tope_de_meses(app_engine: Engine, adelanto_org: dict) -> None:
    """Pedir más del tope se recorta a MAX_MESES_ADELANTO (no genera años)."""
    org, dep, insc = adelanto_org["org"], adelanto_org["deportista"], adelanto_org["inscripcion"]
    _adelantar(app_engine, org, dep, 999)
    # 1 del período corriente + el tope de meses adelantados.
    assert len(_vencimientos(app_engine, org, insc)) == 1 + generacion.MAX_MESES_ADELANTO
