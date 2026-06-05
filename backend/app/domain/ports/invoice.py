"""Puerto de facturación/comprobantes (PDF local, SIN en fase 2).

El núcleo define la interfaz; los adaptadores la implementan. Esqueleto para
este epic — emisión real llega en un epic posterior.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class InvoiceProvider(Protocol):
    """Emite comprobantes/facturas para un pago."""

    def issue(self, *, payment_id: str) -> bytes:
        """Emite el comprobante y devuelve el documento (p.ej. PDF en bytes).

        TODO(epic-cobranza): implementar en el adaptador concreto. La emisión
        debe ser idempotente respecto al pago (no duplicar comprobantes).
        """
        ...
