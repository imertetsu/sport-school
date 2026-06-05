"""Puerto de cobro (proveedor de pagos QR, p.ej. OpenBCB).

El núcleo define esta interfaz; los adaptadores en `app.adapters` la implementan.
La selección del adaptador se hace por configuración de la organización
(`pais`/proveedor), inyectada, no hardcodeada. Estructuras de dominio puras (sin
SQLAlchemy ni FastAPI).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class QrCharge:
    """Resultado de crear un cobro QR (C3).

    - `qr_ref`: referencia interna única del QR (clave que resuelve el webhook).
    - `payload`: cadena del QR (lo que el banco/app escanea).
    - `qr_png_data_url`: PNG embebido como `data:image/png;base64,...` para la UI.
    """

    qr_ref: str
    payload: str
    qr_png_data_url: str


@runtime_checkable
class PaymentProvider(Protocol):
    """Genera cobros QR y resuelve su estado de forma idempotente."""

    def create_qr_charge(self, *, reference: str, amount: Decimal, currency: str) -> QrCharge:
        """Crea un cobro QR y devuelve `qr_ref` + payload + PNG data-url (C3).

        El `qr_ref` debe ser único; es la referencia interna que el webhook usa
        (vía `webhook_resolver`) para localizar el pago saltando RLS.
        """
        ...

    def verify_webhook(self, *, payload: bytes, signature: str) -> bool:
        """Valida la firma de un webhook entrante.

        El webhook debe ser idempotente por `transaccion_id` (constraint único) —
        sin doble pago ni doble comprobante. El sandbox no firma (devuelve True).
        """
        ...
