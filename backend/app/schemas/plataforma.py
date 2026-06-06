"""Schemas de la consola de plataforma (Epic Super Admin).

Contratos de request/response de `api/v1/plataforma.py`. NUNCA se serializa
`password_hash` (no aparece en ningún schema de salida).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr


# --------------------------------------------------------------------------- #
# Login de plataforma
# --------------------------------------------------------------------------- #
class PlataformaLoginIn(BaseModel):
    """Body de `POST /plataforma/login`."""

    email: EmailStr
    password: str


class AdminRef(BaseModel):
    """Datos públicos del super admin (sin password_hash)."""

    id: uuid.UUID
    nombre: str
    email: EmailStr


class PlataformaLoginOut(BaseModel):
    """Respuesta del login de plataforma."""

    access_token: str
    token_type: str = "bearer"
    admin: AdminRef


# --------------------------------------------------------------------------- #
# Escuelas (organizaciones)
# --------------------------------------------------------------------------- #
class EscuelaItem(BaseModel):
    """Una escuela en la lista de la consola."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    nombre: str
    pais: str
    moneda: str
    estado: str
    created_at: datetime


class CrearEscuelaIn(BaseModel):
    """Body de `POST /plataforma/escuelas` — org + su primer admin ADMIN."""

    nombre: str
    pais: str | None = None
    moneda: str | None = None
    admin_nombre: str
    admin_email: EmailStr
    admin_password: str


class EscuelaAdminRef(BaseModel):
    """Referencia mínima al admin recién creado de la escuela."""

    id: uuid.UUID
    email: EmailStr


class CrearEscuelaOut(BaseModel):
    """Respuesta de creación de escuela (201)."""

    id: uuid.UUID
    nombre: str
    estado: str
    admin: EscuelaAdminRef


class EscuelaEstadoOut(BaseModel):
    """Respuesta de suspender/reactivar."""

    id: uuid.UUID
    estado: str


# --------------------------------------------------------------------------- #
# Gestión de super admins
# --------------------------------------------------------------------------- #
class SuperAdminItem(BaseModel):
    """Un super admin en la lista (sin password_hash)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    nombre: str
    email: EmailStr
    activo: bool
    created_at: datetime


class CrearSuperAdminIn(BaseModel):
    """Body de `POST /plataforma/admins`."""

    nombre: str
    email: EmailStr
    password: str


class SuperAdminCreatedOut(BaseModel):
    """Respuesta de creación de super admin (201, sin password_hash)."""

    id: uuid.UUID
    nombre: str
    email: EmailStr
    activo: bool


class SuperAdminEstadoOut(BaseModel):
    """Respuesta de activar/desactivar super admin."""

    id: uuid.UUID
    activo: bool
