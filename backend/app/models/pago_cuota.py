"""Modelo `pago_cuota` (C1) — puente N:M entre `pago` y `cuota`.

Tabla tenant con RLS por `org_id`. Cada fila registra cuánto de un pago se aplicó
a una cuota concreta (`monto_aplicado`). `UNIQUE(pago_id, cuota_id)` evita aplicar
dos veces el mismo pago a la misma cuota (idempotencia de la aplicación FIFO).

Columnas EXACTAS a `migrations/versions/0002_cobranza.py` (autoridad): sin
`created_at`/`updated_at`.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import ForeignKey, Numeric, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, OrgScoped, UUIDPkMixin


class PagoCuota(UUIDPkMixin, OrgScoped, Base):
    __tablename__ = "pago_cuota"

    pago_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("pago.id"), nullable=False, index=True
    )
    cuota_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("cuota.id"), nullable=False, index=True
    )
    monto_aplicado: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)

    __table_args__ = (UniqueConstraint("pago_id", "cuota_id", name="uq_pago_cuota_pago_cuota"),)
