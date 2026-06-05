"""Adaptador de notificaciones no-op (para dev/tests).

Implementa el puerto `NotificationService` sin enviar nada real: solo registra a
nivel debug. Útil mientras el adaptador de WhatsApp no existe.
"""

from __future__ import annotations

import logging

from app.domain.ports.notification import NotificationService

logger = logging.getLogger(__name__)


class NoopNotificationService(NotificationService):
    """No envía nada; deja traza en debug. Cumple el puerto en entornos sin proveedor."""

    def send(self, *, to: str, template: str, variables: dict[str, str]) -> None:
        # No loguear datos sensibles en claro (RNF-03): solo metadata.
        logger.debug(
            "Noop notification: template=%s to=%s vars=%s",
            template,
            to,
            sorted(variables.keys()),
        )
