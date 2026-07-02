"""Tests de la secuencia de períodos para el alta retroactiva (`_periodos_hasta_corriente`).

PUROS (sin BD): validan que un alumno inscrito en el pasado produce una cuota por mes
desde su `fecha_inscripcion` hasta el período corriente. La parte de persistencia /
idempotencia / reajuste de monto se cubre con los tests `@pytest.mark.db`.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.domain.cobranza.cuota_engine import InscripcionConfig, OrgConfig
from app.services.generacion import _periodos_hasta_corriente

_ORG_ANIVERSARIO = OrgConfig(modo_cobro_default="ANIVERSARIO", prorratea_primer_periodo=False)


def _insc(fecha: date, monto: str = "60") -> InscripcionConfig:
    return InscripcionConfig(fecha_inscripcion=fecha, monto_mensual=Decimal(monto))


def test_inscrito_en_enero_genera_una_cuota_por_mes_hasta_hoy() -> None:
    # Inscrito el 11-ene-2026; "hoy" = 2-jul-2026. Cohortes aniversario: 11 de cada mes.
    periodos = _periodos_hasta_corriente(
        _insc(date(2026, 1, 11)), _ORG_ANIVERSARIO, hoy=date(2026, 7, 2)
    )
    inicios = [p.periodo_inicio for p in periodos]
    assert inicios == [
        date(2026, 1, 11),
        date(2026, 2, 11),
        date(2026, 3, 11),
        date(2026, 4, 11),
        date(2026, 5, 11),
        date(2026, 6, 11),
    ]
    # La corriente (última) vence en el futuro; el resto ya venció.
    assert periodos[-1].vence_el == date(2026, 7, 11)
    assert all(p.vence_el <= date(2026, 7, 2) for p in periodos[:-1])


def test_todas_las_cuotas_llevan_el_monto_de_la_inscripcion() -> None:
    periodos = _periodos_hasta_corriente(
        _insc(date(2026, 1, 11), monto="60"), _ORG_ANIVERSARIO, hoy=date(2026, 7, 2)
    )
    assert all(p.monto == Decimal("60.00") for p in periodos)


def test_inscrito_este_mes_solo_genera_la_cuota_corriente() -> None:
    # Inscrito hoy: solo la primera cuota (vence el mes que viene, en el futuro).
    periodos = _periodos_hasta_corriente(
        _insc(date(2026, 7, 2)), _ORG_ANIVERSARIO, hoy=date(2026, 7, 2)
    )
    assert len(periodos) == 1
    assert periodos[0].periodo_inicio == date(2026, 7, 2)


def test_no_genera_periodos_futuros_de_mas() -> None:
    # La última cuota es la corriente; no debe adelantarse a agosto.
    periodos = _periodos_hasta_corriente(
        _insc(date(2026, 1, 11)), _ORG_ANIVERSARIO, hoy=date(2026, 7, 2)
    )
    assert all(p.periodo_inicio <= date(2026, 7, 2) for p in periodos)
