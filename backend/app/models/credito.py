"""Modelo `credito` (0009 Abonos) — saldo a favor por inscripción (RF-ABO-06/07).

Tabla tenant con RLS por `org_id` (fail-closed, patrón NULLIF de 0003/0004). Un
sobrepago en efectivo deja remanente que se guarda como `saldo` de crédito de la
inscripción; el siguiente pago lo consume primero (antes del efectivo nuevo).

`UNIQUE(inscripcion_id)`: un único crédito por inscripción (el servicio hace upsert
sobre esa fila). `CHECK(saldo >= 0)` (`ck_credito_saldo_no_negativo`): el crédito
nunca queda negativo. Hereda `TimestampMixin` (`created_at`/`updated_at`).

Columnas EXACTAS a `migrations/versions/0009_abonos.py` (autoridad del esquema
físico, db-dev). Es **contrato compartido** backend->db: si una columna cambia tras
empezar, handoff y parar (no driftear el esquema en un solo lado).
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Numeric, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, OrgScoped, TimestampMixin, UUIDPkMixin


class Credito(UUIDPkMixin, OrgScoped, TimestampMixin, Base):
    __tablename__ = "credito"

    inscripcion_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("inscripcion.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    saldo: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False, default=Decimal("0"))

    __table_args__ = (
        UniqueConstraint("inscripcion_id", name="uq_credito_inscripcion"),
        CheckConstraint("saldo >= 0", name="ck_credito_saldo_no_negativo"),
    )
