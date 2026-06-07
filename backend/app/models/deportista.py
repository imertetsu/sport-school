"""Modelo `deportista` (C1). `ficha_medica` JSONB {tipo_sangre, alergias, condiciones}."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from sqlalchemy import Date, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, OrgScoped, TimestampMixin, UUIDPkMixin


class Deportista(UUIDPkMixin, OrgScoped, TimestampMixin, Base):
    __tablename__ = "deportista"

    sucursal_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("sucursal.id"), nullable=False, index=True
    )
    categoria_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("categoria.id"), nullable=True, index=True
    )
    ap_paterno: Mapped[str | None] = mapped_column(String, nullable=True)
    ap_materno: Mapped[str | None] = mapped_column(String, nullable=True)
    nombres: Mapped[str] = mapped_column(String, nullable=False)
    ci: Mapped[str | None] = mapped_column(String, nullable=True)
    fecha_nac: Mapped[date | None] = mapped_column(Date, nullable=True)
    disciplina: Mapped[str | None] = mapped_column(String, nullable=True)
    contacto_emergencia: Mapped[str | None] = mapped_column(String, nullable=True)
    ficha_medica: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
