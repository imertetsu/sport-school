"""Modelo `plataforma_auditoria` (Epic Super Admin) — auditoría mínima de plataforma.

Tabla ligera **sin RLS** (como `plataforma_admin`/`organizacion`): la acción la
ejecuta el SUPERADMIN, que no tiene contexto de org, así que una tabla tenant con
RLS le quedaría inaccesible. Solo registra quién (admin_id), qué acción y sobre qué
escuela (org_id es un DATO, NO scope RLS → NO se usa `OrgScoped`).

Solo `created_at` (registro inmutable, sin updated_at) — patrón de `egreso`/
`solicitud_registro`, por eso NO hereda `TimestampMixin`. La autoridad del esquema es
la migración 0012 (db-dev); este modelo debe quedar alineado con ella.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPkMixin


class PlataformaAuditoria(UUIDPkMixin, Base):
    __tablename__ = "plataforma_auditoria"

    admin_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    # CREAR_ESCUELA | SUSPENDER_ESCUELA | REACTIVAR_ESCUELA (CHECK en BD).
    accion: Mapped[str] = mapped_column(String, nullable=False)
    org_id: Mapped[uuid.UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    detalle: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
