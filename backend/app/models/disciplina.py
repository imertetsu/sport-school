"""Modelo `disciplina` (epic Disciplinas, S2) — catálogo GLOBAL del SaaS.

A diferencia de las tablas tenant, `disciplina` **NO** hereda de `OrgScoped`: no tiene
`org_id` ni RLS (mismo patrón que `plataforma_admin` / `organizacion`). Es un catálogo
global gobernado por el superadmin desde `/plataforma`; la escuela solo lo lee
(`GET /catalogo/disciplinas`, cero datos de tenant).

La unicidad **case-insensitive** vive en la migración como índice funcional
`uq_disciplina_nombre_lower ON disciplina (lower(nombre))`, NO como `UniqueConstraint`
declarativo (SQLAlchemy no expresa índices funcionales en `Base.metadata` de forma
portable; la autoridad del esquema físico es la migración 0016 de db-dev).
"""

from __future__ import annotations

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPkMixin


class Disciplina(UUIDPkMixin, TimestampMixin, Base):
    __tablename__ = "disciplina"

    nombre: Mapped[str] = mapped_column(String, nullable=False)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
