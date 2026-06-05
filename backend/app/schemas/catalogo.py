"""Schemas de catálogos: sucursales y categorías (contrato C5)."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, ConfigDict


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
