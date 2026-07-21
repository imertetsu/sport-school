"""Modelo `egreso` (C1) — un gasto de la escuela (RF-FIN-07).

Tabla tenant con RLS por `org_id` (fail-closed, patrón NULLIF de 0003/0004). Es
el contraparte de `cuota`/`pago` en el lado de salidas de caja. En MVP solo se
crea y se lista (no edición/borrado).

Columnas EXACTAS a `migrations/versions/0005_egresos.py` (autoridad del esquema
físico, db-dev). Este modelo es **contrato compartido** backend->db: si una
columna cambia tras empezar, handoff y parar (no driftear el esquema en un solo
lado). `egreso` lleva `created_at` (timestamptz now()) pero NO `updated_at`
(MVP = inmutable), por eso no hereda `TimestampMixin`. El default de `id` y de
`created_at` lo pone el servidor (gen_random_uuid()/now()); aquí se replica con
`UUIDPkMixin` (default app uuid4) + `server_default` para que coincidan.

`monto` es `numeric(10,2)`; la regla `monto > 0` se valida en la API (422), no
con un default. `metodo` (0027) es EFECTIVO|QR, con CHECK en BD. `sucursal_id` es
NULLABLE: un egreso a nivel org (no atado a una sucursal) lo deja en NULL.
`registrado_por` es auditoría (RNF-03): el usuario del token que dio el alta.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, DateTime, ForeignKey, Index, Numeric, Text, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, OrgScoped, UUIDPkMixin


class Egreso(UUIDPkMixin, OrgScoped, Base):
    __tablename__ = "egreso"

    sucursal_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("sucursal.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    categoria_gasto: Mapped[str] = mapped_column(Text, nullable=False)  # texto libre (MVP)
    # Con qué se pagó el gasto. MISMOS literales que `pago.metodo` (ck_pago_metodo)
    # para que el panel pueda desglosar ingresos y egresos con el mismo vocabulario.
    # El CHECK vive en 0027 (ck_egreso_metodo); el server_default hace de backfill.
    metodo: Mapped[str] = mapped_column(
        Text, nullable=False, default="EFECTIVO", server_default="EFECTIVO"
    )
    monto: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    fecha: Mapped[date] = mapped_column(Date, nullable=False)  # fecha del gasto, no created_at
    descripcion: Mapped[str | None] = mapped_column(Text, nullable=True)
    registrado_por: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("usuario.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )  # auditoría (RNF-03): usuario del token que dio el alta
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    __table_args__ = (Index("ix_egreso_org_fecha", "org_id", "fecha"),)
