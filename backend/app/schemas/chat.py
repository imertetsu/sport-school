"""Schemas del chat de WhatsApp (epic chat-whatsapp).

Las MISMAS formas sirven a las dos consolas (escuela y plataforma): el hilo se ve
igual en ambas, lo que cambia es el alcance. Los campos propios de la consola de
plataforma (`org_id`, `org_nombre`) viajan siempre; en la escuela son redundantes
(siempre su propia escuela) pero no revelan nada que no sepa.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, field_validator

# Tope del texto que se puede mandar en una respuesta. WhatsApp corta el cuerpo en
# 4096 caracteres; rechazar antes evita mandar un mensaje truncado sin avisar.
MAX_TEXTO = 4096


# --------------------------------------------------------------------------- #
# Bandeja
# --------------------------------------------------------------------------- #
class ConversacionItem(BaseModel):
    """Una fila de la bandeja (lista de chats)."""

    id: uuid.UUID
    telefono: str
    nombre_contacto: str | None
    # `None` = número aún sin clasificar. En la escuela nunca llega uno así (RLS);
    # en la consola de plataforma es justo la cola de trabajo.
    org_id: uuid.UUID | None
    org_nombre: str | None
    ultimo_mensaje_at: datetime
    ultimo_mensaje_texto: str | None
    no_leidos: int
    # ¿Se puede responder texto libre? (24 h desde el último mensaje del contacto).
    ventana_abierta: bool
    # ¿Se puede escribir aunque la ventana esté cerrada? True cuando el hilo pertenece a
    # una escuela, porque entonces el mensaje sale como plantilla `contacto_escuela`.
    # Falso solo en los hilos sin clasificar de la consola: no hay escuela que poner en
    # la plantilla, así que hasta asignarlos solo se les puede contestar dentro de 24 h.
    puede_iniciar: bool


class ConversacionesPage(BaseModel):
    """Una página de la bandeja + el total de no leídos para el badge del menú.

    `no_leidos_total` NO es de la página: es de todo lo visible, porque el badge cuenta
    lo que hay pendiente, no lo que entró en la primera pantalla.
    """

    items: list[ConversacionItem]
    no_leidos_total: int
    # Cursor de la página siguiente: se devuelven los valores del ÚLTIMO item para que
    # el cliente los reenvíe tal cual. `hay_mas=False` ⇒ no hay nada más que pedir.
    hay_mas: bool = False
    cursor_at: datetime | None = None
    cursor_id: uuid.UUID | None = None


# --------------------------------------------------------------------------- #
# Hilo
# --------------------------------------------------------------------------- #
class MensajeItem(BaseModel):
    """Una burbuja del hilo."""

    id: uuid.UUID
    direccion: str  # IN (el tutor) | OUT (nosotros)
    tipo: str  # TEXTO | IMAGEN | DOCUMENTO | AUDIO | PLANTILLA | OTRO
    texto: str | None
    # True si la burbuja lleva adjunto: el binario se pide aparte
    # (`GET .../mensajes/{id}/media`) para no inflar el JSON del hilo con base64.
    tiene_media: bool
    media_mime: str | None
    # Nombre original del archivo (`comprobante-agosto.pdf`). Es lo que se muestra en
    # la burbuja de un documento: "Documento" a secas no distingue uno de otro.
    media_nombre: str | None = None
    estado: str | None  # solo OUT: ENVIADO | ENTREGADO | LEIDO | FALLIDO
    error_detalle: str | None
    enviado_por_nombre: str | None
    ocurrido_en: datetime


class HiloOut(BaseModel):
    """Conversación abierta: su cabecera + los mensajes."""

    conversacion: ConversacionItem
    mensajes: list[MensajeItem]


# --------------------------------------------------------------------------- #
# Envío
# --------------------------------------------------------------------------- #
class EnviarMensajeIn(BaseModel):
    """Body de `POST .../conversaciones/{id}/mensajes`."""

    texto: str

    @field_validator("texto")
    @classmethod
    def _texto_valido(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("El mensaje no puede estar vacío")
        if len(v) > MAX_TEXTO:
            raise ValueError(f"El mensaje no puede superar {MAX_TEXTO} caracteres")
        return v


class EnviarMensajeOut(BaseModel):
    """Resultado del envío.

    `enviado=False` con `motivo="ventana_expirada"` NO es un error del sistema: es que
    pasaron más de 24 h desde el último mensaje del contacto y Meta ya no admite texto
    libre. La UI lo muestra como aviso, no como fallo.
    """

    enviado: bool
    motivo: str
    detalle: str | None = None
    mensaje: MensajeItem | None = None


# --------------------------------------------------------------------------- #
# Agenda de tutores (solo consola de escuela)
# --------------------------------------------------------------------------- #
class TutorContactableItem(BaseModel):
    """Un tutor de la escuela al que se le puede escribir.

    `deportistas` es lo que hace usable la lista: en la escuela no se busca por el
    nombre del tutor, se busca "la mamá de Alexia".
    """

    tutor_id: uuid.UUID
    nombres: str
    telefono: str
    deportistas: list[str]
    # Hilo ya abierto con ese número, si lo hay: la UI lo abre en vez de crear otro.
    conversacion_id: uuid.UUID | None


class AbrirConversacionIn(BaseModel):
    """Body de `POST /whatsapp/conversaciones/abrir`.

    Se manda el TELÉFONO y no el `tutor_id` porque el hilo es del número, no de la
    persona: dos tutores con el mismo teléfono comparten conversación, igual que en la
    app de WhatsApp.
    """

    telefono: str

    @field_validator("telefono")
    @classmethod
    def _no_vacio(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("El teléfono no puede estar vacío")
        return v


# --------------------------------------------------------------------------- #
# Asignación de escuela (solo consola de plataforma)
# --------------------------------------------------------------------------- #
class AsignarEscuelaIn(BaseModel):
    """Body de `POST /plataforma/whatsapp/conversaciones/{id}/asignar`.

    `org_id = null` desasigna (devuelve el hilo a la cola de sin clasificar), que es
    la salida si se categorizó mal.
    """

    org_id: uuid.UUID | None = None
