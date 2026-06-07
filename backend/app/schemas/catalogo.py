"""Schemas de catálogos: sucursales y categorías (contrato C5)."""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.schemas.disciplina import DisciplinaRef

# Niveles válidos de categoría. EXACTOS al CHECK `ck_categoria_nivel` de la
# migración 0001 (`nivel IN ('PRINCIPIANTE','INTERMEDIO','AVANZADO')`); un valor
# fuera de este conjunto se rechaza en el schema (422) antes de tocar la BD.
NivelCategoria = Literal["PRINCIPIANTE", "INTERMEDIO", "AVANZADO"]


class SucursalOut(BaseModel):
    """Item de `GET /sucursales` -> `[{id, nombre, direccion}]`."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    nombre: str
    direccion: str | None = None


class CategoriaOut(BaseModel):
    """Item de `GET /categorias?sucursal_id=` -> incluye nivel, rango_edad, sucursal_id."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    nombre: str
    nivel: str
    rango_edad: str | None = None
    sucursal_id: uuid.UUID
    # Catálogo GLOBAL de disciplinas (epic Disciplinas, S2). `disciplina_id` es la FK
    # cruda; `disciplina` es el embebido `{id, nombre}` (poblado desde la relación, o
    # None si la categoría no tiene disciplina asignada).
    disciplina_id: uuid.UUID | None = None
    disciplina: DisciplinaRef | None = None


# --------------------------------------------------------------------------- #
# CRUD ADMIN (epic Sucursales/Categorías). Solo entrada; la salida reusa
# `SucursalOut`/`CategoriaOut`.
# --------------------------------------------------------------------------- #
class SucursalCreate(BaseModel):
    """Cuerpo de `POST /sucursales` (ADMIN)."""

    nombre: str
    direccion: str | None = None


class SucursalUpdate(BaseModel):
    """Cuerpo de `PUT /sucursales/{id}` (ADMIN)."""

    nombre: str
    direccion: str | None = None


class CategoriaCreate(BaseModel):
    """Cuerpo de `POST /categorias` (ADMIN). `sucursal_id` se fija al crear."""

    nombre: str
    nivel: NivelCategoria
    rango_edad: str | None = None
    sucursal_id: uuid.UUID
    # Opcional: vincula la categoría a una disciplina del catálogo global (debe existir
    # y estar activa; el router valida → 404/422). None = sin disciplina.
    disciplina_id: uuid.UUID | None = None


class CategoriaUpdate(BaseModel):
    """Cuerpo de `PUT /categorias/{id}` (ADMIN). `sucursal_id` NO es editable."""

    nombre: str
    nivel: NivelCategoria
    rango_edad: str | None = None
    disciplina_id: uuid.UUID | None = None
