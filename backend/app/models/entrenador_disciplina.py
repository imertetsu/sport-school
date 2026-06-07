"""Modelo `entrenador_disciplina` (epic S4 · CI/multi-disciplina) — M:N entrenador↔disciplina.

Tabla **tenant** con RLS por `org_id` (gemela de `entrenador_sucursal`). Enlaza un
entrenador con una o más disciplinas del **catálogo GLOBAL** `disciplina` (S2). El join
referencia el catálogo (sin org_id/RLS) pero esta tabla puente SÍ es tenant: el
aislamiento por org lo da RLS en la BD. La idempotencia del alta la garantiza
`UNIQUE(entrenador_id, disciplina_id)`: re-insertar la misma asignación no duplica.

Columnas EXACTAS a `migrations/versions/0017_*.py` (autoridad del esquema físico,
db-dev). Es **contrato compartido** backend↔db: si una columna cambia tras empezar,
handoff y parar. NO lleva `updated_at`; el único sello es `created_at` (timestamptz
now()), por eso NO hereda `TimestampMixin`. La `disciplina_id` referencia el catálogo
global con `ON DELETE RESTRICT` (como `categoria.disciplina_id`); `entrenador_id` con
`ON DELETE CASCADE`.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, OrgScoped, UUIDPkMixin


class EntrenadorDisciplina(UUIDPkMixin, OrgScoped, Base):
    __tablename__ = "entrenador_disciplina"

    entrenador_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("entrenador.id", ondelete="CASCADE"),
        nullable=False,
    )
    disciplina_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("disciplina.id", ondelete="RESTRICT"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("entrenador_id", "disciplina_id", name="uq_entrenador_disciplina"),
        Index("ix_entrenador_disciplina_org_disc", "org_id", "disciplina_id"),
    )
