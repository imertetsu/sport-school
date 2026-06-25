"""Modelo `whatsapp_sesion` (C1, epic whatsapp-multitenant) — sesión por escuela.

**Una fila por organización** (UNIQUE en `org_id`): metadata best-effort de la sesión de
WhatsApp de esa escuela para mostrarla en la UI de Ajustes. La **verdad LIVE**
(connected / QR vivo) es el **sidecar** (`Map<org_id, Session>` en Baileys); el backend la
reconcilia en cada GET de estado. `estado` en BD es por tanto un **cache best-effort**.

Tabla tenant con **RLS por `org_id`** (fail-closed NULLIF, patrón `0005_egresos.py`):
`ENABLE+FORCE` + policy `org_isolation` + GRANT a `latinosport_app`. NO se añaden columnas
a `organizacion` (que no tiene RLS): la sesión vive en su propia tabla.

Columnas EXACTAS a `migrations/versions/0022_whatsapp_sesion.py` (autoridad del esquema
físico, db-dev — head actual 0021 → nueva 0022). Este modelo es **contrato compartido**
backend->db: db-dev autogenera la migración a partir de `Base.metadata`; si una columna
cambia tras empezar, handoff y parar (no driftear el esquema en un solo lado).

El **CHECK** de `estado` (`'DESVINCULADA'|'PENDIENTE_QR'|'CONECTADA'`) lo pone db-dev en la
migración (patrón del repo: el CHECK enum-like vive en la migración, no declarativo — ver
`recordatorio_pago.py` que sí lo declara, vs el grueso de modelos que lo dejan a la BD).
Aquí se declara el `server_default`/`default` de `estado` y el `UniqueConstraint` de
`org_id` (es un UNIQUE simple, no parcial → puede ir declarativo; los únicos parciales de
CI del repo viven solo en migraciones).
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, OrgScoped, TimestampMixin, UUIDPkMixin


class WhatsAppSesion(UUIDPkMixin, OrgScoped, TimestampMixin, Base):
    __tablename__ = "whatsapp_sesion"

    # estado: cache best-effort. CHECK IN (...) lo pone db-dev en la migración (patrón repo).
    estado: Mapped[str] = mapped_column(
        String, nullable=False, server_default=text("'DESVINCULADA'"), default="DESVINCULADA"
    )  # DESVINCULADA | PENDIENTE_QR | CONECTADA
    numero: Mapped[str | None] = mapped_column(String, nullable=True)  # dígitos E.164 del par
    vinculado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # 1 fila por org. UNIQUE simple (no parcial) ⇒ declarativo OK; db-dev confirma al autogenerar.
    __table_args__ = (UniqueConstraint("org_id", name="uq_whatsapp_sesion_org"),)
