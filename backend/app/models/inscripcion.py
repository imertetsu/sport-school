"""Modelo `inscripcion` (C1). Sin cuota/pago en este epic."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, OrgScoped, TimestampMixin, UUIDPkMixin


class Inscripcion(UUIDPkMixin, OrgScoped, TimestampMixin, Base):
    __tablename__ = "inscripcion"

    deportista_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("deportista.id"), nullable=False, index=True
    )
    disciplina: Mapped[str | None] = mapped_column(String, nullable=True)
    fecha_inscripcion: Mapped[date] = mapped_column(Date, nullable=False)
    monto_mensual: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    # null -> hereda ORGANIZACION.modo_cobro_default (motor de cuotas, epic posterior)
    modo_cobro: Mapped[str | None] = mapped_column(String, nullable=True)
    dia_corte: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estado: Mapped[str] = mapped_column(String, nullable=False, default="ACTIVA")  # ACTIVA|INACTIVA
