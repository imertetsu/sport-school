"""Motor de cuotas — dominio PURO sin I/O (contrato C2, SRS §7).

Funciones puras + dataclasses. NO importa SQLAlchemy, FastAPI ni adaptadores
(import-linter lo verifica). El servicio de aplicación (con I/O) traduce filas de
BD a/desde estas estructuras.

Reglas exactas (C2):
- `resolver_modo`: `inscripcion.modo_cobro or org.modo_cobro_default` (FIJO|ANIVERSARIO).
- `add_months(d, n)`: mismo día del mes; si el día no existe (29/30/31) → último
  día del mes resultante. **Nunca** `+30 días` (usa relativedelta).
- ANIVERSARIO: corte = día de inscripción; primer período completo.
- FIJO: corte = `org.dia_corte_fijo`; primer período prorrateable.
- Generación incremental: existe la "cuota corriente" (la última); se genera la
  siguiente cuando su `vence_el` ya pasó (o la primera al crear la inscripción).
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from dateutil.relativedelta import relativedelta

MODO_FIJO = "FIJO"
MODO_ANIVERSARIO = "ANIVERSARIO"


# --------------------------------------------------------------------------- #
# Estructuras puras
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class OrgConfig:
    """Configuración de cobranza de la organización (C2)."""

    modo_cobro_default: str
    dia_corte_fijo: int | None = None
    prorratea_primer_periodo: bool = True


@dataclass(frozen=True)
class InscripcionConfig:
    """Datos de la inscripción relevantes para el motor (C2)."""

    fecha_inscripcion: date
    monto_mensual: Decimal
    # null -> hereda org.modo_cobro_default
    modo_cobro: str | None = None
    # FIJO: día de corte por inscripción (override del de la org), opcional
    dia_corte: int | None = None


@dataclass(frozen=True)
class PeriodoCuota:
    """Una cuota proyectada por el motor (sin persistir)."""

    periodo_inicio: date
    periodo_fin: date
    vence_el: date
    monto: Decimal
    es_prorrateo: bool


# --------------------------------------------------------------------------- #
# Aritmética de fechas
# --------------------------------------------------------------------------- #
def dias_del_mes(d: date) -> int:
    """Días del mes de `d` (28/29/30/31)."""
    return calendar.monthrange(d.year, d.month)[1]


def add_months(d: date, n: int) -> date:
    """Suma `n` meses a `d` manteniendo el mismo día del mes.

    Si el día no existe en el mes resultante (p.ej. 31-ene + 1 mes → feb) se
    *clampa* al último día de ese mes. `relativedelta` ya implementa este clamp;
    lo dejamos explícito y testeado. NUNCA `+30 días`.
    """
    return d + relativedelta(months=n)


def _dia_corte_en_mes(anio: int, mes: int, dia_corte: int) -> date:
    """Construye la fecha de corte `dia_corte` en (anio, mes), clampando al último
    día del mes si `dia_corte` no existe (p.ej. 31 en febrero)."""
    ultimo = calendar.monthrange(anio, mes)[1]
    return date(anio, mes, min(dia_corte, ultimo))


def proximo_corte_fijo(desde: date, dia_corte: int) -> date:
    """Primer día `dia_corte` en o después de `desde` (clamp al último día del mes).

    Si `desde` cae exactamente en el corte, devuelve `desde` (corte inmediato del
    mismo mes); si ya pasó, salta al corte del mes siguiente.
    """
    corte_este_mes = _dia_corte_en_mes(desde.year, desde.month, dia_corte)
    if corte_este_mes >= desde:
        return corte_este_mes
    siguiente = desde + relativedelta(months=1)
    return _dia_corte_en_mes(siguiente.year, siguiente.month, dia_corte)


def _round2(value: Decimal) -> Decimal:
    """Redondeo a 2 decimales, HALF_UP (consistente con dinero)."""
    return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# --------------------------------------------------------------------------- #
# Resolución de modo (herencia org ↔ inscripción)
# --------------------------------------------------------------------------- #
def resolver_modo(insc: InscripcionConfig, org: OrgConfig) -> str:
    """`inscripcion.modo_cobro or org.modo_cobro_default` (C2)."""
    return insc.modo_cobro or org.modo_cobro_default


def _dia_corte_efectivo(insc: InscripcionConfig, org: OrgConfig) -> int:
    """Día de corte para modo FIJO: inscripción > org.

    Si ninguno está definido, cae al día de la fecha de inscripción (degradación
    sensata para no romper la generación).
    """
    if insc.dia_corte is not None:
        return insc.dia_corte
    if org.dia_corte_fijo is not None:
        return org.dia_corte_fijo
    return insc.fecha_inscripcion.day


# --------------------------------------------------------------------------- #
# Generación de cuotas (C2)
# --------------------------------------------------------------------------- #
def primera_cuota(insc: InscripcionConfig, org: OrgConfig) -> PeriodoCuota:
    """Proyecta la PRIMERA cuota (k=1) de la inscripción según el modo."""
    modo = resolver_modo(insc, org)
    if modo == MODO_ANIVERSARIO:
        return _cuota_aniversario(insc, k=1)
    return _primera_cuota_fijo(insc, org)


def siguiente_cuota(
    insc: InscripcionConfig,
    org: OrgConfig,
    *,
    ultimo_periodo_inicio: date,
    ultimo_vence_el: date,
) -> PeriodoCuota:
    """Proyecta la cuota que sigue a la última existente (corte corriente).

    `ultimo_periodo_inicio` / `ultimo_vence_el` son de la cuota más reciente.
    """
    modo = resolver_modo(insc, org)
    if modo == MODO_ANIVERSARIO:
        # k de la última: periodo_inicio = add_months(fecha_insc, k-1).
        k = _k_aniversario(insc.fecha_inscripcion, ultimo_periodo_inicio)
        return _cuota_aniversario(insc, k=k + 1)
    # FIJO: el corte previo es el vence_el de la última; el período va de ese
    # corte al corte + 1 mes.
    corte_previo = ultimo_vence_el
    vence = add_months(corte_previo, 1)
    return PeriodoCuota(
        periodo_inicio=corte_previo,
        periodo_fin=vence,
        vence_el=vence,
        monto=_round2(insc.monto_mensual),
        es_prorrateo=False,
    )


# --- ANIVERSARIO ---------------------------------------------------------- #
def _cuota_aniversario(insc: InscripcionConfig, *, k: int) -> PeriodoCuota:
    """Cuota k (k≥1) en modo ANIVERSARIO — pago ADELANTADO (primer período completo).

    Cada mes se cobra al INICIO de su período (el día aniversario de la inscripción),
    de modo que el primer mes vence el MISMO día de la inscripción. Por eso
    `vence_el = inicio` (no el fin del período). `periodo_fin` sigue siendo el fin real
    del período (usado por el motor de generación para contar cuántas cuotas van).
    """
    inicio = add_months(insc.fecha_inscripcion, k - 1)
    fin = add_months(insc.fecha_inscripcion, k)
    return PeriodoCuota(
        periodo_inicio=inicio,
        periodo_fin=fin,
        vence_el=inicio,
        monto=_round2(insc.monto_mensual),
        es_prorrateo=False,
    )


def _k_aniversario(fecha_inscripcion: date, periodo_inicio: date) -> int:
    """Deduce k (1-based) a partir del `periodo_inicio` de una cuota ANIVERSARIO.

    `periodo_inicio = add_months(fecha_inscripcion, k-1)` ⇒ k = meses + 1.
    """
    rd = relativedelta(periodo_inicio, fecha_inscripcion)
    meses = rd.years * 12 + rd.months
    return meses + 1


# --- FIJO ----------------------------------------------------------------- #
def _primera_cuota_fijo(insc: InscripcionConfig, org: OrgConfig) -> PeriodoCuota:
    """Primer período en modo FIJO (prorrateable según `prorratea_primer_periodo`)."""
    dia_corte = _dia_corte_efectivo(insc, org)
    primer_corte = proximo_corte_fijo(insc.fecha_inscripcion, dia_corte)
    inicio = insc.fecha_inscripcion

    if org.prorratea_primer_periodo and primer_corte > inicio:
        dias_periodo = (primer_corte - inicio).days
        base = dias_del_mes(primer_corte)
        monto = _round2(insc.monto_mensual * Decimal(dias_periodo) / Decimal(base))
        return PeriodoCuota(
            periodo_inicio=inicio,
            periodo_fin=primer_corte,
            vence_el=primer_corte,
            monto=monto,
            es_prorrateo=True,
        )

    # Sin prorrateo: primer mes completo.
    return PeriodoCuota(
        periodo_inicio=inicio,
        periodo_fin=primer_corte,
        vence_el=primer_corte,
        monto=_round2(insc.monto_mensual),
        es_prorrateo=False,
    )
