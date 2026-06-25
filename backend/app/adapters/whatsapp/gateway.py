"""Adaptador WhatsApp **Gateway no-oficial** (sidecar Baileys) — implementa `WhatsAppPort`.

Epic whatsapp-gateway: enviar mensajes REALES desde un número de prueba **ya**, sin
esperar la verificación de negocio + plantillas aprobadas de Meta Cloud API. El sidecar
Node (lo posee infra-dev, vive en `infra/whatsapp-gateway/`) mantiene la sesión del
número (pairing por QR) y expone `POST /send`. Este adaptador lo consume.

Multi-tenant (epic whatsapp-multitenant): el sidecar es **multi-sesión** (un número por
escuela). La organización en curso se resuelve por `ContextVar` (`app.core.org_context`,
fijado en el mismo punto que el GUC `app.current_org`) y se inyecta en la URL por-org,
**sin** cambiar la firma de `WhatsAppPort`. Sin contexto de org ⇒ `ok=False` **sin** pegar
al sidecar (fail-closed; invariante anti-fuga del `ContextVar` entre orgs consecutivas).

Contrato del sidecar (sección A de la spec):
- `POST {gateway_url}/sessions/{org_id}/send` con header `X-Gateway-Token: {gateway_token}`
  y body `{"to": "<dígitos E.164 sin +>", "text": "<string, puede ser multilínea>"}`.
- Respuesta **200** `{"ok": true, "message_id": "<id>"}` o **200**
  `{"ok": false, "error": "<msg legible>"}`. Los errores de negocio (número inválido,
  no conectado) llegan como `ok:false` (nunca 5xx) ⇒ se mapean a
  `WhatsAppSendResult(ok=False, error=...)`.

A diferencia de Meta, el no-oficial **NO** tiene plantillas aprobadas: el texto lo
ponemos nosotros desde un dict local (`_TEMPLATES`), rellenado con los `body_params`
posicionales que ya pasan los 4 servicios (orden EXACTO, sección D de la spec). Como el
canal libre se entrega siempre y admite saltos de línea, el texto es multilínea-friendly.
`header_image` se ignora (igual que en `meta.py`). El destino se normaliza con el helper
EXISTENTE `app.core.phone.normalize_bo_phone` (no se duplica): número no plausible ⇒
`ok=False` **sin** pegar al sidecar.

No lanza: reporta cualquier fallo (red, sidecar caído, plantilla desconocida) vía
`ok`/`error`. La fábrica (`app.services.deps.get_whatsapp_port`) lo selecciona con
`whatsapp_provider == "gateway"` + url/token presentes; si no, degrada a mock.
"""

from __future__ import annotations

from typing import Any

import httpx

from app.core.config import settings
from app.core.org_context import get_current_org_id
from app.core.phone import normalize_bo_phone
from app.domain.ports.whatsapp import (
    WhatsAppPort,
    WhatsAppSendResult,
    WhatsAppTemplateMessage,
    WhatsAppTextMessage,
)

_TIMEOUT_SECONDS = 15.0

# Plantillas de TEXTO del gateway no-oficial (sección D de la spec). Clave =
# `template_name` que ya pasan los servicios; `{{n}}` = `body_params` posicionales en
# el ORDEN EXACTO que esos servicios producen. NO se tocan los servicios: el contrato
# lo garantiza este dict. El no-oficial permite multilínea (a diferencia de Meta).
_TEMPLATES: dict[str, str] = {
    # {{1}} deportista · {{2}} monto ("Bs X.XX") · {{3}} escuela · {{4}} vence · {{5}} enlace
    "recordatorio_cuota_qr": (
        "Hola, recordatorio de cuota de {{1}} en {{3}}: {{2}}, vence el {{4}}. Pague aquí: {{5}}"
    ),
    # mismos 5 (deportista, monto, escuela, vence, enlace)
    "morosidad_cuota_qr": (
        "La cuota de {{1}} en {{3}} está vencida: {{2}} (venció el {{4}}). Regularice aquí: {{5}}"
    ),
    # {{1}} deportista · {{2}} monto · {{3}} escuela · {{4}} N° recibo · {{5}} enlace PDF
    "recibo_pago": (
        "Pago recibido de {{1}} en {{3}}: {{2}}. Recibo {{4}}. Descárguelo aquí: {{5}}"
    ),
    # {{1}} entrenador · {{2}} sucursal · {{3}} nº deudores · {{4}} monto total
    "resumen_deudores": (
        "Hola {{1}}, resumen de deudores en {{2}}: {{3}} deportistas, "
        "total Bs {{4}}. Detalle a continuación."
    ),
    # {{1}} escuela · {{2}} título · {{3}} cuerpo
    "nuevo_aviso": "{{1}} informa: {{2}}. {{3}}",
}


def _render(template_name: str, body_params: list[str]) -> str | None:
    """Renderiza la plantilla `template_name` con `body_params` posicionales.

    Devuelve el texto con cada `{{n}}` (1-based) sustituido por su parámetro; `None`
    si la plantilla no está registrada (defensivo: el contrato la garantiza, pero un
    `template_name` desconocido NO debe reventar el envío).
    """
    template = _TEMPLATES.get(template_name)
    if template is None:
        return None
    rendered = template
    for index, value in enumerate(body_params, start=1):
        rendered = rendered.replace("{{" + str(index) + "}}", value)
    return rendered


class GatewayWhatsAppAdapter(WhatsAppPort):
    """Cliente del sidecar no-oficial (Baileys) vía `POST /send`."""

    def _send(self, to: str, text: str) -> WhatsAppSendResult:
        """`POST {gateway_url}/sessions/{org_id}/send`. No lanza: mapea a `ok`/`error`.

        Resuelve la organización en curso desde el `ContextVar`
        (`app.core.org_context`): el sidecar es **multi-sesión** (un número por
        escuela) y la org se inyecta por contexto, **sin** cambiar la firma del puerto.
        Si no hay contexto de org (p.ej. una task que no fijó `app.current_org`), se
        reporta `ok=False` **sin** pegar al sidecar (fail-closed, invariante anti-fuga).

        Normaliza el destinatario a E.164-sin-`+` (lo que espera el sidecar) en este
        punto único; si el número no es plausible, reporta `ok=False` **sin** llamar al
        sidecar (mismo guard que `meta.py`).
        """
        org_id = get_current_org_id()
        if not org_id:
            return WhatsAppSendResult(
                ok=False,
                provider_message_id=None,
                error="sin contexto de organización",
            )

        normalized_to = normalize_bo_phone(to)
        if normalized_to is None:
            return WhatsAppSendResult(
                ok=False,
                provider_message_id=None,
                error=f"teléfono inválido: {to}",
            )

        url = f"{(settings.whatsapp_gateway_url or '').rstrip('/')}/sessions/{org_id}/send"
        headers = {
            "X-Gateway-Token": settings.whatsapp_gateway_token or "",
            "Content-Type": "application/json",
        }
        body: dict[str, Any] = {"to": normalized_to, "text": text}
        try:
            resp = httpx.post(url, headers=headers, json=body, timeout=_TIMEOUT_SECONDS)
            resp.raise_for_status()
            data = resp.json()
            if data.get("ok"):
                message_id = data.get("message_id")
                return WhatsAppSendResult(
                    ok=True,
                    provider_message_id=str(message_id) if message_id is not None else None,
                )
            # Error de negocio del sidecar (200 ok:false): número no conectado, etc.
            return WhatsAppSendResult(
                ok=False,
                provider_message_id=None,
                error=str(data.get("error") or "gateway reportó ok:false"),
            )
        except httpx.HTTPStatusError as exc:
            return WhatsAppSendResult(
                ok=False,
                provider_message_id=None,
                error=f"http {exc.response.status_code}: {exc.response.text}",
            )
        except Exception as exc:  # noqa: BLE001 - el puerto reporta el fallo, no lanza
            return WhatsAppSendResult(ok=False, provider_message_id=None, error=str(exc))

    def send_text(self, msg: WhatsAppTextMessage) -> WhatsAppSendResult:
        """Envía un texto libre por el sidecar. No lanza: reporta vía `ok`/`error`."""
        return self._send(msg.to, msg.body)

    def send_template(self, msg: WhatsAppTemplateMessage) -> WhatsAppSendResult:
        """Renderiza la plantilla de texto local y la envía por el sidecar.

        El no-oficial no tiene plantillas aprobadas: el texto sale del dict `_TEMPLATES`
        (sección D), rellenado con `msg.body_params` posicionales. `header_image` se
        ignora (igual que en `meta.py`). Plantilla desconocida ⇒ `ok=False` (defensivo)
        sin pegar al sidecar.
        """
        text = _render(msg.template_name, msg.body_params)
        if text is None:
            return WhatsAppSendResult(
                ok=False,
                provider_message_id=None,
                error=f"plantilla desconocida: {msg.template_name}",
            )
        return self._send(msg.to, text)
