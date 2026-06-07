"""Modelo `entrenador_sucursal` (epic Recordatorio de deudores) — M:N entrenador↔sucursal.

Tabla tenant con RLS por `org_id`. Asigna un entrenador a una o más sucursales; esta
asignación SOLO alimenta el recordatorio de deudores (no cambia la vista del
entrenador ni el claim `sucursal_ids` del JWT). La idempotencia del alta la garantiza
`UNIQUE(entrenador_id, sucursal_id)`: re-insertar la misma asignación no duplica.

Columnas EXACTAS a `migrations/versions/0014_*.py` (autoridad del esquema físico,
db-dev). Es **contrato compartido** backend↔db: si una columna cambia tras empezar,
handoff y parar. NO lleva `updated_at`; el único sello es `created_at` (timestamptz
now()), por eso NO hereda `TimestampMixin`.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, OrgScoped, UUIDPkMixin


class EntrenadorSucursal(UUIDPkMixin, OrgScoped, Base):
    __tablename__ = "entrenador_sucursal"

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
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("entrenador_id", "sucursal_id", name="uq_entrenador_sucursal"),
        Index("ix_entrenador_sucursal_org_suc", "org_id", "sucursal_id"),
    )
