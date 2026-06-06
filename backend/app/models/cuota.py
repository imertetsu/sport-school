"""Modelo `cuota` (C1).

Cuota mensual generada por el motor de cobranza (C2). Tabla tenant con RLS por
`org_id`. La idempotencia de generación la garantiza
`UNIQUE(inscripcion_id, periodo_inicio)`: re-correr la generación no duplica.

Las columnas coinciden EXACTO con `migrations/versions/0002_cobranza.py` (la
autoridad del esquema físico): `cuota` no lleva `created_at`/`updated_at`, solo
`generada_en` (timestamptz). Por eso NO hereda `TimestampMixin`.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, OrgScoped, UUIDPkMixin


class Cuota(UUIDPkMixin, OrgScoped, Base):
    __tablename__ = "cuota"

    inscripcion_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("inscripcion.id"), nullable=False, index=True
    )
    periodo_inicio: Mapped[date] = mapped_column(Date, nullable=False)
    periodo_fin: Mapped[date] = mapped_column(Date, nullable=False)
    vence_el: Mapped[date] = mapped_column(Date, nullable=False)
    monto: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    # Abonos (0009): cuánto se ha aplicado a esta cuota. Saldo = monto - monto_pagado
    # (derivado, no se persiste). EXACTO a 0009_abonos.py (contrato con db-dev).
    monto_pagado: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=Decimal("0")
    )
    estado: Mapped[str] = mapped_column(
        String, nullable=False, default="PENDIENTE"
    )  # PENDIENTE | PARCIAL | PAGADO | VENCIDO
    es_prorrateo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    generada_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint(
            "inscripcion_id", "periodo_inicio", name="uq_cuota_inscripcion_periodo_inicio"
        ),
        Index("ix_cuota_org_estado_vence_el", "org_id", "estado", "vence_el"),
    )
