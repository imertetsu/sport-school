"""Modelo puente N:M `alumno_tutor` (C1). UNIQUE(alumno_id, tutor_id)."""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, OrgScoped, TimestampMixin, UUIDPkMixin


class AlumnoTutor(UUIDPkMixin, OrgScoped, TimestampMixin, Base):
    __tablename__ = "alumno_tutor"
    __table_args__ = (UniqueConstraint("alumno_id", "tutor_id", name="uq_alumno_tutor"),)

    alumno_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("alumno.id"), nullable=False, index=True
    )
    tutor_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tutor.id"), nullable=False, index=True
    )
    parentesco: Mapped[str | None] = mapped_column(String, nullable=True)
    responsable_pago: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
