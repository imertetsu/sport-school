"""Modelo `aviso` (C1) — un aviso del muro administrado centralmente (RF-COM-01).

Tabla tenant con RLS por `org_id` (fail-closed, patrón NULLIF de 0003/0004). Es el
último epic del MVP fase 1: el ADMIN publica avisos con un **alcance**
(ORG / SUCURSAL / CATEGORIA) y admin/entrenador los ven en un feed (el entrenador
solo los que le aplican).

Columnas EXACTAS a `migrations/versions/0006_avisos.py` (autoridad del esquema
físico, db-dev). Este modelo es **contrato compartido** backend->db: si una columna
cambia tras empezar, handoff y parar (no driftear el esquema en un solo lado).
`aviso` lleva `created_at` (timestamptz now()) pero NO `updated_at` (igual que
`egreso`), por eso no hereda `TimestampMixin`. El default de `id` y de `created_at`
lo pone el servidor (gen_random_uuid()/now()); aquí se replica con `UUIDPkMixin`
(default app uuid4) + `server_default` para que coincidan.

`alcance` es ORG|SUCURSAL|CATEGORIA (CHECK en la BD). La **invariante**
(alcance<->sucursal_id/categoria_id) la valida el backend (422), no la BD: SUCURSAL
exige `sucursal_id`; CATEGORIA exige `categoria_id`; ORG exige ambos nulos.
`vigente_hasta` (date) NULL = sin caducidad. `creado_por` es auditoría (RNF-03): el
usuario del token que publicó. `activo` (bool default true) habilita el
**soft-delete** (DELETE => activo=false, sin borrado físico).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, OrgScoped, UUIDPkMixin


class Aviso(UUIDPkMixin, OrgScoped, Base):
    __tablename__ = "aviso"

    titulo: Mapped[str] = mapped_column(Text, nullable=False)
    cuerpo: Mapped[str] = mapped_column(Text, nullable=False)
    alcance: Mapped[str] = mapped_column(Text, nullable=False)  # ORG|SUCURSAL|CATEGORIA
    sucursal_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("sucursal.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    categoria_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("categoria.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    publicado_en: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    vigente_hasta: Mapped[date | None] = mapped_column(
        Date, nullable=True
    )  # NULL = sin caducidad
    creado_por: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("usuario.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )  # auditoría (RNF-03): usuario del token que publicó
    activo: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=func.true(), default=True
    )  # soft-delete: DELETE => activo=false
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (Index("ix_aviso_org_activo_publicado", "org_id", "activo", "publicado_en"),)
