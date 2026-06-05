"""Schemas de Cobranza (contrato C4).

Formas de request/response **espejo exacto** de C4; frontend-dev tipa contra
ellas. Dinero como `Decimal`; fechas como `date`/`datetime`.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


# --------------------------------------------------------------------------- #
# Generación
# --------------------------------------------------------------------------- #
class GenerarOut(BaseModel):
    """`POST /cobranza/generar` -> `{creadas:n}`."""

    creadas: int


# --------------------------------------------------------------------------- #
# Cuotas (lista paginada)
# --------------------------------------------------------------------------- #
class AlumnoRef(BaseModel):
    id: uuid.UUID
    nombre_completo: str


class SucursalNombre(BaseModel):
    nombre: str


class CategoriaNombre(BaseModel):
    nombre: str


class CuotaItem(BaseModel):
    """Item de `GET /cobranza/cuotas` (C4)."""

    id: uuid.UUID
    alumno: AlumnoRef
    sucursal: SucursalNombre | None = None
    categoria: CategoriaNombre | None = None
    periodo_inicio: date
    vence_el: date
    monto: Decimal
    estado: str
    ultimo_metodo: str | None = None


class CuotasPage(BaseModel):
    """`GET /cobranza/cuotas` -> `{items, total, page, page_size}` (C4)."""

    items: list[CuotaItem]
    total: int
    page: int
    page_size: int


# --------------------------------------------------------------------------- #
# Panel (KPIs + morosidad)
# --------------------------------------------------------------------------- #
class IngresosMes(BaseModel):
    monto: Decimal


class AlumnosActivos(BaseModel):
    count: int
    sucursales: int
    disciplinas: int


class CuotasAgg(BaseModel):
    count: int
    monto: Decimal


class MorosidadItem(BaseModel):
    alumno_id: uuid.UUID
    nombre_completo: str
    categoria: str | None = None
    monto: Decimal
    dias_mora: int


class PanelOut(BaseModel):
    """`GET /cobranza/panel` (C4)."""

    ingresos_mes: IngresosMes
    alumnos_activos: AlumnosActivos
    cuotas_pendientes: CuotasAgg
    cuotas_vencidas: CuotasAgg
    morosidad: list[MorosidadItem]


# --------------------------------------------------------------------------- #
# Pagos
# --------------------------------------------------------------------------- #
class PagoEfectivoIn(BaseModel):
    """`POST /cobranza/pagos/efectivo` (C3)."""

    cuota_ids: list[uuid.UUID] = Field(..., min_length=1)


class PagoQrIn(BaseModel):
    """`POST /cobranza/pagos/qr` (C3)."""

    cuota_ids: list[uuid.UUID] = Field(..., min_length=1)


class PagoOut(BaseModel):
    """Polling `GET /cobranza/pagos/{id}` (C3)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    estado: str
    metodo: str
    monto: Decimal
    comprobante_url: str | None = None


class QrOut(BaseModel):
    """Respuesta de `POST /cobranza/pagos/qr` (C3): QR + monto esperado."""

    pago_id: uuid.UUID
    estado: str
    monto: Decimal
    qr_ref: str
    qr_payload: str
    qr_png_data_url: str


class WebhookIn(BaseModel):
    """Body de `POST /webhooks/openbcb` (C3)."""

    transaccion_id: str
    referencia: str
    monto: Decimal
