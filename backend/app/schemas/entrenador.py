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

from app.schemas.disciplina import DisciplinaRef


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
    # CI (documento de identidad), único por org cuando no es NULL (S4). `None` = sin CI.
    ci: str | None = None
    especialidad: str | None = None
    telefono: str | None = None
    # IDs del catálogo GLOBAL de disciplinas (S2) a enlazar (M:N). Reemplaza el antiguo
    # `disciplinas: list[str]` (texto libre). Vacío = sin disciplinas asignadas.
    disciplina_ids: list[uuid.UUID] = Field(default_factory=list)
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
    # CI: `None` = no tocar; string = set + valida unicidad por org (409 si colisiona).
    ci: str | None = None
    especialidad: str | None = None
    telefono: str | None = None
    # `disciplina_ids` (S2, semántica del CONTRATO 3): `None` = no tocar; `[]` = limpiar
    # el set; lista = **REEMPLAZA** el set de disciplinas enlazadas.
    disciplina_ids: list[uuid.UUID] | None = None
    activo: bool | None = None
    password: str | None = Field(default=None, min_length=8)
    sucursal_ids: list[uuid.UUID] | None = None


class EntrenadorOut(BaseModel):
    """Item de `GET /entrenadores` y respuesta de `POST`/`PUT` (contrato B).

    `email`/`activo` provienen del `usuario` ligado (join por `usuario_id`).
    `telefono` y `sucursal_ids` (asignación M:N) del epic Recordatorio de deudores.
    `ci` (S4) único por org. `disciplinas` son **refs al catálogo** (`{id, nombre}`),
    resueltas del join `entrenador_disciplina ⨝ disciplina` (S4, ya no texto libre).
    """

    id: uuid.UUID
    usuario_id: uuid.UUID
    nombres: str
    email: str
    ci: str | None = None
    especialidad: str | None = None
    telefono: str | None = None
    disciplinas: list[DisciplinaRef] = Field(default_factory=list)
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
