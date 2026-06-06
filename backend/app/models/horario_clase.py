"""Modelo `horario_clase` (C1) — horario recurrente de clase por categoría.

Tabla tenant con RLS por `org_id`. Define el patrón semanal (día + franja
horaria) del que el cron genera las `sesion` futuras y dispara el recordatorio.

`dia_semana` es un `smallint` con CHECK 0..6 donde **0=Lunes … 6=Domingo**,
exactamente como `date.weekday()` de Python (clave para la generación). La
unicidad `UNIQUE(categoria_id, dia_semana, hora_inicio)` evita horarios duplicados
para la misma categoría/día/hora.

Columnas EXACTAS a `migrations/versions/0007_horarios.py` (autoridad del esquema
físico). `created_at` (timestamptz now()) pero NO `updated_at`, por eso NO hereda
`TimestampMixin` (igual criterio que `sesion`). El default de `id`/`created_at` lo
pone el servidor; aquí se replica con `UUIDPkMixin` + `server_default`.
"""

from __future__ import annotations

import uuid
from datetime import datetime, time

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    SmallInteger,
    Time,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, OrgScoped, UUIDPkMixin


class HorarioClase(UUIDPkMixin, OrgScoped, Base):
    __tablename__ = "horario_clase"

    categoria_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("categoria.id"), nullable=False, index=True
    )
    dia_semana: Mapped[int] = mapped_column(SmallInteger, nullable=False)  # 0=Lun … 6=Dom
    hora_inicio: Mapped[time] = mapped_column(Time, nullable=False)
    hora_fin: Mapped[time] = mapped_column(Time, nullable=False)
    entrenador_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("entrenador.id"), nullable=True, index=True
    )
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        CheckConstraint("dia_semana >= 0 AND dia_semana <= 6", name="ck_horario_dia_semana"),
        UniqueConstraint(
            "categoria_id", "dia_semana", "hora_inicio", name="uq_horario_categoria_dia_hora"
        ),
        Index("ix_horario_org_categoria", "org_id", "categoria_id"),
    )
