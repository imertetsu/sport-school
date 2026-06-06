"""Token HMAC para el enlace público del recibo PDF (epic Sucursales/Recibo).

El recibo se entrega al tutor por WhatsApp como un **enlace** (Meta no manda
binarios arbitrarios). El enlace debe ser público (sin auth) pero **inadivinable**
(RNF-02): se firma con HMAC-SHA256 usando el `jwt_secret` de la org/instalación.

`firmar_recibo` y `token_valido` son funciones puras (sin I/O): firman/verifican
`recibo:{org_id}:{pago_id}`. La verificación usa `hmac.compare_digest` (comparación
en tiempo constante). **Sin expiración** (decisión de producto): el recibo de un
pago confirmado no caduca. La validez del recurso (que el pago exista y esté
CONFIRMADO) la chequea el router bajo RLS — el token solo prueba que el caller
conoce el par (org, pago) firmado.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import uuid

from app.core.config import settings


def _mensaje(org_id: uuid.UUID, pago_id: uuid.UUID) -> bytes:
    return f"recibo:{org_id}:{pago_id}".encode()


def firmar_recibo(org_id: uuid.UUID, pago_id: uuid.UUID) -> str:
    """Devuelve `base64url(HMAC_SHA256(key=jwt_secret, msg='recibo:{org}:{pago}'))`.

    Sin padding `=` (base64url estándar para URLs).
    """
    digest = hmac.new(
        settings.jwt_secret.encode("utf-8"),
        _mensaje(org_id, pago_id),
        hashlib.sha256,
    ).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def token_valido(org_id: uuid.UUID, pago_id: uuid.UUID, token: str) -> bool:
    """True si `token` es la firma HMAC esperada para `(org_id, pago_id)`.

    Comparación en tiempo constante (`hmac.compare_digest`) para no filtrar la firma
    por timing.
    """
    esperado = firmar_recibo(org_id, pago_id)
    return hmac.compare_digest(esperado, token)


def url_recibo(org_id: uuid.UUID, pago_id: uuid.UUID) -> str:
    """URL pública del recibo PDF: `{public_base_url}/api/v1/recibos/{org}/{pago}/{token}.pdf`."""
    token = firmar_recibo(org_id, pago_id)
    base = settings.public_base_url.rstrip("/")
    return f"{base}/api/v1/recibos/{org_id}/{pago_id}/{token}.pdf"
