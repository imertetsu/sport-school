"""Schemas del catálogo de disciplinas (epic Disciplinas, S2).

Dos vistas de salida:
- `DisciplinaOut {id, nombre}`: vista de ESCUELA (`GET /catalogo/disciplinas`), cero
  datos de tenant ni de gestión.
- `DisciplinaAdminOut {id, nombre, activo, created_at}`: vista de SUPERADMIN (consola
  `/plataforma`), incluye el estado y la fecha de alta.

`DisciplinaRef` es el embebido que `CategoriaOut` usa para anidar la disciplina de una
categoría (mismo `{id, nombre}` que `DisciplinaOut`; alias semántico).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class DisciplinaOut(BaseModel):
    """Vista de ESCUELA: solo `{id, nombre}` (catálogo, sin datos de tenant)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    nombre: str


# Alias semántico para el embebido en `CategoriaOut.disciplina` (mismos campos).
DisciplinaRef = DisciplinaOut


class DisciplinaAdminOut(BaseModel):
    """Vista de SUPERADMIN: incluye `activo` y `created_at` (consola `/plataforma`)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    nombre: str
    activo: bool
    created_at: datetime


class DisciplinaCreate(BaseModel):
    """Body de `POST /plataforma/disciplinas`."""

    nombre: str


class DisciplinaUpdate(BaseModel):
    """Body de `PUT /plataforma/disciplinas/{id}` (renombrar y/o activar/desactivar)."""

    nombre: str | None = None
    activo: bool | None = None
