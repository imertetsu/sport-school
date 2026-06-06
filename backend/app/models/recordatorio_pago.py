"""Modelo `recordatorio_pago` (C1) — registro de recordatorios de cobro enviados.

Tabla tenant con RLS por `org_id`. Cada fila es un recordatorio de una cuota
enviado a un tutor por un canal (WhatsApp). La **idempotencia** la garantiza
`UNIQUE(cuota_id, tipo, ciclo)`: el cron diario re-ejecutado NO debe reenviar el
mismo recordatorio (mismo tipo y mismo ciclo) para la misma cuota.

Columnas EXACTAS a `migrations/versions/0011_*.py` (autoridad del esquema físico,
db-dev). Es **contrato compartido** backend->db: si una columna cambia tras
empezar, handoff y parar (no driftear el esquema en un solo lado). NO lleva
`created_at`/`updated_at`; el sello es `enviado_en` (timestamptz now()), por eso
NO hereda `TimestampMixin`.
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


class RecordatorioPago(UUIDPkMixin, OrgScoped, Base):
    __tablename__ = "recordatorio_pago"

    cuota_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("cuota.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tutor_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tutor.id", ondelete="SET NULL"),
        nullable=True,
    )
    tipo: Mapped[str] = mapped_column(Text, nullable=False)  # PROXIMO_VENCIMIENTO | MOROSIDAD
    canal: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'WHATSAPP'"), default="WHATSAPP"
    )  # WHATSAPP
    ciclo: Mapped[str] = mapped_column(Text, nullable=False)
    destino: Mapped[str | None] = mapped_column(Text, nullable=True)
    qr_ref: Mapped[str | None] = mapped_column(Text, nullable=True)
    provider_message_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    estado: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'ENVIADO'"), default="ENVIADO"
    )  # ENVIADO | FALLIDO
    enviado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("cuota_id", "tipo", "ciclo", name="uq_recordatorio_cuota_tipo_ciclo"),
        Index("ix_recordatorio_org_cuota", "org_id", "cuota_id"),
        CheckConstraint("tipo IN ('PROXIMO_VENCIMIENTO','MOROSIDAD')", name="ck_recordatorio_tipo"),
        CheckConstraint("estado IN ('ENVIADO','FALLIDO')", name="ck_recordatorio_estado"),
    )
