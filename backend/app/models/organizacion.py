"""Modelo `organizacion` — la única tabla SIN org_id ni RLS (C1)."""

from __future__ import annotations

from sqlalchemy import Boolean, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPkMixin


class Organizacion(UUIDPkMixin, TimestampMixin, Base):
    __tablename__ = "organizacion"

    nombre: Mapped[str] = mapped_column(String, nullable=False)
    pais: Mapped[str] = mapped_column(String, nullable=False, default="BO")
    moneda: Mapped[str] = mapped_column(String, nullable=False, default="BOB")
    regimen_fiscal: Mapped[str | None] = mapped_column(String, nullable=True)
    modo_cobro_default: Mapped[str] = mapped_column(
        String, nullable=False, default="ANIVERSARIO"
    )  # FIJO | ANIVERSARIO
    dia_corte_fijo: Mapped[int | None] = mapped_column(Integer, nullable=True)
    prorratea_primer_periodo: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
