"""Schemas de autenticación (contrato C4)."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict, EmailStr


class LoginIn(BaseModel):
    """Body de `POST /auth/login`."""

    email: EmailStr
    password: str


class UserOut(BaseModel):
    """Usuario actual devuelto en login y en `GET /auth/me` (C4)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    nombre: str
    email: EmailStr
    role: str
    org_id: uuid.UUID


class TokenOut(BaseModel):
    """Respuesta de login (C4): `{access_token, token_type, user}`."""

    access_token: str
    token_type: str = "bearer"
    user: UserOut
