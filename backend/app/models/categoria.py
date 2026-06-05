"""Modelo `categoria` (C1). `nivel` PRINCIPIANTE|INTERMEDIO|AVANZADO."""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, OrgScoped, TimestampMixin, UUIDPkMixin


class Categoria(UUIDPkMixin, OrgScoped, TimestampMixin, Base):
    __tablename__ = "categoria"

    sucursal_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("sucursal.id"), nullable=False, index=True
    )
    nombre: Mapped[str] = mapped_column(String, nullable=False)
    nivel: Mapped[str] = mapped_column(String, nullable=False)  # PRINCIPIANTE|INTERMEDIO|AVANZADO
    rango_edad: Mapped[str | None] = mapped_column(String, nullable=True)  # ej "Sub-14"
