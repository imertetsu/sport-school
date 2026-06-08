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


class OrgRef(BaseModel):
    """Datos mínimos de la escuela embebidos en el login (C1, epic escuela-y-bajas).

    Aditivo a `TokenOut`: el TopBar pinta nombre + monograma (iniciales con `color`,
    default si `color` null) sin una llamada extra ni parpadeo.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    nombre: str
    color: str | None = None


class TokenOut(BaseModel):
    """Respuesta de login (C4 + C1): `{access_token, token_type, user, org}`."""

    access_token: str
    token_type: str = "bearer"
    user: UserOut
    org: OrgRef
