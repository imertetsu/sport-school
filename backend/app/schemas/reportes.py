"""Schemas de Reportes (contrato C1).

Formas de response **espejo exacto** de C1; frontend-dev tipa contra ellas.

Decisión de serialización: los **montos van como `str`** (p. ej. `"0.00"`,
`"1500.00"`) — C1 dice explícitamente "Montos como string (numeric)" y el
frontend los pasa por `formatMoney`. El servicio arma el string ya `quantize`-ado
a 2 decimales, así que aquí el tipo es `str` (no `Decimal`) para que la forma del
JSON sea estable y no dependa de cómo FastAPI serialice `Decimal`.

`AsistenciaReporte.global_` se expone en el JSON como `global` vía alias
(`global` es palabra reservada en Python). El router usa
`response_model_by_alias=True` para que el frontend reciba la clave `global`.
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, Field


# --------------------------------------------------------------------------- #
# GET /reportes/ingresos
# --------------------------------------------------------------------------- #
class IngresosMesItem(BaseModel):
    """Un mes del reporte financiero (siempre los 12; montos "0.00" si vacío).

    `monto` conserva el nombre del contrato C1 original (= **ingresos** del mes);
    se le suman `egresos` y `utilidad` para poder graficar las tres series.
    """

    mes: int  # 1..12
    etiqueta: str  # "ene", "feb", ...
    monto: str  # ingresos del mes; numeric como string, p. ej. "1500.00"
    n_pagos: int
    egresos: str = "0.00"
    n_egresos: int = 0
    utilidad: str = "0.00"  # monto - egresos (negativo si el mes cerró en pérdida)


class IngresosReporte(BaseModel):
    """`GET /reportes/ingresos?anio=YYYY&sucursal_id=` (C1 + egresos/utilidad).

    `total` = ingresos del año (string). `n_pagos` = nº de pagos CONFIRMADO del
    año (se cuenta el `pago`, no las cuotas, para no doblar). `total_egresos` /
    `n_egresos` son el espejo del lado de salidas, y `utilidad` = total -
    total_egresos. `meses` siempre trae 12.

    Con `sucursal_id` los ingresos se acotan a los pagos de deportistas de esa
    sucursal y los egresos a los gastos de esa sucursal — los egresos a nivel
    organización (sucursal NULL) quedan **fuera**, porque no son atribuibles.
    """

    anio: int
    total: str
    n_pagos: int
    total_egresos: str = "0.00"
    n_egresos: int = 0
    utilidad: str = "0.00"
    # Eco del filtro aplicado (None = toda la organización).
    sucursal_id: uuid.UUID | None = None
    meses: list[IngresosMesItem]


# --------------------------------------------------------------------------- #
# GET /reportes/asistencia
# --------------------------------------------------------------------------- #
class CategoriaRefReporte(BaseModel):
    id: uuid.UUID
    nombre: str


class SucursalRefReporte(BaseModel):
    nombre: str


class AsistenciaGlobal(BaseModel):
    """Totales globales del reporte de asistencia (C1)."""

    sesiones: int
    presentes: int
    ausentes: int
    total_marcas: int
    pct_presente: float  # round(presentes/total_marcas*100, 1); 0 si total=0


class AsistenciaPorCategoria(BaseModel):
    """Desglose de asistencia por categoría/sucursal (C1)."""

    categoria: CategoriaRefReporte
    sucursal: SucursalRefReporte
    sesiones: int
    presentes: int
    ausentes: int
    total_marcas: int
    pct_presente: float


class DeportistaRefReporte(BaseModel):
    id: uuid.UUID
    nombre_completo: str


class MarcaAsistencia(BaseModel):
    """Una marca concreta: en qué fecha y con qué estado quedó el deportista.

    Es lo que permite responderle a un padre "faltó el 3 y el 10 de julio" en vez
    de solo "80%".
    """

    fecha: str  # YYYY-MM-DD (fecha de la sesión)
    estado: str  # PRESENTE | AUSENTE | (lo que registre asistencia)


class AsistenciaPorDeportista(BaseModel):
    """Asistencia de UN deportista en el rango: sus marcas y su % de presencia."""

    deportista: DeportistaRefReporte
    categoria: str | None = None
    sucursal: str | None = None
    sesiones: int
    presentes: int
    ausentes: int
    total_marcas: int
    pct_presente: float
    # Detalle día por día, en orden cronológico (para el desglose de la UI).
    marcas: list[MarcaAsistencia] = Field(default_factory=list)


class AsistenciaReporte(BaseModel):
    """`GET /reportes/asistencia?desde&hasta&sucursal_id&categoria_id` (C1)."""

    model_config = ConfigDict(populate_by_name=True)

    desde: str  # YYYY-MM-DD
    hasta: str  # YYYY-MM-DD
    # Clave JSON `global` (alias) — `global` es reservado en Python.
    global_: AsistenciaGlobal = Field(alias="global")
    por_categoria: list[AsistenciaPorCategoria]
    # Detalle por deportista del período (una fila por deportista con marcas).
    por_deportista: list[AsistenciaPorDeportista] = Field(default_factory=list)
