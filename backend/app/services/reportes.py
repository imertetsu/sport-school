"""Servicio de Reportes (C1) — agregación de **solo lectura** sobre tablas ya
existentes (Cobranza/Asistencia). **No** crea modelos ni migración.

Corre SIEMPRE con `app.current_org` ya fijado por el llamador (RLS es la barrera
real; no se salta el contexto).

Reglas de negocio:
- **Ingresos por mes** (RF-COM-02): suma de `pago.monto` con `estado='CONFIRMADO'`
  agrupada por mes de `pagado_en` del año dado. Se cuenta el `pago` (no las
  cuotas vía `pago_cuota`) para **no doblar** cuando un pago cubre varias cuotas.
  Devuelve siempre los **12 meses** (monto "0.00" si vacío) + total del año.
- **Egresos y utilidad** (mismo endpoint): suma de `egreso.monto` agrupada por mes
  de `egreso.fecha` (la fecha del gasto, no `created_at`), y `utilidad = ingresos
  - egresos` mes a mes y en el total anual. Puede ser **negativa**.
- **Filtro por sucursal** (opcional, ambas series): los ingresos se acotan a los
  pagos cuyas cuotas son de deportistas de esa sucursal (pago → pago_cuota →
  cuota → inscripción → deportista) y los egresos a `egreso.sucursal_id`. Los
  egresos a nivel organización (`sucursal_id` NULL) quedan **fuera** al filtrar:
  no son atribuibles a una sucursal y repartirlos sería inventar un criterio.
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
from typing import NamedTuple

from sqlalchemy import Integer, and_, cast, func, select
from sqlalchemy.orm import Session

from app.models.asistencia import Asistencia
from app.models.categoria import Categoria
from app.models.cuota import Cuota
from app.models.deportista import Deportista
from app.models.egreso import Egreso
from app.models.inscripcion import Inscripcion
from app.models.pago import Pago
from app.models.pago_cuota import PagoCuota
from app.models.sesion import Sesion
from app.models.sucursal import Sucursal
from app.schemas.reportes import (
    AsistenciaGlobal,
    AsistenciaPorCategoria,
    AsistenciaPorDeportista,
    AsistenciaReporte,
    CategoriaRefReporte,
    DeportistaRefReporte,
    IngresosMesItem,
    IngresosReporte,
    MarcaAsistencia,
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


class ResumenAnual(NamedTuple):
    """Los 12 meses armados + los totales del año (ingresos, egresos, conteos)."""

    meses: list[IngresosMesItem]
    total_ingresos: Decimal
    n_pagos: int
    total_egresos: Decimal
    n_egresos: int


def armar_meses(
    anio: int,
    datos: dict[int, tuple[Decimal, int]],
    egresos: dict[int, tuple[Decimal, int]] | None = None,
) -> ResumenAnual:
    """Arma los **12 meses** del reporte a partir de los agregados por mes.

    `datos` y `egresos` mapean `mes (1..12) -> (monto_sum, n_filas)`; los meses
    ausentes se rellenan con `0.00` / `0`. La utilidad de cada mes es
    `ingresos - egresos` y puede ser negativa (mes en pérdida).

    Lógica pura (sin I/O) para poder testear el relleno de 12 meses sin BD.
    """
    egresos = egresos or {}
    meses: list[IngresosMesItem] = []
    total = Decimal("0")
    n_pagos_total = 0
    total_egr = Decimal("0")
    n_egresos_total = 0
    for mes in range(1, 13):
        monto, n = datos.get(mes, (Decimal("0"), 0))
        egr, n_egr = egresos.get(mes, (Decimal("0"), 0))
        total += monto
        n_pagos_total += n
        total_egr += egr
        n_egresos_total += n_egr
        meses.append(
            IngresosMesItem(
                mes=mes,
                etiqueta=ETIQUETAS_MES[mes - 1],
                monto=_money_str(monto),
                n_pagos=n,
                egresos=_money_str(egr),
                n_egresos=n_egr,
                utilidad=_money_str(monto - egr),
            )
        )
    return ResumenAnual(meses, total, n_pagos_total, total_egr, n_egresos_total)


# --------------------------------------------------------------------------- #
# Ingresos por mes (RF-COM-02)
# --------------------------------------------------------------------------- #
def ingresos_por_mes(
    db: Session, *, anio: int, sucursal_id: uuid.UUID | None = None
) -> IngresosReporte:
    """Ingresos, egresos y utilidad por mes del `anio` (C1 + finanzas).

    Ingresos: cuenta el `pago` CONFIRMADO (no las cuotas) para no doblar montos
    cuando un pago cubre varias cuotas. Egresos: `egreso.monto` por mes de
    `egreso.fecha`. Utilidad = ingresos - egresos (puede ser negativa).
    Devuelve siempre 12 meses + los totales del año.

    Con `sucursal_id` ambas series se acotan a esa sucursal (ver docstring del
    módulo: los egresos a nivel org quedan fuera).
    """
    desde = datetime(anio, 1, 1, tzinfo=UTC)
    hasta = datetime(anio + 1, 1, 1, tzinfo=UTC)

    filtros_pago = [
        Pago.estado == "CONFIRMADO",
        Pago.pagado_en.is_not(None),
        Pago.pagado_en >= desde,
        Pago.pagado_en < hasta,
    ]
    if sucursal_id is not None:
        # Un pago cubre cuotas de UN deportista → una sucursal; filtramos por la
        # sucursal del deportista de las cuotas del pago (igual que /pagos).
        pagos_en_sucursal = (
            select(PagoCuota.pago_id)
            .join(Cuota, Cuota.id == PagoCuota.cuota_id)
            .join(Inscripcion, Inscripcion.id == Cuota.inscripcion_id)
            .join(Deportista, Deportista.id == Inscripcion.deportista_id)
            .where(Deportista.sucursal_id == sucursal_id)
        )
        filtros_pago.append(Pago.id.in_(pagos_en_sucursal))

    mes_pago = cast(func.extract("month", Pago.pagado_en), Integer)
    rows = db.execute(
        select(
            mes_pago.label("mes"),
            func.coalesce(func.sum(Pago.monto), 0),
            func.count(),
        )
        .where(*filtros_pago)
        .group_by(mes_pago)
    ).all()

    filtros_egreso = [
        Egreso.fecha >= date(anio, 1, 1),
        Egreso.fecha <= date(anio, 12, 31),
    ]
    if sucursal_id is not None:
        filtros_egreso.append(Egreso.sucursal_id == sucursal_id)

    mes_egreso = cast(func.extract("month", Egreso.fecha), Integer)
    rows_egreso = db.execute(
        select(
            mes_egreso.label("mes"),
            func.coalesce(func.sum(Egreso.monto), 0),
            func.count(),
        )
        .where(*filtros_egreso)
        .group_by(mes_egreso)
    ).all()

    datos: dict[int, tuple[Decimal, int]] = {
        int(mes): (Decimal(str(monto)), int(n)) for (mes, monto, n) in rows
    }
    datos_egreso: dict[int, tuple[Decimal, int]] = {
        int(mes): (Decimal(str(monto)), int(n)) for (mes, monto, n) in rows_egreso
    }
    resumen = armar_meses(anio, datos, datos_egreso)

    return IngresosReporte(
        anio=anio,
        total=_money_str(resumen.total_ingresos),
        n_pagos=resumen.n_pagos,
        total_egresos=_money_str(resumen.total_egresos),
        n_egresos=resumen.n_egresos,
        utilidad=_money_str(resumen.total_ingresos - resumen.total_egresos),
        sucursal_id=sucursal_id,
        meses=resumen.meses,
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

    # Detalle por deportista (una fila por deportista con marcas en el rango).
    dep_rows = db.execute(
        base.join(Deportista, Deportista.id == Asistencia.deportista_id)
        .with_only_columns(
            Deportista.id,
            Deportista.ap_paterno,
            Deportista.ap_materno,
            Deportista.nombres,
            Categoria.nombre,
            Sucursal.nombre,
            sesiones_expr,
            presentes_expr,
            ausentes_expr,
            total_expr,
        )
        .group_by(
            Deportista.id,
            Deportista.ap_paterno,
            Deportista.ap_materno,
            Deportista.nombres,
            Categoria.nombre,
            Sucursal.nombre,
        )
        .order_by(Deportista.ap_paterno, Deportista.ap_materno, Deportista.nombres)
    ).all()

    # Detalle día por día: fecha de la sesión + estado, por deportista. Es UNA
    # consulta extra (no N+1) que después se reparte en memoria por deportista;
    # sin esto el reporte solo da porcentajes y no se le puede decir a un padre
    # QUÉ día faltó su hijo.
    marca_rows = db.execute(
        base.with_only_columns(
            Asistencia.deportista_id,
            Sesion.fecha,
            Asistencia.estado,
        ).order_by(Sesion.fecha)
    ).all()
    marcas_por_deportista: dict[uuid.UUID, list[MarcaAsistencia]] = {}
    for dep_id, fecha, estado in marca_rows:
        marcas_por_deportista.setdefault(dep_id, []).append(
            MarcaAsistencia(fecha=fecha.isoformat(), estado=estado)
        )

    por_deportista = [
        AsistenciaPorDeportista(
            marcas=marcas_por_deportista.get(dep_id, []),
            deportista=DeportistaRefReporte(
                id=dep_id,
                nombre_completo=" ".join(
                    p for p in (ap_pat, ap_mat, nombres) if p
                ).strip()
                or nombres,
            ),
            categoria=cat_nombre,
            sucursal=suc_nombre,
            sesiones=int(sesiones),
            presentes=int(presentes),
            ausentes=int(ausentes),
            total_marcas=int(total_marcas),
            pct_presente=pct_presente(int(presentes), int(total_marcas)),
        )
        for (
            dep_id,
            ap_pat,
            ap_mat,
            nombres,
            cat_nombre,
            suc_nombre,
            sesiones,
            presentes,
            ausentes,
            total_marcas,
        ) in dep_rows
    ]

    return AsistenciaReporte(
        desde=desde.isoformat(),
        hasta=hasta.isoformat(),
        global_=global_,
        por_categoria=por_categoria,
        por_deportista=por_deportista,
    )
