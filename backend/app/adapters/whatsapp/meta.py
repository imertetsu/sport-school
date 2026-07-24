"""Adaptador WhatsApp **Meta Cloud API** — implementa `WhatsAppPort`.

Esqueleto para producción: envía mensajes de plantilla pre-aprobada vía la Graph
API de Meta. No se ejercita en tests (requiere credenciales reales); la cobertura
de idempotencia vive sobre `MockWhatsAppAdapter`.

Config (C7, inyectada vía `settings`): `whatsapp_graph_version`,
`whatsapp_phone_number_id`, `whatsapp_access_token`.
"""

from __future__ import annotations

import base64
from typing import Any

import httpx

from app.core.config import settings
from app.core.phone import normalize_bo_phone
from app.domain.ports.whatsapp import (
    WhatsAppImage,
    WhatsAppImageMessage,
    WhatsAppPort,
    WhatsAppSendResult,
    WhatsAppTemplateMessage,
    WhatsAppTextMessage,
)

_TIMEOUT_SECONDS = 15.0
_MIME_POR_DEFECTO = "image/png"


def _partir_data_url(data_url: str) -> tuple[str, str]:
    """Separa `data:image/png;base64,XXXX` en `(base64, mime)`.

    Acepta también un base64 "pelado" (sin prefijo `data:`), que es como viaja el QR de
    cobro por el puerto; en ese caso asume PNG.
    """
    if not data_url.startswith("data:"):
        return data_url, _MIME_POR_DEFECTO
    cabecera, _, b64 = data_url.partition(",")
    mime = cabecera[len("data:") :].split(";")[0] or _MIME_POR_DEFECTO
    return b64, mime


class MetaCloudWhatsAppAdapter(WhatsAppPort):
    """Cliente de la Cloud API de WhatsApp (Meta Graph)."""

    def _post(self, body: dict[str, Any]) -> WhatsAppSendResult:
        """POST `/messages` con `body` ya armado. No lanza: reporta vía `ok`/`error`.

        Normaliza el destinatario a E.164-sin-`+` (lo que exige Meta) en este punto
        único: los servicios guardan el teléfono "humano" (`+591 76123456`, etc.) en
        sus registros y solo aquí se formatea para la red. Si el número no es
        plausible, se reporta `ok=False` **sin** llamar a la Graph API.
        """
        raw_to = body.get("to")
        normalized_to = normalize_bo_phone(raw_to if isinstance(raw_to, str) else None)
        if normalized_to is None:
            return WhatsAppSendResult(
                ok=False,
                provider_message_id=None,
                error=f"teléfono inválido: {raw_to}",
            )
        body = {**body, "to": normalized_to}

        url = (
            f"https://graph.facebook.com/{settings.whatsapp_graph_version}"
            f"/{settings.whatsapp_phone_number_id}/messages"
        )
        headers = {
            "Authorization": f"Bearer {settings.whatsapp_access_token}",
            "Content-Type": "application/json",
        }
        try:
            resp = httpx.post(url, headers=headers, json=body, timeout=_TIMEOUT_SECONDS)
            resp.raise_for_status()
            data = resp.json()
            messages = data.get("messages") or []
            provider_message_id = messages[0].get("id") if messages else None
            return WhatsAppSendResult(ok=True, provider_message_id=provider_message_id)
        except httpx.HTTPStatusError as exc:
            return WhatsAppSendResult(
                ok=False,
                provider_message_id=None,
                error=f"http {exc.response.status_code}: {exc.response.text}",
            )
        except Exception as exc:  # noqa: BLE001 - el puerto reporta el fallo, no lanza
            return WhatsAppSendResult(ok=False, provider_message_id=None, error=str(exc))

    def _subir_media(self, image_b64: str, mime: str) -> tuple[str | None, str | None]:
        """Sube una imagen a Meta y devuelve `(media_id, error)`. No lanza.

        Meta NO acepta base64 inline (ni en `type=image` ni en la cabecera de plantilla):
        hay que subir el binario a `POST /{phone_number_id}/media` (multipart) y luego
        referenciar el `media_id` devuelto.
        """
        try:
            binario = base64.b64decode(image_b64)
        except Exception as exc:  # noqa: BLE001 - base64 inválido: se reporta, no rompe
            return None, f"imagen base64 inválida: {exc}"

        url = (
            f"https://graph.facebook.com/{settings.whatsapp_graph_version}"
            f"/{settings.whatsapp_phone_number_id}/media"
        )
        headers = {"Authorization": f"Bearer {settings.whatsapp_access_token}"}
        try:
            resp = httpx.post(
                url,
                headers=headers,
                data={"messaging_product": "whatsapp", "type": mime},
                files={"file": ("imagen", binario, mime)},
                timeout=_TIMEOUT_SECONDS,
            )
            resp.raise_for_status()
            media_id = (resp.json() or {}).get("id")
            if not media_id:
                return None, "Meta no devolvió media_id"
            return str(media_id), None
        except httpx.HTTPStatusError as exc:
            return None, f"http {exc.response.status_code}: {exc.response.text}"
        except Exception as exc:  # noqa: BLE001 - el puerto reporta el fallo, no lanza
            return None, str(exc)

    def _componente_cabecera(self, imagen: WhatsAppImage) -> dict[str, Any] | None:
        """Componente `header` con imagen para una plantilla, o `None` si no se pudo.

        Un `link` HTTP público lo acepta Meta tal cual; un `data_url`/base64 (el QR de
        cobro) hay que subirlo primero y referenciar su `media_id`.
        """
        if imagen.link:
            referencia: dict[str, Any] = {"link": imagen.link}
        elif imagen.data_url:
            b64, mime = _partir_data_url(imagen.data_url)
            media_id, _error = self._subir_media(b64, mime)
            if media_id is None:
                return None
            referencia = {"id": media_id}
        else:
            return None
        return {"type": "header", "parameters": [{"type": "image", "image": referencia}]}

    def send_image(self, msg: WhatsAppImageMessage) -> WhatsAppSendResult:
        """Envía una imagen con caption: sube el media y manda `type=image` con su id.

        El caption vacío NO se envía (Meta rechaza `caption: ""`).
        """
        media_id, error = self._subir_media(msg.image_b64, msg.mime)
        if media_id is None:
            return WhatsAppSendResult(ok=False, provider_message_id=None, error=error)

        imagen: dict[str, Any] = {"id": media_id}
        if msg.caption:
            imagen["caption"] = msg.caption
        body: dict[str, Any] = {
            "messaging_product": "whatsapp",
            "to": msg.to,
            "type": "image",
            "image": imagen,
        }
        return self._post(body)

    def send_text(self, msg: WhatsAppTextMessage) -> WhatsAppSendResult:
        """Envía un mensaje de texto libre vía Graph API (esqueleto; no en tests)."""
        body: dict[str, Any] = {
            "messaging_product": "whatsapp",
            "to": msg.to,
            "type": "text",
            "text": {"body": msg.body},
        }
        return self._post(body)

    def send_template(self, msg: WhatsAppTemplateMessage) -> WhatsAppSendResult:
        """Envía una plantilla vía Graph API. No lanza: reporta vía `ok`/`error`."""
        components: list[dict[str, Any]] = []
        if msg.header_image is not None:
            # El QR de cobro llega como data_url/base64: se sube a `/media` y se
            # referencia por `media_id` (un `link` público va tal cual). Si la subida
            # falla se OMITE la cabecera para no perder el cuerpo del mensaje.
            cabecera = self._componente_cabecera(msg.header_image)
            if cabecera is not None:
                components.append(cabecera)
        if msg.body_params:
            components.append(
                {
                    "type": "body",
                    "parameters": [{"type": "text", "text": param} for param in msg.body_params],
                }
            )

        body: dict[str, Any] = {
            "messaging_product": "whatsapp",
            "to": msg.to,
            "type": "template",
            "template": {
                "name": msg.template_name,
                "language": {"code": msg.lang_code},
                "components": components,
            },
        }
        return self._post(body)
