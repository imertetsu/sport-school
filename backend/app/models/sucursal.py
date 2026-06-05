"""Modelo `sucursal` (C1)."""

from __future__ import annotations

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, OrgScoped, TimestampMixin, UUIDPkMixin


class Sucursal(UUIDPkMixin, OrgScoped, TimestampMixin, Base):
    __tablename__ = "sucursal"

    nombre: Mapped[str] = mapped_column(String, nullable=False)
    direccion: Mapped[str | None] = mapped_column(String, nullable=True)
