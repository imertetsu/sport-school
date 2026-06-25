"""Modelo `qr_cobro` (C1, epic pagos-qr-comprobante) — QR estático por escuela.

**Una fila por organización** (UNIQUE en `org_id`): el ADMIN sube la imagen del QR de
su banco/billetera; el sistema la **reenvía tal cual** (no se decodifica) como adjunto del
recordatorio de cobro (`send_image`). El QR no es reconciliable (OpenBCB queda FUERA del
epic): la conciliación es asistida-manual vía `comprobante_pendiente`.

Tabla tenant con **RLS por `org_id`** (fail-closed NULLIF, patrón 0022):
`ENABLE+FORCE` + policy `org_isolation` + GRANT a `latinosport_app`. El QR de la org A es
invisible a la org B.

Columnas EXACTAS al contrato C1 / migración **0023** (autoridad del esquema físico,
db-dev — head actual 0022 → nueva 0023). Este modelo es **contrato compartido**
backend->db: db-dev autogenera la migración a partir de `Base.metadata`; si una columna
cambia tras empezar, handoff y parar (no driftear el esquema en un solo lado).

`org_id`/`id`/`created_at`/`updated_at` vienen de los mixins. El UNIQUE simple de `org_id`
(no parcial) puede ir declarativo; db-dev lo confirma/materializa al autogenerar (CASCADE
de la FK incluido, patrón del repo).
"""

from __future__ import annotations

from sqlalchemy import Integer, LargeBinary, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, OrgScoped, TimestampMixin, UUIDPkMixin


class QrCobro(UUIDPkMixin, OrgScoped, TimestampMixin, Base):
    __tablename__ = "qr_cobro"

    # Imagen del QR como bytea: se reenvía tal cual (no se decodifica).
    imagen: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    mime: Mapped[str] = mapped_column(String, nullable=False)  # p.ej. image/png
    tamano_bytes: Mapped[int] = mapped_column(Integer, nullable=False)

    # 1 fila por org. UNIQUE simple (no parcial) ⇒ declarativo OK; db-dev confirma al autogenerar.
    __table_args__ = (UniqueConstraint("org_id", name="uq_qr_cobro_org"),)
