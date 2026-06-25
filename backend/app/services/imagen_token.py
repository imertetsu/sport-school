"""Token HMAC para servir imágenes (QR de cobro y comprobantes) al `<img>` del navegador.

Las imágenes binarias (el QR de la escuela y la captura del comprobante) las consume
un `<img src=...>` del front, que **NO** envía el header `Authorization`. Por eso el
binario se sirve por una URL **firmada/tokenizada** (sin Bearer), exactamente como el
recibo PDF (`services/recibo_token.py`): HMAC-SHA256 con `jwt_secret`, verificación en
tiempo constante, sin expiración (decisión de producto: el recurso es estable).

`kind` distingue el tipo de imagen (`qr` | `comprobante`) para que un token de un QR
no valga para un comprobante y viceversa. La validez del recurso (que exista y sea de
la org) la chequea el router bajo RLS — el token solo prueba que el caller conoce el
par `(kind, org_id, recurso_id)` firmado.

Funciones puras (sin I/O). Capa de servicios: el dominio no las importa.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import uuid

from app.core.config import settings

# Tipos de imagen tokenizable. El `kind` entra en el mensaje firmado, así que un token
# de QR no valida un comprobante (y viceversa).
KIND_QR = "qr"
KIND_COMPROBANTE = "comprobante"


def _mensaje(kind: str, org_id: uuid.UUID, recurso_id: uuid.UUID) -> bytes:
    return f"imagen:{kind}:{org_id}:{recurso_id}".encode()


def firmar(kind: str, org_id: uuid.UUID, recurso_id: uuid.UUID) -> str:
    """`base64url(HMAC_SHA256(key=jwt_secret, msg='imagen:{kind}:{org}:{recurso}'))`."""
    digest = hmac.new(
        settings.jwt_secret.encode("utf-8"),
        _mensaje(kind, org_id, recurso_id),
        hashlib.sha256,
    ).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def token_valido(kind: str, org_id: uuid.UUID, recurso_id: uuid.UUID, token: str) -> bool:
    """True si `token` es la firma HMAC esperada para `(kind, org_id, recurso_id)`.

    Comparación en tiempo constante (`hmac.compare_digest`).
    """
    esperado = firmar(kind, org_id, recurso_id)
    return hmac.compare_digest(esperado, token)


def url_qr(org_id: uuid.UUID) -> str:
    """URL pública firmada del QR de cobro de la org.

    `{public_base_url}/api/v1/qr-cobro/{org}/{token}.img`. El QR es 1 por org, así que
    el recurso firmado es el propio `org_id`.
    """
    token = firmar(KIND_QR, org_id, org_id)
    base = settings.public_base_url.rstrip("/")
    return f"{base}/api/v1/qr-cobro/{org_id}/{token}.img"


def url_comprobante(org_id: uuid.UUID, comprobante_id: uuid.UUID) -> str:
    """URL pública firmada de la captura de un comprobante.

    `{public_base_url}/api/v1/comprobantes/{org}/{comprobante}/{token}.img`.
    """
    token = firmar(KIND_COMPROBANTE, org_id, comprobante_id)
    base = settings.public_base_url.rstrip("/")
    return f"{base}/api/v1/comprobantes/{org_id}/{comprobante_id}/{token}.img"
