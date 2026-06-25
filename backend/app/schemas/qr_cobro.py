"""Schemas del QR de cobro estático por escuela (C6, epic pagos-qr-comprobante).

Formas de salida que consume el frontend (Ajustes → subir/ver/borrar el QR). El
binario del QR NO viaja en estos schemas: se sirve por una URL **firmada** (HMAC
stateless, mismo mecanismo que el recibo PDF) en `imagen_url`, para que un `<img>`
del navegador (sin header `Authorization`) pueda renderizarla.
"""

from __future__ import annotations

from pydantic import BaseModel


class QrCobroMetaOut(BaseModel):
    """Metadata del QR de cobro de la escuela.

    `tiene_qr=False` ⇒ `mime`/`tamano_bytes`/`imagen_url` quedan en `None`. Cuando hay
    QR, `imagen_url` es el enlace firmado (sin Bearer) que el `<img>` del front consume.
    """

    tiene_qr: bool
    mime: str | None = None
    tamano_bytes: int | None = None
    imagen_url: str | None = None
