"""Modelo `entrenador` (C1)."""

from __future__ import annotations

import uuid

from sqlalchemy import ForeignKey, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, OrgScoped, TimestampMixin, UUIDPkMixin


class Entrenador(UUIDPkMixin, OrgScoped, TimestampMixin, Base):
    __tablename__ = "entrenador"

    usuario_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("usuario.id"), nullable=False, index=True
    )
    nombres: Mapped[str] = mapped_column(String, nullable=False)
    especialidad: Mapped[str | None] = mapped_column(String, nullable=True)
    # CI (documento de identidad), único por org cuando no es NULL. El índice único
    # PARCIAL `(org_id, ci) WHERE ci IS NOT NULL` vive SOLO en la migración 0017
    # (db-dev), no como `UniqueConstraint` declarativo: múltiples NULL permitidos.
    ci: Mapped[str | None] = mapped_column(String, nullable=True)
    # Teléfono E.164 sin `+` (epic Recordatorio de deudores): destino del digest de
    # deudores por WhatsApp. Validación de forma en Pydantic.
    telefono: Mapped[str | None] = mapped_column(String, nullable=True)
    # JSONB legacy de disciplinas (texto libre). CONSERVADO por data-preserving (D1
    # del epic S4): la M:N a `disciplina` (catálogo global) lo reemplaza en la API,
    # pero la columna NO se dropea ni se escribe ya desde el servicio.
    disciplinas: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
