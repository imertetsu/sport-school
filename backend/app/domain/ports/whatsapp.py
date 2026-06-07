"""Puerto de WhatsApp (envío de plantillas pre-aprobadas) — epic WhatsApp Cobro.

El núcleo define esta interfaz; los adaptadores en `app.adapters.whatsapp` la
implementan (mock para tests/dev, Meta Cloud para producción). La selección del
adaptador se hace por configuración (`whatsapp_provider`), inyectada, no
hardcodeada.

Estructuras de dominio PURAS: solo `dataclasses`/`typing`. Este módulo NO importa
sqlalchemy, fastapi ni httpx (lo verifica import-linter). Respeta plantillas
pre-aprobadas y el costo por mensaje (RNF-07).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class WhatsAppImage:
    """Imagen de cabecera de una plantilla.

    Se provee como `data_url` (`data:image/png;base64,...`, p.ej. el QR de cobro) o
    como `link` HTTP público. El adaptador real decide cómo subir/referenciar el
    media; el dominio solo describe el contenido.
    """

    data_url: str | None = None
    link: str | None = None


@dataclass(frozen=True)
class WhatsAppTemplateMessage:
    """Mensaje de plantilla pre-aprobada a enviar.

    - `to`: número destino en formato E.164 (sin `+`, según proveedor).
    - `template_name`: nombre de la plantilla aprobada.
    - `lang_code`: código de idioma de la plantilla (p.ej. `es`, `es_BO`).
    - `body_params`: variables posicionales del cuerpo de la plantilla.
    - `header_image`: imagen de cabecera opcional (p.ej. QR de cobro).
    """

    to: str
    template_name: str
    lang_code: str
    body_params: list[str]
    header_image: WhatsAppImage | None = None


@dataclass(frozen=True)
class WhatsAppTextMessage:
    """Mensaje de texto libre (sesión de servicio al cliente abierta).

    - `to`: número destino en formato E.164 (sin `+`, según proveedor).
    - `body`: cuerpo del mensaje (texto plano, puede ser multilínea).

    Se usa para el detalle del digest de deudores (epic Recordatorio de deudores):
    tras la plantilla pre-aprobada `resumen_deudores`, se envía la lista de morosos
    como un único texto multilínea.
    """

    to: str
    body: str


@dataclass(frozen=True)
class WhatsAppSendResult:
    """Resultado de un envío.

    - `ok`: True si el proveedor aceptó el mensaje.
    - `provider_message_id`: id del proveedor (para auditoría/seguimiento).
    - `error`: descripción del fallo cuando `ok` es False.
    """

    ok: bool
    provider_message_id: str | None
    error: str | None = None


@runtime_checkable
class WhatsAppPort(Protocol):
    """Envía mensajes de plantilla pre-aprobada vía WhatsApp."""

    def send_template(self, msg: WhatsAppTemplateMessage) -> WhatsAppSendResult:
        """Envía `msg` y devuelve el resultado (no lanza; reporta vía `ok`/`error`)."""
        ...

    def send_text(self, msg: WhatsAppTextMessage) -> WhatsAppSendResult:
        """Envía un mensaje de texto libre (no lanza; reporta vía `ok`/`error`)."""
        ...
