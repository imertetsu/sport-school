"""Modelo `recibo_contador` (epic Recibo, C1/C2) — secuencia de recibos por org.

Una fila por organización; `ultimo_numero` es el último correlativo `REC-NNNNNN`
asignado. El incremento es atómico vía `INSERT ... ON CONFLICT (org_id) DO UPDATE
... RETURNING` (ver `services/pagos._asignar_numero_recibo`), de modo que dos
confirmaciones concurrentes de la misma org no producen números duplicados
(RF-REC-04). Tabla tenant con RLS por `org_id` (fail-closed NULLIF, patrón
0009/0010).

El **PRIMARY KEY es `org_id`** (no hay columna `id` propia): por eso NO hereda
`UUIDPkMixin` y redeclara `org_id` con `primary_key=True` (sobreescribe el
`OrgScoped.org_id`). Hereda `TimestampMixin` (`created_at`/`updated_at`).

Columnas EXACTAS a `migrations/versions/0010_recibo.py` (autoridad del esquema
físico, db-dev). Es **contrato compartido** backend->db: si una columna cambia tras
empezar, handoff y parar (no driftear el esquema en un solo lado).
"""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, Integer
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, OrgScoped, TimestampMixin


class ReciboContador(OrgScoped, TimestampMixin, Base):
    __tablename__ = "recibo_contador"

    # PK = org_id (sobreescribe OrgScoped.org_id). FK a organizacion ON DELETE CASCADE.
    org_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("organizacion.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False,
    )
    ultimo_numero: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
