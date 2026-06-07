"""Adaptador WhatsApp **mock** — implementa `WhatsAppPort` para dev/tests.

No envía nada real: acumula los mensajes en `self.sent` para inspección en tests
(es el sujeto de los tests de idempotencia: un recordatorio duplicado NO debe
producir un segundo envío). Devuelve siempre un id de mensaje único simulado.
"""

from __future__ import annotations

from uuid import uuid4

from app.domain.ports.whatsapp import (
    WhatsAppPort,
    WhatsAppSendResult,
    WhatsAppTemplateMessage,
    WhatsAppTextMessage,
)


class MockWhatsAppAdapter(WhatsAppPort):
    """Acumula mensajes en memoria; no llama a ningún proveedor."""

    def __init__(self) -> None:
        self.sent: list[WhatsAppTemplateMessage] = []
        # Lista SEPARADA para los textos libres (epic Recordatorio de deudores): los
        # tests de idempotencia verifican que ni `sent` ni `sent_text` crecen al
        # re-enviar el mismo período.
        self.sent_text: list[WhatsAppTextMessage] = []

    def send_template(self, msg: WhatsAppTemplateMessage) -> WhatsAppSendResult:
        """Registra `msg` y simula un envío exitoso con id único."""
        self.sent.append(msg)
        return WhatsAppSendResult(ok=True, provider_message_id=f"mock_{uuid4().hex}")

    def send_text(self, msg: WhatsAppTextMessage) -> WhatsAppSendResult:
        """Registra `msg` (texto libre) y simula un envío exitoso con id único."""
        self.sent_text.append(msg)
        return WhatsAppSendResult(ok=True, provider_message_id=f"mock_{uuid4().hex}")
