"""Base declarativa y mixins (contrato C0).

- PK `id` UUID con default a nivel app (también default en BD vía migración db-dev).
- `created_at` / `updated_at` en UTC en todas las tablas.
- `OrgScoped`: añade `org_id UUID NOT NULL REFERENCES organizacion(id)` (denormalizado
  para RLS). Todas las tablas tenant heredan de él; `organizacion` NO.

NOTA: el aislamiento real es RLS en la BD (políticas creadas por db-dev en la
migración). Estos modelos definen el esquema que db-dev migra.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    """Base declarativa de SQLAlchemy 2.0. db-dev hace `from app.models import Base`."""


class UUIDPkMixin:
    """PK `id` UUID. Default en app (uuid4) además del default en BD."""

    id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )


class TimestampMixin:
    """`created_at` / `updated_at` en UTC (C0)."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        onupdate=_utcnow,
        nullable=False,
    )


class OrgScoped:
    """Añade `org_id` (FK a organizacion) para tablas tenant + RLS (C1)."""

    org_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizacion.id"),
        nullable=False,
        index=True,
    )
