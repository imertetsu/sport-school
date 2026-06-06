"""Modelo `conciliacion_pendiente` (C1) — cola dead-letter de pagos.

A diferencia del resto de tablas tenant, esta cola NO lleva `org_id` ni RLS
(ops/vendor): el webhook escribe aquí cuando no puede resolver la referencia o el
monto no cuadra, de modo que **ningún pago se pierde jamás** (RNF-06). El rol
`latinosport_app` tiene GRANT explícito de DML sobre ella en la migración.

Por eso NO hereda `OrgScoped`. Columnas EXACTAS a
`migrations/versions/0002_cobranza.py` (autoridad): lleva `created_at`.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, DateTime, Numeric, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, UUIDPkMixin


class ConciliacionPendiente(UUIDPkMixin, Base):
    __tablename__ = "conciliacion_pendiente"

    transaccion_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    referencia: Mapped[str | None] = mapped_column(Text, nullable=True)
    monto: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    payload: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    motivo: Mapped[str | None] = mapped_column(Text, nullable=True)
    resuelto: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
