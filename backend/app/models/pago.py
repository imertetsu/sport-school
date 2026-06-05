"""Modelo `pago` (C1).

Un pago efectivo (admin) o QR (sandbox OpenBCB). Tabla tenant con RLS por
`org_id`. La idempotencia del webhook descansa en `transaccion_id` UNIQUE;
`qr_ref` UNIQUE es la referencia interna usada para resolver el pago desde el
webhook vía `webhook_resolver` (SECURITY DEFINER).

Columnas EXACTAS a `migrations/versions/0002_cobranza.py` (autoridad): `pago`
lleva `created_at` pero NO `updated_at`, por eso no hereda `TimestampMixin`.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, String, func
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, OrgScoped, UUIDPkMixin


class Pago(UUIDPkMixin, OrgScoped, Base):
    __tablename__ = "pago"

    metodo: Mapped[str] = mapped_column(String, nullable=False)  # EFECTIVO | QR
    estado: Mapped[str] = mapped_column(
        String, nullable=False, default="PENDIENTE"
    )  # PENDIENTE | CONFIRMADO | FALLIDO
    monto: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    transaccion_id: Mapped[str | None] = mapped_column(
        String, nullable=True, unique=True
    )  # referencia externa OpenBCB
    qr_ref: Mapped[str | None] = mapped_column(
        String, nullable=True, unique=True
    )  # referencia interna del QR
    pagado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    registrado_por: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("usuario.id"), nullable=True
    )  # solo efectivo
    comprobante_url: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
