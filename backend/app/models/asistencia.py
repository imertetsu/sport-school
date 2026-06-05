"""Modelo `asistencia` (C1) — la marca de un alumno en una sesión.

Tabla tenant con RLS por `org_id`. La idempotencia del guardado descansa en
`UNIQUE(sesion_id, alumno_id)`: re-guardar la lista hace **upsert** (actualiza
`estado`/`registrado_por`/`updated_at`), nunca duplica filas. `estado` tiene un
CHECK PRESENTE|AUSENTE a nivel BD (ampliable a JUSTIFICADO sin romper esquema).

Columnas EXACTAS a `migrations/versions/0004_asistencia.py` (autoridad): lleva
`created_at` + `updated_at` (timestamptz now()). No hereda `TimestampMixin` para
replicar los `server_default`/`onupdate` que coinciden con la migración.
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
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, OrgScoped, UUIDPkMixin


class Asistencia(UUIDPkMixin, OrgScoped, Base):
    __tablename__ = "asistencia"

    sesion_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("sesion.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    alumno_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("alumno.id"), nullable=False, index=True
    )
    estado: Mapped[str] = mapped_column(Text, nullable=False)  # PRESENTE | AUSENTE
    registrado_por: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("usuario.id"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        UniqueConstraint("sesion_id", "alumno_id", name="uq_asistencia_sesion_alumno"),
        CheckConstraint("estado IN ('PRESENTE','AUSENTE')", name="ck_asistencia_estado"),
        Index("ix_asistencia_org_id", "org_id"),
    )
