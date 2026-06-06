"""Modelo `plataforma_admin` (Epic Super Admin) — identidad de PLATAFORMA.

A diferencia de `usuario`, esta tabla **no es tenant**: no tiene `org_id` ni RLS
(como `organizacion`, la única otra tabla sin RLS). El super admin opera la consola
de plataforma (`/plataforma`), crea/suspende escuelas y nunca tiene contexto de org
→ por eso `require_superadmin` NO fija el GUC y RLS lo deja fail-closed (0 filas) en
cualquier tabla tenant.

`email` es UNIQUE global de login de plataforma (independiente del `usuario.email`
de las escuelas). `password_hash` = bcrypt (`security.hash_password`). La autoridad
del esquema físico es la migración 0012 (db-dev); este modelo debe quedar ALINEADO
con ella (lección del epic WhatsApp/0011: el modelo desalineado costó un fix).
"""

from __future__ import annotations

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPkMixin


class PlataformaAdmin(UUIDPkMixin, TimestampMixin, Base):
    __tablename__ = "plataforma_admin"

    email: Mapped[str] = mapped_column(String, nullable=False, unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String, nullable=False)
    nombre: Mapped[str] = mapped_column(String, nullable=False)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
