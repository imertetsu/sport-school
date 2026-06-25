"""Webhook ENTRANTE del gateway no-oficial (Baileys) — epic whatsapp-gateway.

Ruta NUEVA y DISTINTA del webhook de estados de Meta (`/webhooks/whatsapp`, no se
toca). El sidecar Node, al recibir un mensaje de WhatsApp, hace `POST` a esta ruta con
el header compartido `X-Gateway-Token` y un body
`{"org_id": "<uuid>", "from": "<dígitos>", "text": "<string>", "message_id": "<id>",
"timestamp": <epoch>}`. El `org_id` lo añade el sidecar **multi-sesión** (epic
whatsapp-multitenant): identifica la escuela cuya sesión recibió el mensaje.

Alcance MVP (sección "Entrante" de la spec): **validar token → loguear → 200**. Canal
bidireccional ABIERTO y demostrado, SIN lógica de auto-respuesta/chatbot todavía. Por
eso este webhook **NO escribe en BD** (ni pagos ni conversaciones): así no necesita
contexto de tenant/RLS ni migración (queda como follow-up explícito).

Auth: header `X-Gateway-Token` debe coincidir con `settings.whatsapp_gateway_token`.
Ausente o incorrecto ⇒ **401**. No se valida firma HMAC (el sidecar es nuestro, el token
compartido basta), a diferencia del webhook de Meta que sí firma con `X-Hub-Signature-256`.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Header, Request, status
from fastapi.responses import JSONResponse

from app.core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post("/whatsapp-inbound", response_model=None)
async def whatsapp_inbound(
    request: Request,
    x_gateway_token: str | None = Header(default=None, alias="X-Gateway-Token"),
) -> JSONResponse:
    """Recibe un mensaje entrante del sidecar: valida token, loguea y responde 200.

    NO escribe en BD (solo loguea `org_id`/`from`/`message_id`/`text`). El `org_id`
    (escuela cuya sesión multi-tenant recibió el mensaje) se loguea pero NO se usa como
    contexto de RLS (este webhook no toca BD). Token ausente o incorrecto ⇒ 401
    (fail-closed). Body no-JSON ⇒ se loguea y se ACK con 200 (no se rompe el pipe del
    sidecar).
    """
    esperado = settings.whatsapp_gateway_token
    if not esperado or x_gateway_token != esperado:
        logger.warning("webhook whatsapp-inbound: X-Gateway-Token inválido/ausente; 401")
        return JSONResponse(
            status_code=status.HTTP_401_UNAUTHORIZED,
            content={"detail": "X-Gateway-Token inválido"},
        )

    try:
        payload = await request.json()
    except Exception:  # noqa: BLE001 - body no-JSON: ACK igualmente, no rompemos el sidecar.
        logger.info("webhook whatsapp-inbound: body no-JSON; ACK")
        return JSONResponse(status_code=status.HTTP_200_OK, content={"status": "ok"})

    if not isinstance(payload, dict):
        payload = {}

    logger.info(
        "webhook whatsapp-inbound: org_id=%s from=%s message_id=%s text=%s",
        payload.get("org_id"),
        payload.get("from"),
        payload.get("message_id"),
        payload.get("text"),
    )
    return JSONResponse(status_code=status.HTTP_200_OK, content={"status": "ok"})
