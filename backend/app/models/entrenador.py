"""Modelo `entrenador` (C1)."""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, OrgScoped, TimestampMixin, UUIDPkMixin


class Entrenador(UUIDPkMixin, OrgScoped, TimestampMixin, Base):
    __tablename__ = "entrenador"

    usuario_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("usuario.id"), nullable=False, index=True
    )
    nombres: Mapped[str] = mapped_column(String, nullable=False)
    especialidad: Mapped[str | None] = mapped_column(String, nullable=True)
    disciplinas: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
