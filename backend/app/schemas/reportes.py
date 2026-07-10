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
    """Un mes del reporte de ingresos (siempre los 12; `monto` "0.00" si vacío)."""

    mes: int  # 1..12
    etiqueta: str  # "ene", "feb", ...
    monto: str  # numeric como string, p. ej. "1500.00"
    n_pagos: int


class IngresosReporte(BaseModel):
    """`GET /reportes/ingresos?anio=YYYY` (C1).

    `total` = suma del año (string). `n_pagos` = nº de pagos CONFIRMADO del año
    (se cuenta el `pago`, no las cuotas, para no doblar). `meses` siempre trae 12.
    """

    anio: int
    total: str
    n_pagos: int
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
