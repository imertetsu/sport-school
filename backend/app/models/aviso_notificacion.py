"""Modelo `aviso_notificacion` (epic avisos-whatsapp, C1) — log/idempotencia del envío.

Tabla tenant con RLS por `org_id`. Cada fila registra el intento de notificar por
WhatsApp a UN destinatario (entrenador o tutor) sobre UN aviso. La **idempotencia** la
garantiza `UNIQUE(aviso_id, tipo_destinatario, destinatario_id)`: reencolar/reejecutar
el envío del mismo aviso NO produce doble envío ni doble fila. El INSERT usa
`ON CONFLICT DO NOTHING` (mismo patrón que `recordatorio_deudores`).

`estado`:
- `ENVIADO`: se envió la plantilla `nuevo_aviso` (con `provider_message_id`/`enviado_en`).
- `SIN_TELEFONO`: el destinatario no tenía teléfono; NO se llamó al puerto (`destino` NULL).
- `FALLIDO`: tenía teléfono pero el proveedor rechazó el envío (`error` con el detalle).

Columnas EXACTAS a `migrations/versions/0021_*.py` (autoridad del esquema físico,
db-dev). Es **contrato compartido** backend↔db: si una columna cambia tras empezar,
handoff y parar. NO lleva `updated_at`; los sellos son `created_at` (timestamptz now())
y `enviado_en`, por eso NO hereda `TimestampMixin` (igual que `recordatorio_deudores`).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, OrgScoped, UUIDPkMixin


class AvisoNotificacion(UUIDPkMixin, OrgScoped, Base):
    __tablename__ = "aviso_notificacion"

    aviso_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("aviso.id", ondelete="CASCADE"),
        nullable=False,
    )
    tipo_destinatario: Mapped[str] = mapped_column(Text, nullable=False)  # ENTRENADOR | TUTOR
    # id del entrenador o tutor; sin FK polimórfico (no se referencia una tabla concreta).
    destinatario_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    canal: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'WHATSAPP'"), default="WHATSAPP"
    )  # WHATSAPP
    # teléfono (NULL si SIN_TELEFONO)
    destino: Mapped[str | None] = mapped_column(Text, nullable=True)
    estado: Mapped[str] = mapped_column(Text, nullable=False)  # ENVIADO | FALLIDO | SIN_TELEFONO
    provider_message_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    enviado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        UniqueConstraint(
            "aviso_id",
            "tipo_destinatario",
            "destinatario_id",
            name="uq_aviso_notificacion_destinatario",
        ),
        Index("ix_aviso_notificacion_org_aviso", "org_id", "aviso_id"),
        CheckConstraint(
            "tipo_destinatario IN ('ENTRENADOR','TUTOR')",
            name="ck_aviso_notificacion_tipo_destinatario",
        ),
        CheckConstraint(
            "estado IN ('ENVIADO','FALLIDO','SIN_TELEFONO')",
            name="ck_aviso_notificacion_estado",
        ),
    )
