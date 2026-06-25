"""Adaptador WhatsApp **Meta Cloud API** — implementa `WhatsAppPort`.

Esqueleto para producción: envía mensajes de plantilla pre-aprobada vía la Graph
API de Meta. No se ejercita en tests (requiere credenciales reales); la cobertura
de idempotencia vive sobre `MockWhatsAppAdapter`.

Config (C7, inyectada vía `settings`): `whatsapp_graph_version`,
`whatsapp_phone_number_id`, `whatsapp_access_token`.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.core.config import settings
from app.core.phone import normalize_bo_phone
from app.domain.ports.whatsapp import (
    WhatsAppPort,
    WhatsAppSendResult,
    WhatsAppTemplateMessage,
    WhatsAppTextMessage,
)

_TIMEOUT_SECONDS = 15.0


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
            # TODO(epic-whatsapp): para cabecera con imagen, Meta requiere subir el
            # media a `POST /{phone_number_id}/media` y referenciar el `media_id`
            # devuelto (o pasar un `link` HTTP público). El QR de cobro llega como
            # `data_url` base64, que NO es aceptado directamente por la plantilla:
            # hay que subirlo primero. Fuera de alcance del MVP; se omite la
            # cabecera para no romper el envío del cuerpo.
            pass
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
