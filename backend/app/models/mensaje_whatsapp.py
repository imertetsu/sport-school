"""Modelo `mensaje_whatsapp` (epic chat-whatsapp) — un mensaje del hilo.

Cada fila es una burbuja del chat: entrante (`IN`, lo escribió el tutor) o saliente
(`OUT`, lo mandó la escuela o el superadmin desde la consola).

`org_id` está **denormalizado** desde la conversación (y por eso es NULLABLE igual que
allí): es la columna de RLS, y sin ella el hilo de un número sin clasificar no podría
existir. Cuando el superadmin asigna la conversación a una escuela, el servicio propaga
el `org_id` a TODOS sus mensajes en la misma transacción — de otro modo la escuela vería
el hilo vacío.

`provider_message_id` es UNIQUE: es la idempotencia ante la re-entrega del webhook de
Meta (que reintenta si no recibe 200) y la clave por la que los eventos de estado
(`sent`/`delivered`/`read`/`failed`) encuentran su mensaje saliente.

Constraints que pone db-dev A MANO en la migración (patrón del repo: los CHECK enum-like
viven solo en la migración): `direccion IN ('IN','OUT')`, `tipo IN
('TEXTO','IMAGEN','PLANTILLA','OTRO')` y `estado IN
('ENVIADO','ENTREGADO','LEIDO','FALLIDO')`.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPkMixin


class MensajeWhatsApp(UUIDPkMixin, Base):
    __tablename__ = "mensaje_whatsapp"

    # Denormalizado de la conversación (columna de RLS). NULL mientras el número
    # no esté asignado a ninguna escuela.
    org_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizacion.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    conversacion_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("conversacion_whatsapp.id", ondelete="CASCADE"),
        nullable=False,
    )

    # IN = lo escribió el tutor · OUT = lo mandó la escuela/consola. CHECK en la migración.
    direccion: Mapped[str] = mapped_column(String, nullable=False)
    # TEXTO | IMAGEN | PLANTILLA | OTRO (audio/video/sticker/ubicación: se registra
    # la burbuja sin el contenido, para que el hilo no tenga huecos).
    tipo: Mapped[str] = mapped_column(String, nullable=False)

    texto: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Imagen propia del mensaje como bytea (mismo criterio que `comprobante_pendiente`),
    # servida por endpoint propio. La llevan las ENTRANTES y el recibo del comprobante
    # (único por pago: ahí la fidelidad vale más que el espacio). NULL en los de texto.
    media: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    media_mime: Mapped[str | None] = mapped_column(String, nullable=True)
    # Imagen que vive en OTRA tabla y no se copia aquí. Hoy solo `'qr'`: el QR de cobro
    # de la escuela, el mismo en todos sus recordatorios — duplicarlo por mensaje serían
    # megabytes de copias idénticas (ver migración 0030).
    media_ref: Mapped[str | None] = mapped_column(String, nullable=True)

    # Id de Meta: idempotencia del webhook + clave de los eventos de estado.
    provider_message_id: Mapped[str | None] = mapped_column(String, nullable=True)

    # Solo en OUT: ENVIADO -> ENTREGADO -> LEIDO, o FALLIDO con su motivo. CHECK en
    # la migración. NULL en los entrantes.
    estado: Mapped[str | None] = mapped_column(String, nullable=True)
    error_detalle: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Quién lo mandó, como texto para mostrar en la burbuja ("Ana (escuela)",
    # "Consola"). Texto y no FK a `usuario`: `usuario` es tabla tenant y el superadmin
    # opera SIN contexto de org, así que una FK ahí no se podría ni leer ni validar.
    enviado_por_nombre: Mapped[str | None] = mapped_column(String, nullable=True)

    # Instante real del mensaje (el `timestamp` de Meta en los entrantes; `now()` en
    # los salientes). Es el que ordena el hilo, no `created_at`: el webhook puede
    # llegar tarde o desordenado.
    ocurrido_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("provider_message_id", name="uq_mensaje_whatsapp_provider"),
        Index("ix_mensaje_whatsapp_conversacion", "conversacion_id", "ocurrido_en"),
    )
