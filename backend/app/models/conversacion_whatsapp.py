"""Modelo `conversacion_whatsapp` (epic chat-whatsapp) — un hilo por número.

Bandeja de entrada del número oficial: una fila por **(teléfono, escuela)**.

Hay **un hilo por (teléfono, escuela)**, no uno por teléfono. El tutor ve UNA sola
conversación en su celular —el número oficial es uno solo—, pero cada escuela ve la
suya: una madre con hijas en dos escuelas recibe mensajes de las dos, y ninguna lee lo
que la familia le escribió a la otra (migración 0033).

`org_id` es **NULLABLE** — la excepción a la regla del repo (`OrgScoped` es NOT NULL) y
la razón de ser de este epic: cuando escribe un número desconocido todavía NO se sabe a
qué escuela pertenece. Esa fila queda con `org_id IS NULL`, **invisible para toda
escuela** (la policy compara `org_id = <org actual>`, y `NULL = uuid` no es TRUE), y solo
la ve el superadmin, que conversa con la persona y luego la **asigna** a una escuela.

RLS (migración 0028) con DOS vías, ambas fail-closed:
  - escuela: `org_id = NULLIF(current_setting('app.current_org', true), '')::uuid`
  - consola/webhook: GUC propio `app.whatsapp_inbox = 'ALL'`
El GUC de la consola abre SOLO estas dos tablas (`conversacion_whatsapp`,
`mensaje_whatsapp`); el resto del esquema tenant sigue cerrado para el superadmin.

Constraints A MANO en la migración (patrón del repo): los dos únicos son PARCIALES
(uno por escuela, otro para el hilo sin clasificar), y esos no van declarativos.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPkMixin


class ConversacionWhatsApp(UUIDPkMixin, TimestampMixin, Base):
    __tablename__ = "conversacion_whatsapp"

    # NULL = número aún sin clasificar: solo visible en la consola de plataforma.
    org_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizacion.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )

    # E.164 sin `+` (normalizado con `normalize_bo_phone`). UNIQUE global: un número,
    # un hilo — como en la app de WhatsApp.
    telefono: Mapped[str] = mapped_column(String, nullable=False)
    # Nombre de perfil que manda Meta en `contacts[].profile.name` (puede faltar).
    nombre_contacto: Mapped[str | None] = mapped_column(String, nullable=True)

    # Orden y preview de la bandeja (se recalculan en cada mensaje).
    ultimo_mensaje_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ultimo_mensaje_texto: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Último mensaje ENTRANTE: de aquí sale la ventana de 24 h de Meta (fuera de ella
    # el texto libre no llega, hace falta plantilla aprobada). Se guarda el instante,
    # no el vencimiento, para que la ventana se recalcule sola si cambia la regla.
    ultimo_entrante_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Badge de no leídos: sube con cada entrante, se limpia al abrir el hilo.
    no_leidos: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0"), default=0
    )

    # La unicidad es por (telefono, escuela) y NO por telefono a secas: una madre puede
    # tener hijas en dos escuelas, y cada una necesita su propio hilo con ella (ver
    # migración 0033). Son dos índices PARCIALES, así que viven solo en la migración.
    __table_args__ = ()
