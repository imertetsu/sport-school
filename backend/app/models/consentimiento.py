"""Modelo `consentimiento` (C1). Requisito duro para persistir un deportista (RNF-02)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, OrgScoped, TimestampMixin, UUIDPkMixin


class Consentimiento(UUIDPkMixin, OrgScoped, TimestampMixin, Base):
    __tablename__ = "consentimiento"

    tutor_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tutor.id"), nullable=False, index=True
    )
    deportista_id: Mapped[uuid.UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("deportista.id"), nullable=False, index=True
    )
    version_terminos: Mapped[str] = mapped_column(String, nullable=False)
    canal: Mapped[str | None] = mapped_column(String, nullable=True)
    aceptado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
