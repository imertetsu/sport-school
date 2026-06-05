"""Modelo `usuario` (C1). `email` UNIQUE global; `role` ADMIN|ENTRENADOR."""

from __future__ import annotations

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, OrgScoped, TimestampMixin, UUIDPkMixin


class Usuario(UUIDPkMixin, OrgScoped, TimestampMixin, Base):
    __tablename__ = "usuario"

    email: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    role: Mapped[str] = mapped_column(String, nullable=False)  # ADMIN | ENTRENADOR
    nombre: Mapped[str] = mapped_column(String, nullable=False)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
