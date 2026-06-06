"""Modelo `solicitud_registro` (C1) — cola de auto-registro EN SISTEMA.

Captura (logueada) de un alumno por entrenador/admin → cola PENDIENTE → el admin
aprueba (crea el alumno real reutilizando `app/services/alumno.py`) o rechaza.

NO hay token ni link público: es una pantalla dentro del sistema, autenticada y
con contexto de tenant fijado (RLS por `org_id`). La migración 0008 (db-dev) es la
autoridad del esquema (CHECK de `estado`, índice (org_id,estado,created_at), RLS
NULLIF + GRANTs). Aquí definimos la forma que db-dev migra.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import Date, DateTime, ForeignKey, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, OrgScoped, UUIDPkMixin


class SolicitudRegistro(UUIDPkMixin, OrgScoped, Base):
    __tablename__ = "solicitud_registro"

    # Estado de la cola: PENDIENTE | APROBADA | RECHAZADA (CHECK en BD, def PENDIENTE).
    estado: Mapped[str] = mapped_column(String, nullable=False, default="PENDIENTE")

    # --- Datos del alumno (capturados) ---
    ap_paterno: Mapped[str | None] = mapped_column(String, nullable=True)
    ap_materno: Mapped[str | None] = mapped_column(String, nullable=True)
    nombres: Mapped[str] = mapped_column(String, nullable=False)
    ci: Mapped[str | None] = mapped_column(String, nullable=True)
    fecha_nac: Mapped[date | None] = mapped_column(Date, nullable=True)
    disciplina: Mapped[str | None] = mapped_column(String, nullable=True)
    contacto_emergencia: Mapped[str | None] = mapped_column(Text, nullable=True)
    ficha_medica: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    # --- Datos del tutor (capturados) ---
    tutor_nombres: Mapped[str] = mapped_column(String, nullable=False)
    tutor_telefono: Mapped[str | None] = mapped_column(String, nullable=True)
    tutor_ci: Mapped[str | None] = mapped_column(String, nullable=True)
    parentesco: Mapped[str | None] = mapped_column(String, nullable=True)

    # --- Consentimiento (aceptado en la captura) ---
    consent_version: Mapped[str] = mapped_column(Text, nullable=False)
    consent_canal: Mapped[str] = mapped_column(Text, nullable=False, default="SISTEMA")
    consent_aceptado_en: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    # --- Sugerencias del capturador (administrativo lo decide el admin al aprobar) ---
    sucursal_sugerida_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("sucursal.id"), nullable=True
    )
    categoria_sugerida_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("categoria.id"), nullable=True
    )

    # --- Captura: quién la registró ---
    creado_por: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("usuario.id"), nullable=True
    )

    # --- Resultado de la revisión ---
    alumno_id: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("alumno.id"), nullable=True
    )
    motivo_rechazo: Mapped[str | None] = mapped_column(Text, nullable=True)
    revisado_por: Mapped[uuid.UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("usuario.id"), nullable=True
    )
    revisado_en: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Solo created_at (sin updated_at), consistente con egreso/aviso y la migración 0008.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
