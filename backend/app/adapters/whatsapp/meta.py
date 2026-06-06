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
from app.domain.ports.whatsapp import (
    WhatsAppPort,
    WhatsAppSendResult,
    WhatsAppTemplateMessage,
)

_TIMEOUT_SECONDS = 15.0


class MetaCloudWhatsAppAdapter(WhatsAppPort):
    """Cliente de la Cloud API de WhatsApp (Meta Graph)."""

    def send_template(self, msg: WhatsAppTemplateMessage) -> WhatsAppSendResult:
        """Envía una plantilla vía Graph API. No lanza: reporta vía `ok`/`error`."""
        url = (
            f"https://graph.facebook.com/{settings.whatsapp_graph_version}"
            f"/{settings.whatsapp_phone_number_id}/messages"
        )
        headers = {
            "Authorization": f"Bearer {settings.whatsapp_access_token}",
            "Content-Type": "application/json",
        }

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
