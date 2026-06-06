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
    """Item de `GET /cobranza/cuotas` (C4).

    Abonos: `monto_pagado` (acumulado aplicado) y `saldo` (= monto - monto_pagado).
    `estado` puede ser `PARCIAL`.
    """

    id: uuid.UUID
    alumno: AlumnoRef
    sucursal: SucursalNombre | None = None
    categoria: CategoriaNombre | None = None
    periodo_inicio: date
    vence_el: date
    monto: Decimal
    monto_pagado: Decimal = Decimal("0")
    saldo: Decimal = Decimal("0")
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
    """`GET /cobranza/panel` (C4).

    Abonos: `cuotas_pendientes`/`cuotas_vencidas` suman **saldos** (no montos
    nominales); morosidad por saldo. `credito_total` = Σ `credito.saldo` de la org.
    """

    ingresos_mes: IngresosMes
    alumnos_activos: AlumnosActivos
    cuotas_pendientes: CuotasAgg
    cuotas_vencidas: CuotasAgg
    morosidad: list[MorosidadItem]
    credito_total: Decimal = Decimal("0")


# --------------------------------------------------------------------------- #
# Pagos
# --------------------------------------------------------------------------- #
class PagoEfectivoIn(BaseModel):
    """`POST /cobranza/pagos/efectivo` (C3 + abonos).

    `monto_recibido` opcional (efectivo de caja). `None` ⇒ paga el total (Σ saldos).
    Si se envía debe ser `> 0`; un excedente sobre Σ saldos queda como crédito.
    """

    cuota_ids: list[uuid.UUID] = Field(..., min_length=1)
    monto_recibido: Decimal | None = Field(default=None, gt=0)


class PagoQrIn(BaseModel):
    """`POST /cobranza/pagos/qr` (C3)."""

    cuota_ids: list[uuid.UUID] = Field(..., min_length=1)


class CuotaAplicada(BaseModel):
    """Detalle por cuota de un pago efectivo con abono (RF-ABO)."""

    cuota_id: uuid.UUID
    monto_aplicado: Decimal
    saldo_restante: Decimal
    estado: str


class PagoOut(BaseModel):
    """Polling `GET /cobranza/pagos/{id}` (C3) + respuesta de pago efectivo (abonos).

    `monto` = efectivo de caja. `credito_aplicado` = crédito previo consumido;
    `credito_generado` = saldo a favor generado por el sobrepago. `cuotas_aplicadas`
    detalla qué recibió cada cuota. Defaults `0`/`[]` ⇒ el polling QR no se rompe.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    estado: str
    metodo: str
    monto: Decimal
    comprobante_url: str | None = None
    credito_aplicado: Decimal = Decimal("0")
    credito_generado: Decimal = Decimal("0")
    cuotas_aplicadas: list[CuotaAplicada] = Field(default_factory=list)


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
