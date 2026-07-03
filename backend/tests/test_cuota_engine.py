"""Tests del motor de cuotas (C2) — PUROS, sin BD.

Casos borde requeridos por los criterios de aceptación:
- ANIVERSARIO: inscrito 31-ene -> feb 28/29; meses sucesivos con clamp.
- FIJO con y sin prorrateo.
- Herencia de modo org ↔ inscripción.
- add_months nunca hace +30 días (clamp a último día del mes).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.domain.cobranza.cuota_engine import (
    MODO_ANIVERSARIO,
    MODO_FIJO,
    InscripcionConfig,
    OrgConfig,
    add_months,
    primera_cuota,
    proximo_corte_fijo,
    resolver_modo,
    siguiente_cuota,
)


# --------------------------------------------------------------------------- #
# add_months: clamp 29/30/31 (nunca +30 días)
# --------------------------------------------------------------------------- #
def test_add_months_clamp_31_enero_no_existe_en_febrero():
    # 31-ene + 1 mes -> 28-feb (año no bisiesto).
    assert add_months(date(2025, 1, 31), 1) == date(2025, 2, 28)


def test_add_months_clamp_31_enero_febrero_bisiesto():
    assert add_months(date(2024, 1, 31), 1) == date(2024, 2, 29)


def test_add_months_mismo_dia_normal():
    assert add_months(date(2025, 3, 15), 1) == date(2025, 4, 15)


def test_add_months_31_a_abril_clamp_30():
    # 31-mar + 1 mes -> 30-abr (abril tiene 30).
    assert add_months(date(2025, 3, 31), 1) == date(2025, 4, 30)


def test_add_months_no_es_mas_30_dias():
    # +30 días de 31-ene sería 02-mar; el motor debe dar 28-feb.
    assert add_months(date(2025, 1, 31), 1) != date(2025, 1, 31) + __import_timedelta(30)


def __import_timedelta(n):
    from datetime import timedelta

    return timedelta(days=n)


# --------------------------------------------------------------------------- #
# proximo_corte_fijo
# --------------------------------------------------------------------------- #
def test_proximo_corte_dia_existe_mismo_mes():
    # desde 10-mar, corte día 15 -> 15-mar.
    assert proximo_corte_fijo(date(2025, 3, 10), 15) == date(2025, 3, 15)


def test_proximo_corte_dia_ya_paso_salta_mes():
    # desde 20-mar, corte día 15 -> 15-abr.
    assert proximo_corte_fijo(date(2025, 3, 20), 15) == date(2025, 4, 15)


def test_proximo_corte_dia_no_existe_clamp_febrero():
    # desde 05-feb, corte día 31 -> 28-feb (clamp).
    assert proximo_corte_fijo(date(2025, 2, 5), 31) == date(2025, 2, 28)


def test_proximo_corte_exacto_devuelve_mismo_dia():
    assert proximo_corte_fijo(date(2025, 3, 15), 15) == date(2025, 3, 15)


# --------------------------------------------------------------------------- #
# Herencia de modo
# --------------------------------------------------------------------------- #
def test_herencia_modo_usa_org_si_inscripcion_null():
    org = OrgConfig(modo_cobro_default=MODO_FIJO, dia_corte_fijo=1)
    insc = InscripcionConfig(
        fecha_inscripcion=date(2025, 1, 10), monto_mensual=Decimal("250"), modo_cobro=None
    )
    assert resolver_modo(insc, org) == MODO_FIJO


def test_herencia_modo_inscripcion_override_org():
    org = OrgConfig(modo_cobro_default=MODO_FIJO, dia_corte_fijo=1)
    insc = InscripcionConfig(
        fecha_inscripcion=date(2025, 1, 10),
        monto_mensual=Decimal("250"),
        modo_cobro=MODO_ANIVERSARIO,
    )
    assert resolver_modo(insc, org) == MODO_ANIVERSARIO


# --------------------------------------------------------------------------- #
# ANIVERSARIO
# --------------------------------------------------------------------------- #
def test_aniversario_31_enero_primera_cuota():
    org = OrgConfig(modo_cobro_default=MODO_ANIVERSARIO)
    insc = InscripcionConfig(fecha_inscripcion=date(2025, 1, 31), monto_mensual=Decimal("300.00"))
    c = primera_cuota(insc, org)
    assert c.periodo_inicio == date(2025, 1, 31)
    assert c.vence_el == date(2025, 1, 31)  # pago adelantado: vence al INICIO del período
    assert c.periodo_fin == date(2025, 2, 28)  # fin real (clamp)
    assert c.monto == Decimal("300.00")
    assert c.es_prorrateo is False


def test_aniversario_meses_sucesivos_con_clamp():
    org = OrgConfig(modo_cobro_default=MODO_ANIVERSARIO)
    insc = InscripcionConfig(fecha_inscripcion=date(2025, 1, 31), monto_mensual=Decimal("300.00"))
    c1 = primera_cuota(insc, org)
    # Siguiente: k=2 -> inicio=28-feb; pago adelantado -> vence al INICIO (28-feb).
    c2 = siguiente_cuota(
        insc, org, ultimo_periodo_inicio=c1.periodo_inicio, ultimo_vence_el=c1.vence_el
    )
    assert c2.periodo_inicio == date(2025, 2, 28)
    assert c2.vence_el == date(2025, 2, 28)
    assert c2.es_prorrateo is False
    # Tercera: k=3 -> inicio=31-mar; vence al INICIO (31-mar).
    c3 = siguiente_cuota(
        insc, org, ultimo_periodo_inicio=c2.periodo_inicio, ultimo_vence_el=c2.vence_el
    )
    assert c3.periodo_inicio == date(2025, 3, 31)
    assert c3.vence_el == date(2025, 3, 31)


def test_aniversario_dia_normal():
    org = OrgConfig(modo_cobro_default=MODO_ANIVERSARIO)
    insc = InscripcionConfig(fecha_inscripcion=date(2025, 3, 15), monto_mensual=Decimal("250"))
    c = primera_cuota(insc, org)
    assert c.periodo_inicio == date(2025, 3, 15)
    assert c.vence_el == date(2025, 3, 15)  # pago adelantado: vence al inicio


# --------------------------------------------------------------------------- #
# FIJO con prorrateo
# --------------------------------------------------------------------------- #
def test_fijo_con_prorrateo_primer_periodo():
    # Inscrito 16-mar, corte día 1 -> primer corte 01-abr. Prorrateo:
    # días(16-mar -> 01-abr) = 16; abril tiene 30 días.
    # monto = round(300 * 16/30, 2) = round(160.00..., 2) = 160.00
    org = OrgConfig(modo_cobro_default=MODO_FIJO, dia_corte_fijo=1, prorratea_primer_periodo=True)
    insc = InscripcionConfig(fecha_inscripcion=date(2025, 3, 16), monto_mensual=Decimal("300.00"))
    c = primera_cuota(insc, org)
    assert c.periodo_inicio == date(2025, 3, 16)
    assert c.vence_el == date(2025, 4, 1)
    assert c.es_prorrateo is True
    assert c.monto == Decimal("160.00")


def test_fijo_con_prorrateo_calculo_dias():
    # Inscrito 11-may, corte día 1 -> primer corte 01-jun. días = 21; junio 30 días.
    # monto = round(300 * 21/30,2) = 210.00
    org = OrgConfig(modo_cobro_default=MODO_FIJO, dia_corte_fijo=1, prorratea_primer_periodo=True)
    insc = InscripcionConfig(fecha_inscripcion=date(2025, 5, 11), monto_mensual=Decimal("300.00"))
    c = primera_cuota(insc, org)
    assert c.vence_el == date(2025, 6, 1)
    assert c.monto == Decimal("210.00")
    assert c.es_prorrateo is True


# --------------------------------------------------------------------------- #
# FIJO sin prorrateo
# --------------------------------------------------------------------------- #
def test_fijo_sin_prorrateo_primer_mes_completo():
    org = OrgConfig(modo_cobro_default=MODO_FIJO, dia_corte_fijo=1, prorratea_primer_periodo=False)
    insc = InscripcionConfig(fecha_inscripcion=date(2025, 3, 16), monto_mensual=Decimal("300.00"))
    c = primera_cuota(insc, org)
    assert c.periodo_inicio == date(2025, 3, 16)
    assert c.vence_el == date(2025, 4, 1)
    assert c.es_prorrateo is False
    assert c.monto == Decimal("300.00")  # mes completo


def test_fijo_siguiente_periodo_corte_a_corte():
    org = OrgConfig(modo_cobro_default=MODO_FIJO, dia_corte_fijo=1, prorratea_primer_periodo=True)
    insc = InscripcionConfig(fecha_inscripcion=date(2025, 3, 16), monto_mensual=Decimal("300.00"))
    c1 = primera_cuota(insc, org)  # vence 01-abr
    c2 = siguiente_cuota(
        insc, org, ultimo_periodo_inicio=c1.periodo_inicio, ultimo_vence_el=c1.vence_el
    )
    # período siguiente: de 01-abr a 01-may, mes completo.
    assert c2.periodo_inicio == date(2025, 4, 1)
    assert c2.vence_el == date(2025, 5, 1)
    assert c2.monto == Decimal("300.00")
    assert c2.es_prorrateo is False


def test_fijo_corte_dia_31_clamp_en_febrero():
    # corte día 31, inscrito 05-feb -> primer corte 28-feb (clamp).
    org = OrgConfig(modo_cobro_default=MODO_FIJO, dia_corte_fijo=31, prorratea_primer_periodo=False)
    insc = InscripcionConfig(fecha_inscripcion=date(2025, 2, 5), monto_mensual=Decimal("300.00"))
    c = primera_cuota(insc, org)
    assert c.vence_el == date(2025, 2, 28)


def test_fijo_dia_corte_inscripcion_override_org():
    # La inscripción define dia_corte=10 (override de org dia_corte_fijo=1).
    org = OrgConfig(modo_cobro_default=MODO_FIJO, dia_corte_fijo=1, prorratea_primer_periodo=False)
    insc = InscripcionConfig(
        fecha_inscripcion=date(2025, 3, 5),
        monto_mensual=Decimal("300.00"),
        dia_corte=10,
    )
    c = primera_cuota(insc, org)
    assert c.vence_el == date(2025, 3, 10)
