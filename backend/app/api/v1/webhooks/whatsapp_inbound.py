"""Webhook ENTRANTE del gateway no-oficial (Baileys) — epic whatsapp-gateway.

Ruta NUEVA y DISTINTA del webhook de estados de Meta (`/webhooks/whatsapp`, no se
toca). El sidecar Node, al recibir un mensaje de WhatsApp, hace `POST` a esta ruta con
el header compartido `X-Gateway-Token` y un body.

- **Texto** (retrocompat): `{org_id, from, text, message_id, timestamp}` SIN `tipo` →
  **solo se loguea** (chatbot/persistencia de texto = futuro). El `org_id` lo añade el
  sidecar **multi-sesión** (epic whatsapp-multitenant): la escuela cuya sesión recibió.
- **Imagen** (epic pagos-qr-comprobante, C4): `{org_id, from, tipo:"image",
  media:"<base64>", mime, caption, message_id, timestamp}` → es un **comprobante de
  pago**: se procesa con `comprobantes_svc.procesar_comprobante_inbound`, que guarda la
  fila en `comprobante_pendiente` (cola "Pagos por verificar"). Al pasar a **escribir
  BD**, el servicio **fija `app.current_org`** (`set_config` + `ContextVar`) dentro de
  la tx — invariante anti-fuga del repo (hoy el inbound de texto NO escribía, por eso no
  fijaba contexto).

Responde **200 siempre** (idempotente; los errores internos se loguean y se ACK 200 para
no romper el pipe del sidecar — RNF-06: nunca se descarta un pago por un fallo interno).

Auth: header `X-Gateway-Token` debe coincidir con `settings.whatsapp_gateway_token`.
Ausente o incorrecto ⇒ **401**. No se valida firma HMAC (el sidecar es nuestro, el token
compartido basta), a diferencia del webhook de Meta que sí firma con `X-Hub-Signature-256`.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Header, Request, status
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.db import SessionLocal
from app.services import comprobantes as comprobantes_svc

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

_OK = JSONResponse(status_code=status.HTTP_200_OK, content={"status": "ok"})


def _procesar_imagen(payload: dict) -> None:
    """Procesa un comprobante (imagen) entrante: abre su propia tx, fija org, guarda.

    Endpoint sin auth de usuario (no usa `get_db`): abre su propia sesión. El servicio
    fija `app.current_org` dentro de la tx (anti-fuga) antes de escribir. Idempotente
    por `message_id`. NO lanza hacia arriba: cualquier fallo se loguea y se ACK 200.
    """
    org_id = payload.get("org_id")
    media = payload.get("media")
    if not org_id or not media:
        logger.warning("webhook whatsapp-inbound image: falta org_id/media; se ignora")
        return

    db = SessionLocal()
    try:
        comprobantes_svc.procesar_comprobante_inbound(
            db,
            org_id=str(org_id),
            from_telefono=str(payload.get("from") or ""),
            media_b64=str(media),
            mime=str(payload.get("mime") or "image/jpeg"),
            caption=payload.get("caption"),
            message_id=payload.get("message_id"),
        )
        db.commit()
    except Exception:  # noqa: BLE001 - ACK 200 igual; no rompemos el sidecar (RNF-06).
        db.rollback()
        logger.exception("webhook whatsapp-inbound: fallo procesando comprobante (imagen)")
    finally:
        db.close()


@router.post("/whatsapp-inbound", response_model=None)
async def whatsapp_inbound(
    request: Request,
    x_gateway_token: str | None = Header(default=None, alias="X-Gateway-Token"),
) -> JSONResponse:
    """Recibe un mensaje entrante del sidecar: valida token, procesa/loguea, ACK 200.

    Token ausente o incorrecto ⇒ 401 (fail-closed). Body no-JSON ⇒ se loguea y se ACK
    200. `tipo == "image"` ⇒ comprobante de pago (guarda en BD, fijando contexto org).
    Texto (sin `tipo`/`text`) ⇒ solo loguea (como hasta ahora).
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
        return _OK

    if not isinstance(payload, dict):
        payload = {}

    tipo = payload.get("tipo")
    if tipo == "image":
        logger.info(
            "webhook whatsapp-inbound: comprobante (imagen) org_id=%s from=%s message_id=%s",
            payload.get("org_id"),
            payload.get("from"),
            payload.get("message_id"),
        )
        _procesar_imagen(payload)
        return _OK

    # Texto (sin `tipo` o "text"): solo se loguea, como hasta ahora.
    logger.info(
        "webhook whatsapp-inbound: org_id=%s from=%s message_id=%s text=%s",
        payload.get("org_id"),
        payload.get("from"),
        payload.get("message_id"),
        payload.get("text"),
    )
    return _OK
