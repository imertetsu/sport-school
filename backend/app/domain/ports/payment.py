"""Puerto de cobro (proveedor de pagos QR, p.ej. OpenBCB).

El núcleo define esta interfaz; los adaptadores en `app.adapters` la implementan.
La selección del adaptador se hace por configuración de la organización
(`pais`/proveedor), inyectada, no hardcodeada. Esqueleto para este epic — la
lógica de cobranza/webhooks llega en un epic posterior (SRS §8).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class PaymentProvider(Protocol):
    """Genera cobros QR y resuelve su estado de forma idempotente."""

    def create_charge(self, *, reference: str, amount: float, currency: str) -> str:
        """Crea un cobro y devuelve el identificador/payload QR del proveedor.

        TODO(epic-cobranza): implementar en el adaptador concreto (OpenBCB).
        """
        ...

    def verify_webhook(self, *, payload: bytes, signature: str) -> bool:
        """Valida la firma de un webhook entrante.

        TODO(epic-cobranza): implementar; el webhook debe ser idempotente por
        `transaccion_id` (constraint único) — sin doble pago ni doble comprobante.
        """
        ...
