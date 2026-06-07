"""Schemas de Entrenadores (epic B · Gestión de Entrenadores).

Formas de request/response **espejo exacto** del contrato fijado por main;
frontend-dev tipa contra ellas. `email` y `activo` provienen del `usuario` ligado
(join por `entrenador.usuario_id`).

- `EntrenadorCreate`: alta de entrenador (= usuario ENTRENADOR + perfil). `password`
  mínimo 8 (=> 422 si menor).
- `EntrenadorUpdate`: edición parcial; todos los campos opcionales (solo se aplican
  los provistos). `password` opcional con mínimo 8 si viene.
- `EntrenadorOut`: lo que devuelven GET/POST/PUT.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from pydantic import BaseModel, EmailStr, Field


class EntrenadorCreate(BaseModel):
    """Body de `POST /entrenadores` (solo ADMIN).

    Crea, en una transacción, el `usuario`(ENTRENADOR, activo) + el perfil
    `entrenador`. `org_id` lo fija el servidor (la org del admin, vía RLS).

    `telefono` (E.164 sin `+`) y `sucursal_ids` (asignación M:N a sucursales)
    alimentan el recordatorio de deudores (epic Recordatorio de deudores).
    """

    nombres: str = Field(min_length=1)
    email: EmailStr
    password: str = Field(min_length=8)
    especialidad: str | None = None
    telefono: str | None = None
    disciplinas: list[str] = Field(default_factory=list)
    sucursal_ids: list[uuid.UUID] = Field(default_factory=list)


class EntrenadorUpdate(BaseModel):
    """Body de `PUT /entrenadores/{id}` (solo ADMIN).

    Edición parcial: solo los campos no-None se aplican. `activo` da de baja
    (`false`) / reactiva (`true`). `password` resetea la clave si viene (min 8).
    El `email` no se edita (es la identidad de login).

    `sucursal_ids` (semántica del CONTRATO 4): `None` = no tocar; `[]` = limpiar el
    set; lista = **REEMPLAZA** el set de sucursales asignadas.
    """

    nombres: str | None = Field(default=None, min_length=1)
    especialidad: str | None = None
    telefono: str | None = None
    disciplinas: list[str] | None = None
    activo: bool | None = None
    password: str | None = Field(default=None, min_length=8)
    sucursal_ids: list[uuid.UUID] | None = None


class EntrenadorOut(BaseModel):
    """Item de `GET /entrenadores` y respuesta de `POST`/`PUT` (contrato B).

    `email`/`activo` provienen del `usuario` ligado (join por `usuario_id`).
    `telefono` y `sucursal_ids` (asignación M:N) del epic Recordatorio de deudores.
    """

    id: uuid.UUID
    usuario_id: uuid.UUID
    nombres: str
    email: str
    especialidad: str | None = None
    telefono: str | None = None
    disciplinas: list[str]
    activo: bool
    sucursal_ids: list[uuid.UUID] = Field(default_factory=list)


class RecordatorioDeudoresSucursalOut(BaseModel):
    """Resultado del digest de deudores de UNA sucursal (epic Recordatorio de deudores)."""

    sucursal_id: uuid.UUID
    sucursal_nombre: str
    num_deudores: int
    monto_total: Decimal
    estado: str  # ENVIADO | FALLIDO | SIN_DEUDORES


class RecordatorioDeudoresResult(BaseModel):
    """Respuesta de `POST /entrenadores/{id}/recordatorio-deudores` (a demanda)."""

    entrenador_id: uuid.UUID
    periodo: str
    enviados: int
    sucursales: list[RecordatorioDeudoresSucursalOut] = Field(default_factory=list)
