"""Webhook de WhatsApp (Meta Cloud API) — estados de entrega + mensajes entrantes.

Dos rutas, **sin auth de app** (Meta firma el POST):

- `GET  /webhooks/whatsapp`: verificación del webhook (handshake de Meta). Devuelve
  el `hub.challenge` en texto plano si `hub.mode == "subscribe"` y el
  `hub.verify_token` coincide con `settings.whatsapp_verify_token`; si no, 403.
- `POST /webhooks/whatsapp`: recibe eventos. Si `settings.whatsapp_app_secret` está
  configurado, valida la firma `X-Hub-Signature-256` (HMAC-SHA256 del body crudo);
  firma inválida ⇒ 403. Responde **200 SIEMPRE** (ACK), incluso ante un fallo interno:
  un 500 haría que Meta reintente en bucle.

Qué hace con cada evento:

- `messages[]` (el tutor escribe) ⇒ se guarda en la bandeja del chat
  (`chat_whatsapp.registrar_entrante`), creando el hilo si es nuevo y resolviendo a qué
  escuela pertenece por el teléfono del tutor. Idempotente por `provider_message_id`
  (UNIQUE): la re-entrega de Meta no duplica burbujas.
- `statuses[]` (sent/delivered/read/failed) ⇒ avanza el estado del saliente
  correspondiente, si es nuestro. Sigue logueándose el `errors[]` con su código (p. ej.
  131047 "re-engagement"), que es lo único que explica un `failed`.
- `message_template_status_update` ⇒ solo log (aviso de alta/aprobación de plantilla).

IMPORTANTE — este webhook **NO concilia pagos**. El cobro QR adjunto al recordatorio se
confirma por `POST /webhooks/openbcb` (idempotente por `transaccion_id`), que NO se toca
aquí. Actualizar `recordatorio_pago` por `message_id` sigue siendo un TODO aparte.

Contexto de BD: el endpoint no tiene usuario, así que abre su propia sesión y fija
`app.whatsapp_inbox` (GUC exclusivo de las tablas del chat) — hace falta porque los
mensajes de un número aún sin clasificar tienen `org_id IS NULL` y ninguna policy de
tenant los dejaría insertar.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Request, Response, status
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import PlainTextResponse

from app.core.config import settings
from app.core.db import SessionLocal
from app.domain.ports.whatsapp import WhatsAppPort
from app.services import chat_whatsapp as chat_svc
from app.services.deps import get_whatsapp_port

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])

# Tipos de mensaje de Meta que sabemos representar tal cual en el hilo. El resto
# (audio, vídeo, sticker, ubicación, contactos…) entra como OTRO: se registra la
# burbuja con una etiqueta para que la conversación no tenga huecos, aunque el
# contenido no se guarde.
_TIPO_TEXTO = ("text",)
_TIPO_IMAGEN = ("image",)


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


def _momento(raw: Any) -> datetime:
    """`timestamp` de Meta (epoch en segundos, como string) → datetime UTC.

    Ante un valor ausente o ilegible cae a "ahora": preferimos una burbuja con la hora
    aproximada a perder el mensaje.
    """
    try:
        return datetime.fromtimestamp(int(str(raw)), tz=UTC)
    except (TypeError, ValueError):
        return datetime.now(UTC)


def _detalle_error(estado: dict[str, Any]) -> str:
    """Código + motivo del `errors[]` de un status (p. ej. `131047 Re-engagement`).

    Sin esto un `status=failed` no dice nada y hay que adivinar por qué no llegó.
    """
    errores = estado.get("errors") or []
    if not errores:
        return ""
    e = errores[0]
    titulo = e.get("title") or e.get("message") or ""
    extra = (e.get("error_data") or {}).get("details") or ""
    return f" error={e.get('code')} {titulo}" + (f" ({extra})" if extra else "")


def _contenido(mensaje: dict[str, Any], port: WhatsAppPort) -> dict[str, Any]:
    """Traduce un `messages[]` de Meta a los campos de nuestra burbuja.

    La descarga del adjunto ocurre AQUÍ, fuera de la transacción: el binario viaja por
    dos llamadas HTTP a la Graph API y no tiene sentido tener la tx abierta mientras.
    Si la descarga falla, el mensaje se registra igual (sin imagen).
    """
    tipo_meta = mensaje.get("type")
    if tipo_meta in _TIPO_TEXTO:
        return {"tipo": "TEXTO", "texto": (mensaje.get("text") or {}).get("body")}

    if tipo_meta in _TIPO_IMAGEN:
        imagen = mensaje.get("image") or {}
        media_id = imagen.get("id")
        descarga = port.fetch_media(str(media_id)) if media_id else None
        return {
            "tipo": "IMAGEN",
            "texto": imagen.get("caption"),
            "media": descarga.data if descarga else None,
            "media_mime": descarga.mime if descarga else None,
        }

    return {"tipo": "OTRO", "texto": f"[{tipo_meta or 'mensaje'}]"}


def _procesar(payload: dict[str, Any]) -> None:
    """Persiste entrantes y estados. SÍNCRONA: la llama `run_in_threadpool`.

    Abre su propia sesión (no hay usuario) y fija el GUC de la bandeja. Nunca lanza
    hacia arriba: cualquier fallo se loguea y el endpoint responde 200 igual.
    """
    port = get_whatsapp_port()

    for entry in payload.get("entry", []) or []:
        # `entry.id` es el WABA que originó el evento. Se loguea porque es el ÚNICO
        # lugar donde el sistema lo ve: la Graph API no deja llegar a la WABA desde el
        # id del número ni desde el de la app, y es el dato que hace falta para
        # consultar las plantillas.
        logger.info("webhook whatsapp: waba_id=%s", entry.get("id"))
        for change in entry.get("changes", []) or []:
            value = change.get("value", {}) or {}

            # Nombre de perfil por número (Meta lo manda aparte de los mensajes).
            perfiles: dict[str, str] = {}
            for contacto in value.get("contacts") or []:
                wa_id = contacto.get("wa_id")
                nombre = (contacto.get("profile") or {}).get("name")
                if wa_id and nombre:
                    perfiles[str(wa_id)] = str(nombre)

            entrantes = value.get("messages") or []
            # El contenido (con la descarga del adjunto) se resuelve ANTES de abrir la
            # transacción; ver `_contenido`.
            preparados = [(m, _contenido(m, port)) for m in entrantes]

            estados = value.get("statuses") or []
            for estado in estados:
                logger.info(
                    "webhook whatsapp estado: message_id=%s destino=%s status=%s%s",
                    estado.get("id"),
                    estado.get("recipient_id"),
                    estado.get("status"),
                    _detalle_error(estado),
                )

            if preparados or estados:
                _escribir(preparados, estados, perfiles)

            # Alta/aprobación/rechazo de una PLANTILLA. Es el aviso de que el canal
            # oficial quedó habilitado para el cron de cobranza, que no puede salir
            # hasta que Meta apruebe. Sin esto habría que ir a preguntar.
            if change.get("field") == "message_template_status_update":
                logger.info(
                    "webhook whatsapp PLANTILLA: %s [%s] -> %s%s",
                    value.get("message_template_name"),
                    value.get("message_template_language"),
                    value.get("event"),
                    f" (motivo: {value['reason']})" if value.get("reason") else "",
                )


def _escribir(
    preparados: list[tuple[dict[str, Any], dict[str, Any]]],
    estados: list[dict[str, Any]],
    perfiles: dict[str, str],
) -> None:
    """Escribe entrantes y estados en una transacción. No lanza (loguea y sigue)."""
    db = SessionLocal()
    try:
        chat_svc.fijar_contexto_bandeja(db)
        for mensaje, contenido in preparados:
            desde = str(mensaje.get("from") or "")
            chat_svc.registrar_entrante(
                db,
                telefono=desde,
                provider_message_id=mensaje.get("id"),
                nombre_perfil=perfiles.get(desde),
                ocurrido_en=_momento(mensaje.get("timestamp")),
                **contenido,
            )
        for estado in estados:
            message_id = estado.get("id")
            if not message_id:
                continue
            chat_svc.actualizar_estado(
                db,
                provider_message_id=str(message_id),
                estado_meta=str(estado.get("status") or ""),
                error_detalle=_detalle_error(estado).strip() or None,
            )
        db.commit()
    except Exception:  # noqa: BLE001 - ACK 200 igual; Meta reintentaría en bucle.
        db.rollback()
        logger.exception("webhook whatsapp: fallo persistiendo eventos")
    finally:
        db.close()


@router.post("/whatsapp", response_model=None)
async def whatsapp_status(request: Request) -> Response | dict[str, str]:
    """Recibe eventos de Meta, los persiste en el chat y responde 200 (ACK) siempre."""
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

    if not isinstance(payload, dict):
        return {"status": "ok"}

    # El trabajo (BD + descarga de adjuntos) es SÍNCRONO y va al threadpool: hacerlo
    # inline bloquearía el event loop hasta 15 s por adjunto y frenaría toda la API.
    await run_in_threadpool(_procesar, payload)
    return {"status": "ok"}
