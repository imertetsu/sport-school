"""Modelo puente N:M `deportista_tutor` (C1). UNIQUE(deportista_id, tutor_id)."""

from __future__ import annotations

import uuid

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, OrgScoped, TimestampMixin, UUIDPkMixin


class DeportistaTutor(UUIDPkMixin, OrgScoped, TimestampMixin, Base):
    __tablename__ = "deportista_tutor"
    __table_args__ = (UniqueConstraint("deportista_id", "tutor_id", name="uq_deportista_tutor"),)

    deportista_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("deportista.id"), nullable=False, index=True
    )
    tutor_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tutor.id"), nullable=False, index=True
    )
    parentesco: Mapped[str | None] = mapped_column(String, nullable=True)
    responsable_pago: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
