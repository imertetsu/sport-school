"""Servicio de Reportes (C1) — agregación de **solo lectura** sobre tablas ya
existentes (Cobranza/Asistencia). **No** crea modelos ni migración.

Corre SIEMPRE con `app.current_org` ya fijado por el llamador (RLS es la barrera
real; no se salta el contexto).

Reglas de negocio:
- **Ingresos por mes** (RF-COM-02): suma de `pago.monto` con `estado='CONFIRMADO'`
  agrupada por mes de `pagado_en` del año dado. Se cuenta el `pago` (no las
  cuotas vía `pago_cuota`) para **no doblar** cuando un pago cubre varias cuotas.
  Devuelve siempre los **12 meses** (monto "0.00" si vacío) + total del año.
- **Asistencia global** (RF-COM-03): `asistencia` JOIN `sesion` JOIN `categoria`
  JOIN `sucursal`, filtrado por `sesion.fecha ∈ [desde, hasta]` (+ sucursal /
  categoría opcionales). Calcula presentes/ausentes/total_marcas, sesiones
  distintas y `pct_presente = round(presentes/total_marcas*100, 1)` (0 si total
  = 0), global y desglosado por categoría.

Los montos se devuelven como **string** con 2 decimales (C1).
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import Integer, and_, cast, func, select
from sqlalchemy.orm import Session

from app.models.asistencia import Asistencia
from app.models.categoria import Categoria
from app.models.pago import Pago
from app.models.sesion import Sesion
from app.models.sucursal import Sucursal
from app.schemas.reportes import (
    AsistenciaGlobal,
    AsistenciaPorCategoria,
    AsistenciaReporte,
    CategoriaRefReporte,
    IngresosMesItem,
    IngresosReporte,
    SucursalRefReporte,
)

# Etiquetas de mes (abreviadas, español, minúscula) para el eje del gráfico.
ETIQUETAS_MES: tuple[str, ...] = (
    "ene",
    "feb",
    "mar",
    "abr",
    "may",
    "jun",
    "jul",
    "ago",
    "sep",
    "oct",
    "nov",
    "dic",
)

_DOS_DECIMALES = Decimal("0.01")


def _money_str(valor: Decimal) -> str:
    """Formatea un Decimal a string con 2 decimales (HALF_UP), p. ej. "0.00"."""
    return str(valor.quantize(_DOS_DECIMALES, rounding=ROUND_HALF_UP))


def pct_presente(presentes: int, total_marcas: int) -> float:
    """`round(presentes/total_marcas*100, 1)`; 0.0 si `total_marcas == 0`.

    Lógica pura (sin I/O), fácil de testear.
    """
    if total_marcas <= 0:
        return 0.0
    return round(presentes / total_marcas * 100, 1)


def armar_meses(
    anio: int, datos: dict[int, tuple[Decimal, int]]
) -> tuple[list[IngresosMesItem], Decimal, int]:
    """Arma los **12 meses** del reporte a partir de los agregados por mes.

    `datos` mapea `mes (1..12) -> (monto_sum, n_pagos)`; los meses ausentes se
    rellenan con `0.00` / `0`. Devuelve `(meses, total, n_pagos_total)`.

    Lógica pura (sin I/O) para poder testear el relleno de 12 meses sin BD.
    """
    meses: list[IngresosMesItem] = []
    total = Decimal("0")
    n_pagos_total = 0
    for mes in range(1, 13):
        monto, n = datos.get(mes, (Decimal("0"), 0))
        total += monto
        n_pagos_total += n
        meses.append(
            IngresosMesItem(
                mes=mes,
                etiqueta=ETIQUETAS_MES[mes - 1],
                monto=_money_str(monto),
                n_pagos=n,
            )
        )
    return meses, total, n_pagos_total


# --------------------------------------------------------------------------- #
# Ingresos por mes (RF-COM-02)
# --------------------------------------------------------------------------- #
def ingresos_por_mes(db: Session, *, anio: int) -> IngresosReporte:
    """Ingresos confirmados agrupados por mes de `pagado_en` del `anio` (C1).

    Cuenta el `pago` CONFIRMADO (no las cuotas) para no doblar montos cuando un
    pago cubre varias cuotas. Devuelve siempre 12 meses + total del año.
    """
    desde = datetime(anio, 1, 1, tzinfo=UTC)
    hasta = datetime(anio + 1, 1, 1, tzinfo=UTC)

    mes_expr = cast(func.extract("month", Pago.pagado_en), Integer)
    rows = db.execute(
        select(
            mes_expr.label("mes"),
            func.coalesce(func.sum(Pago.monto), 0),
            func.count(),
        )
        .where(
            Pago.estado == "CONFIRMADO",
            Pago.pagado_en.is_not(None),
            Pago.pagado_en >= desde,
            Pago.pagado_en < hasta,
        )
        .group_by(mes_expr)
    ).all()

    datos: dict[int, tuple[Decimal, int]] = {
        int(mes): (Decimal(str(monto)), int(n)) for (mes, monto, n) in rows
    }
    meses, total, n_pagos = armar_meses(anio, datos)

    return IngresosReporte(
        anio=anio,
        total=_money_str(total),
        n_pagos=n_pagos,
        meses=meses,
    )


# --------------------------------------------------------------------------- #
# Asistencia global (RF-COM-03)
# --------------------------------------------------------------------------- #
def asistencia_reporte(
    db: Session,
    *,
    desde: date,
    hasta: date,
    sucursal_id: uuid.UUID | None = None,
    categoria_id: uuid.UUID | None = None,
) -> AsistenciaReporte:
    """Asistencia global + por categoría en `[desde, hasta]` (C1).

    `asistencia` JOIN `sesion` JOIN `categoria` JOIN `sucursal`, filtrado por
    `sesion.fecha` en el rango (inclusive) + sucursal/categoría opcionales.
    `pct_presente = round(presentes/total_marcas*100, 1)` (0 si total = 0).
    """
    filtros = [Sesion.fecha >= desde, Sesion.fecha <= hasta]
    if sucursal_id is not None:
        filtros.append(Categoria.sucursal_id == sucursal_id)
    if categoria_id is not None:
        filtros.append(Categoria.id == categoria_id)
    where = and_(*filtros)

    presentes_expr = func.count().filter(Asistencia.estado == "PRESENTE")
    ausentes_expr = func.count().filter(Asistencia.estado == "AUSENTE")
    total_expr = func.count()
    sesiones_expr = func.count(func.distinct(Sesion.id))

    base = (
        select(Asistencia)
        .join(Sesion, Sesion.id == Asistencia.sesion_id)
        .join(Categoria, Categoria.id == Sesion.categoria_id)
        .join(Sucursal, Sucursal.id == Categoria.sucursal_id)
        .where(where)
    )

    # Totales globales.
    g_row = db.execute(
        base.with_only_columns(
            sesiones_expr,
            presentes_expr,
            ausentes_expr,
            total_expr,
        )
    ).one()
    g_sesiones, g_presentes, g_ausentes, g_total = (
        int(g_row[0]),
        int(g_row[1]),
        int(g_row[2]),
        int(g_row[3]),
    )
    global_ = AsistenciaGlobal(
        sesiones=g_sesiones,
        presentes=g_presentes,
        ausentes=g_ausentes,
        total_marcas=g_total,
        pct_presente=pct_presente(g_presentes, g_total),
    )

    # Desglose por categoría (con su sucursal).
    cat_rows = db.execute(
        base.with_only_columns(
            Categoria.id,
            Categoria.nombre,
            Sucursal.nombre,
            sesiones_expr,
            presentes_expr,
            ausentes_expr,
            total_expr,
        )
        .group_by(Categoria.id, Categoria.nombre, Sucursal.nombre)
        .order_by(Sucursal.nombre, Categoria.nombre)
    ).all()

    por_categoria = [
        AsistenciaPorCategoria(
            categoria=CategoriaRefReporte(id=cat_id, nombre=cat_nombre),
            sucursal=SucursalRefReporte(nombre=suc_nombre),
            sesiones=int(sesiones),
            presentes=int(presentes),
            ausentes=int(ausentes),
            total_marcas=int(total_marcas),
            pct_presente=pct_presente(int(presentes), int(total_marcas)),
        )
        for (
            cat_id,
            cat_nombre,
            suc_nombre,
            sesiones,
            presentes,
            ausentes,
            total_marcas,
        ) in cat_rows
    ]

    return AsistenciaReporte(
        desde=desde.isoformat(),
        hasta=hasta.isoformat(),
        global_=global_,
        por_categoria=por_categoria,
    )
