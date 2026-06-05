"""Modelo `tutor` (C1)."""

from __future__ import annotations

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, OrgScoped, TimestampMixin, UUIDPkMixin


class Tutor(UUIDPkMixin, OrgScoped, TimestampMixin, Base):
    __tablename__ = "tutor"

    nombres: Mapped[str] = mapped_column(String, nullable=False)
    telefono: Mapped[str | None] = mapped_column(String, nullable=True)
    ci: Mapped[str | None] = mapped_column(String, nullable=True)
