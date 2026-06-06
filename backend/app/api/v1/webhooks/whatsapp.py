"""Webhook de estados de WhatsApp (Meta Cloud API) — MVP mínimo, AISLADO del pago.

Dos rutas, **sin auth de app** (Meta firma el POST):

- `GET  /webhooks/whatsapp`: verificación del webhook (handshake de Meta). Devuelve
  el `hub.challenge` en texto plano si `hub.mode == "subscribe"` y el
  `hub.verify_token` coincide con `settings.whatsapp_verify_token`; si no, 403.
- `POST /webhooks/whatsapp`: recibe estados de entrega (sent/delivered/read/failed).
  Si `settings.whatsapp_app_secret` está configurado, valida la firma
  `X-Hub-Signature-256` (HMAC-SHA256 del body crudo); firma inválida ⇒ 403. Solo
  **LOGUEA** cada estado/`message_id` (info) y responde **200 SIEMPRE** (ACK). Es
  idempotente por construcción: no escribe en BD, solo loguea.

IMPORTANTE — este webhook **NO concilia pagos**. El cobro QR adjunto al
recordatorio se confirma por el webhook de cobro `POST /webhooks/openbcb`
(idempotente por `transaccion_id`), que NO se toca aquí. Actualizar
`recordatorio_pago` por `message_id` requeriría contexto de tenant/RLS o un
resolver SECURITY DEFINER (como hace OpenBCB); queda como TODO fuera del MVP.
"""

from __future__ import annotations

import hashlib
import hmac
import logging

from fastapi import APIRouter, Request, Response, status
from fastapi.responses import PlainTextResponse

from app.core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.get("/whatsapp")
async def whatsapp_verify(request: Request) -> Response:
    """Handshake de verificación de Meta. Devuelve `hub.challenge` o 403."""
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    verify_token = settings.whatsapp_verify_token
    if mode == "subscribe" and verify_token and token == verify_token:
        return PlainTextResponse(challenge or "", status_code=status.HTTP_200_OK)
    return Response(status_code=status.HTTP_403_FORBIDDEN)


def _firma_valida(body: bytes, signature_header: str | None, app_secret: str) -> bool:
    """Valida `X-Hub-Signature-256: sha256=<hex>` (HMAC-SHA256 del body crudo)."""
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    recibido = signature_header.split("=", 1)[1]
    esperado = hmac.new(app_secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(recibido, esperado)


@router.post("/whatsapp", response_model=None)
async def whatsapp_status(request: Request) -> Response | dict[str, str]:
    """Recibe estados de entrega y SOLO loguea. 200 siempre (ACK).

    NO escribe en `recordatorio_pago` ni concilia pagos (ver docstring de módulo).
    """
    body = await request.body()

    app_secret = settings.whatsapp_app_secret
    if app_secret:
        signature = request.headers.get("X-Hub-Signature-256")
        if not _firma_valida(body, signature, app_secret):
            logger.warning("webhook whatsapp: firma X-Hub-Signature-256 inválida; descartado")
            return Response(status_code=status.HTTP_403_FORBIDDEN)

    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001 - body no-JSON: ACK igualmente, no rompemos.
        logger.info("webhook whatsapp: body no-JSON; ACK")
        return {"status": "ok"}

    # Estructura Meta: entry[].changes[].value.statuses[] = [{id, status, ...}].
    for entry in payload.get("entry", []) or []:
        for change in entry.get("changes", []) or []:
            value = change.get("value", {}) or {}
            for estado in value.get("statuses", []) or []:
                logger.info(
                    "webhook whatsapp estado: message_id=%s status=%s",
                    estado.get("id"),
                    estado.get("status"),
                )

    return {"status": "ok"}
