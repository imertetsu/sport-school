"""Puerto de notificaciones (WhatsApp real en fase posterior; Noop en dev).

El núcleo define la interfaz; los adaptadores la implementan. Respeta plantillas
pre-aprobadas, el costo por mensaje y los toggles por organización (RNF-07).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class NotificationService(Protocol):
    """Envía notificaciones a tutores/usuarios según plantillas pre-aprobadas."""

    def send(self, *, to: str, template: str, variables: dict[str, str]) -> None:
        """Envía un mensaje renderizando `template` con `variables`.

        TODO(epic-notificaciones): el adaptador real debe respetar toggles por
        organización, contabilizar el costo del mensaje y usar plantillas
        pre-aprobadas.
        """
        ...
