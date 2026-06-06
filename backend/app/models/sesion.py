"""Modelo `sesion` (C1) — una sesión de clase por categoría/fecha(/hora).

Tabla tenant con RLS por `org_id`. La idempotencia del guardado de asistencia
descansa en que no se dupliquen sesiones: `UNIQUE(categoria_id, fecha, hora)`
(con `hora` NULL cuenta como una sesión por día).

Columnas EXACTAS a `migrations/versions/0004_asistencia.py` + ALTER de
`0007_horarios.py` (autoridad del esquema físico): `sesion` lleva `created_at`
(timestamptz now()) pero NO `updated_at`, por eso NO hereda `TimestampMixin`. El
default de `id` y de `created_at` lo pone el servidor (gen_random_uuid()/now());
aquí se replica con `UUIDPkMixin` (default app uuid4) + `server_default` para que
coincidan.

Epic Programación de clases (C1) añade dos columnas **nullable** (no rompen
Asistencia ni sus sesiones creadas a mano):
- `horario_id` -> FK a `horario_clase` (ON DELETE SET NULL): las sesiones
  generadas desde un horario lo enlazan; las creadas a mano quedan NULL.
- `recordatorio_enviado_en` (timestamptz) -> marca de idempotencia del
  recordatorio de clase (NULL = aún no enviado).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time

from sqlalchemy import Date, DateTime, ForeignKey, Index, Text, Time, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, OrgScoped, UUIDPkMixin


class Sesion(UUIDPkMixin, OrgScoped, Base):
    __tablename__ = "sesion"

    categoria_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("categoria.id"), nullable=False, index=True
    )
    fecha: Mapped[date] = mapped_column(Date, nullable=False)
    hora: Mapped[time | None] = mapped_column(Time, nullable=True)
    entrenador_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("entrenador.id"), nullable=True, index=True
    )
    notas: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Enlace al horario recurrente que la generó (NULL = creada a mano). C1 (0007).
    horario_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("horario_clase.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Marca de idempotencia del recordatorio de clase (NULL = aún no enviado). C1 (0007).
    recordatorio_enviado_en: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (
        UniqueConstraint("categoria_id", "fecha", "hora", name="uq_sesion_categoria_fecha_hora"),
        Index("ix_sesion_org_categoria_fecha", "org_id", "categoria_id", "fecha"),
    )
