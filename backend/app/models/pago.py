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

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Text, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, OrgScoped, UUIDPkMixin


class Pago(UUIDPkMixin, OrgScoped, Base):
    __tablename__ = "pago"

    # Recibo no-fiscal (epic Recibo): correlativo `REC-NNNNNN` por org, asignado al
    # confirmar (NULL hasta entonces). El UNIQUE(org_id, numero_recibo) lo declara la
    # migración 0010 (autoridad); se refleja aquí en __table_args__ por coherencia.
    __table_args__ = (
        UniqueConstraint("org_id", "numero_recibo", name="uq_pago_org_numero_recibo"),
    )

    metodo: Mapped[str] = mapped_column(String, nullable=False)  # EFECTIVO | QR
    estado: Mapped[str] = mapped_column(
        String, nullable=False, default="PENDIENTE"
    )  # PENDIENTE | CONFIRMADO | FALLIDO | ANULADO
    monto: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)  # solo efectivo/caja
    # Abonos (0009): crédito previo de la inscripción consumido en este pago. Invariante:
    # Σ pago_cuota.monto_aplicado = pago.monto + pago.credito_aplicado. EXACTO a 0009.
    credito_aplicado: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, default=Decimal("0")
    )
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
    numero_recibo: Mapped[str | None] = mapped_column(
        String, nullable=True
    )  # REC-NNNNNN, NULL hasta CONFIRMADO (epic Recibo)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # Anulación (epic anular-pago) — reversa CON rastro (RNF-02/03), nunca borrado
    # físico. Columnas EXACTAS a `migrations/versions/0025_anular_pago.py` (autoridad).
    # `credito_generado` persiste el sobrepago→crédito de ESTE pago para revertir el
    # saldo a favor con exactitud al anular.
    motivo_anulacion: Mapped[str | None] = mapped_column(Text, nullable=True)
    anulado_por: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("usuario.id", ondelete="SET NULL"), nullable=True
    )
    anulado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    credito_generado: Mapped[Decimal] = mapped_column(
        Numeric(10, 2), nullable=False, server_default=text("'0'"), default=Decimal("0")
    )
