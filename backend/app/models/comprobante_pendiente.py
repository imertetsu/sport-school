"""Modelo `comprobante_pendiente` (C2, epic pagos-qr-comprobante) — cola "Pagos por verificar".

El tutor responde al número de la escuela con la captura del pago; el sidecar la reenvía al
backend, que la guarda aquí (bytea), corre **OCR best-effort** (monto / nº transacción /
fecha → `null` si el OCR falla) e identifica al tutor por su teléfono → su cuota pendiente
más antigua (FIFO) como sugerencia. El ADMIN confirma en 1 clic (reusa
`registrar_pago_efectivo`) o rechaza. **Nunca auto-confirma** en v1.

Tabla tenant con **RLS por `org_id`** (fail-closed NULLIF, patrón 0022):
`ENABLE+FORCE` + policy `org_isolation` + GRANT a `latinosport_app`. El comprobante de la
org A es invisible a la org B.

Columnas EXACTAS al contrato C2 / migración **0023** (autoridad del esquema físico,
db-dev — head actual 0022 → nueva 0023). Este modelo es **contrato compartido**
backend->db: db-dev autogenera la migración a partir de `Base.metadata`; si una columna
cambia tras empezar, handoff y parar.

Constraints que NO van declarativos y los pone db-dev A MANO en la migración (patrón del
repo: el CHECK enum-like y los únicos parciales viven solo en la migración):
  - **CHECK** `estado IN ('PENDIENTE','CONFIRMADO','RECHAZADO')`.
  - **UNIQUE parcial** `(transaccion_id_ocr) WHERE transaccion_id_ocr IS NOT NULL`
    `uq_comprobante_transaccion_ocr` (anti-fraude: un mismo comprobante no se confirma 2x).
  - **index** `(org_id, estado)` para la cola por estado.
El **UNIQUE simple de `message_id`** (idempotencia ante re-entrega del sidecar) SÍ va
declarativo aquí (`uq_comprobante_pendiente_message`); db-dev lo confirma al autogenerar.

`org_id`/`id` vienen de los mixins; `created_at` se declara aquí (NO `updated_at`: el ciclo
de resolución usa `resuelto_en` explícito, por eso NO hereda `TimestampMixin`).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, OrgScoped, UUIDPkMixin


class ComprobantePendiente(UUIDPkMixin, OrgScoped, Base):
    __tablename__ = "comprobante_pendiente"

    # estado: PENDIENTE | CONFIRMADO | RECHAZADO. CHECK IN (...) lo pone db-dev en la
    # migración (patrón repo: el CHECK enum-like vive en la migración, no declarativo).
    estado: Mapped[str] = mapped_column(
        String, nullable=False, server_default=text("'PENDIENTE'"), default="PENDIENTE"
    )

    # Remitente del comprobante por WhatsApp (dígitos del par) — match por teléfono → tutor.
    from_telefono: Mapped[str] = mapped_column(String, nullable=False)
    # Idempotencia ante re-entrega del sidecar: mismo message_id ⇒ 1 fila.
    message_id: Mapped[str | None] = mapped_column(String, nullable=True)

    # La captura del pago como bytea; mime para reenviarla/mostrarla; caption del tutor.
    imagen: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    mime: Mapped[str] = mapped_column(String, nullable=False)
    caption: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Identificación automática (best-effort): tutor por teléfono + cuota FIFO sugerida.
    tutor_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tutor.id", ondelete="SET NULL"), nullable=True
    )
    cuota_sugerida_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("cuota.id", ondelete="SET NULL"), nullable=True
    )

    # OCR best-effort (null si no se leyó): monto / nº transacción / fecha + texto crudo.
    monto_ocr: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), nullable=True)
    transaccion_id_ocr: Mapped[str | None] = mapped_column(String, nullable=True)
    fecha_ocr: Mapped[date | None] = mapped_column(Date, nullable=True)
    ocr_texto_crudo: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Resolución: pago registrado al confirmar + auditoría de quién/cuándo lo resolvió.
    pago_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("pago.id", ondelete="SET NULL"), nullable=True
    )
    resuelto_por: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("usuario.id", ondelete="SET NULL"), nullable=True
    )
    resuelto_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # UNIQUE simple de message_id (idempotencia) ⇒ declarativo OK. El UNIQUE PARCIAL de
    # transaccion_id_ocr, el CHECK del enum de estado y el index (org_id, estado) los pone
    # db-dev A MANO en la migración (patrón del repo).
    __table_args__ = (UniqueConstraint("message_id", name="uq_comprobante_pendiente_message"),)
