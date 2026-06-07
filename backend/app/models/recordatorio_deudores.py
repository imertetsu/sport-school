"""Modelo `recordatorio_deudores` (epic Recordatorio de deudores) — control/idempotencia.

Tabla tenant con RLS por `org_id`. Cada fila registra el digest de deudores enviado a
un entrenador para una sucursal en un período (semana ISO del cron o `MANUAL-<ts>` a
demanda). La **idempotencia** la garantiza `UNIQUE(entrenador_id, sucursal_id, periodo)`:
re-correr el cron el mismo período NO reenvía el digest. El INSERT usa
`ON CONFLICT DO NOTHING` (mismo patrón que `recordatorio_pago`).

`estado`:
- `ENVIADO`: se enviaron los mensajes (plantilla + detalle).
- `SIN_DEUDORES`: la sucursal no tenía deudores; no se llamó al puerto.
- `FALLIDO`: el entrenador no tenía teléfono; no se llamó al puerto (`destino` NULL).

Columnas EXACTAS a `migrations/versions/0014_*.py` (autoridad del esquema físico,
db-dev). Es **contrato compartido** backend↔db: si una columna cambia tras empezar,
handoff y parar. NO lleva `created_at`/`updated_at`; el sello es `enviado_en`
(timestamptz now()), por eso NO hereda `TimestampMixin`.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, OrgScoped, UUIDPkMixin


class RecordatorioDeudores(UUIDPkMixin, OrgScoped, Base):
    __tablename__ = "recordatorio_deudores"

    entrenador_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("entrenador.id", ondelete="CASCADE"),
        nullable=False,
    )
    sucursal_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("sucursal.id", ondelete="CASCADE"),
        nullable=False,
    )
    periodo: Mapped[str] = mapped_column(Text, nullable=False)
    origen: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'CRON'"), default="CRON"
    )  # CRON | MANUAL
    canal: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'WHATSAPP'"), default="WHATSAPP"
    )  # WHATSAPP
    destino: Mapped[str | None] = mapped_column(Text, nullable=True)
    num_deudores: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0"), default=0
    )
    monto_total: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, server_default=text("0"), default=Decimal("0")
    )
    provider_message_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    estado: Mapped[str] = mapped_column(
        Text, nullable=False, server_default=text("'ENVIADO'"), default="ENVIADO"
    )  # ENVIADO | FALLIDO | SIN_DEUDORES
    enviado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "entrenador_id", "sucursal_id", "periodo", name="uq_recordatorio_deudores"
        ),
        Index("ix_recordatorio_deudores_org_ent", "org_id", "entrenador_id"),
        CheckConstraint("origen IN ('CRON','MANUAL')", name="ck_recordatorio_deudores_origen"),
        CheckConstraint(
            "estado IN ('ENVIADO','FALLIDO','SIN_DEUDORES')",
            name="ck_recordatorio_deudores_estado",
        ),
    )
