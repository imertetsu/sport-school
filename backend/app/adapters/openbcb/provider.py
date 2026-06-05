"""Adaptador OpenBCB **sandbox** — implementa `PaymentProvider` (C3).

No habla con el BCB real (requiere onboarding/credenciales, fuera de alcance):
genera un `qr_ref` único, un `payload` simulado y un PNG (QR) embebido como
`data:image/png;base64,...` con la librería `qrcode`. La confirmación se simula
vía el endpoint `…/simular-confirmacion`, que reentra al mismo flujo del webhook.
"""

from __future__ import annotations

import base64
import uuid
from decimal import Decimal
from io import BytesIO

import qrcode

from app.domain.ports.payment import PaymentProvider, QrCharge


class OpenBcbSandboxProvider(PaymentProvider):
    """Proveedor de cobro QR simulado para dev/demo."""

    def create_qr_charge(self, *, reference: str, amount: Decimal, currency: str) -> QrCharge:
        """Crea un cobro QR sandbox: `qr_ref` único + payload + PNG data-url."""
        qr_ref = f"qr_{uuid.uuid4().hex}"
        # Payload simulado tipo "deep link" de cobro (no es un QR EMV real).
        payload = f"openbcb-sandbox://pay?ref={qr_ref}&amount={amount}&ccy={currency}"
        return QrCharge(
            qr_ref=qr_ref,
            payload=payload,
            qr_png_data_url=self._png_data_url(payload),
        )

    def verify_webhook(self, *, payload: bytes, signature: str) -> bool:
        """El sandbox no firma; siempre acepta (la idempotencia la da el modelo)."""
        return True

    @staticmethod
    def _png_data_url(payload: str) -> str:
        """Genera el PNG del QR y lo devuelve como data-url base64 para la UI."""
        img = qrcode.make(payload)
        buf = BytesIO()
        img.save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        return f"data:image/png;base64,{b64}"
