"""Schemas de la cola "Pagos por verificar" (C6, epic pagos-qr-comprobante).

Formas de request/response que consume el frontend ADMIN. Espejo EXACTO del shape
`ComprobantePendienteItem` congelado en la spec (C6): identificación pre-llena
(tutor por teléfono + cuota FIFO) + OCR best-effort + `imagen_url` firmada (HMAC
stateless, sin Bearer, para el `<img>` del navegador).

Dinero como `Decimal`; fechas como `date`/`datetime`.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, Field


class TutorRef(BaseModel):
    """Tutor identificado por el teléfono del remitente del comprobante."""

    id: uuid.UUID
    nombres: str


class CuotaElegible(BaseModel):
    """Cuota con saldo del tutor/escuela, elegible para asignar el comprobante (FIFO).

    Es la misma forma que `cuota_sugerida` del item: el front la usa tanto en el
    desplegable de selección como en la sugerencia pre-llena.
    """

    cuota_id: uuid.UUID
    deportista_nombre: str
    vence_el: date
    saldo: Decimal
    estado: str


class ComprobantePendienteItem(BaseModel):
    """Item de `GET /comprobantes/pendientes` (C6).

    `tutor`/`cuota_sugerida` son `None` cuando el teléfono no matchea ningún tutor
    ("sin identificar"). Los campos `*_ocr` son `None` si el OCR no leyó (best-effort).
    `imagen_url` es el enlace firmado (sin Bearer) de la captura.
    """

    id: uuid.UUID
    estado: str
    from_telefono: str
    created_at: datetime
    tutor: TutorRef | None = None
    cuota_sugerida: CuotaElegible | None = None
    monto_ocr: Decimal | None = None
    transaccion_id_ocr: str | None = None
    fecha_ocr: date | None = None
    imagen_url: str


class ComprobantesPendientesPage(BaseModel):
    """Página de la cola "Pagos por verificar"."""

    items: list[ComprobantePendienteItem]
    total: int
    page: int
    page_size: int


class ConfirmarComprobanteIn(BaseModel):
    """Body de `POST /comprobantes/{id}/confirmar`.

    `cuota_id` = la cuota a la que se imputa el pago (la sugerida FIFO, o cualquier
    otra con saldo de la escuela si era "sin identificar"). `monto` = efectivo de caja
    a aplicar (se reusa `registrar_pago_efectivo`, idempotente).
    """

    cuota_id: uuid.UUID
    monto: Decimal = Field(gt=0)


class RechazarComprobanteIn(BaseModel):
    """Body de `POST /comprobantes/{id}/rechazar`. `motivo` opcional (auditoría)."""

    motivo: str | None = None


class RechazarComprobanteOut(BaseModel):
    """Salida de `POST /comprobantes/{id}/rechazar`."""

    id: uuid.UUID
    estado: str
