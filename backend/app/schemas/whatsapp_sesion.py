"""Schemas de `/mi-escuela/whatsapp/*` (contrato 4, epic whatsapp-multitenant).

Contrato OpenAPI que consume el frontend (pantalla de Ajustes → WhatsApp, solo ADMIN).
La **verdad LIVE** de la conexión (connected / QR vivo) es el **sidecar** multi-sesión;
el backend reconcilia la fila `whatsapp_sesion` en cada lectura y devuelve estos shapes.
El browser nunca ve el `X-Gateway-Token` ni la URL del sidecar: el QR data-url viaja
browser ← backend ← sidecar.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class WhatsAppEstadoOut(BaseModel):
    """Respuesta de `GET /mi-escuela/whatsapp/estado` (estado reconciliado de la sesión)."""

    estado: Literal["DESVINCULADA", "PENDIENTE_QR", "CONECTADA"]
    numero: str | None = None
    vinculado_en: datetime | None = None


class WhatsAppQrOut(BaseModel):
    """Respuesta de `POST /mi-escuela/whatsapp/vincular` y `GET /mi-escuela/whatsapp/qr`.

    `qr` es el data-url (`data:image/png;base64,...`) mientras la sesión está en
    `PENDIENTE_QR`; `None` si el sidecar aún no lo generó (el front reintenta). Si la
    sesión ya está `CONECTADA`, `qr` es `None` y se rellena `numero`.
    """

    estado: Literal["PENDIENTE_QR", "CONECTADA"]
    qr: str | None = None
    numero: str | None = None
