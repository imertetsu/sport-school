"""Schemas de Asistencia (contrato C2).

Formas de request/response **espejo exacto** de C2; frontend-dev tipa contra
ellas. Fechas como `date`; horas como `time`. `estado` es PRESENTE|AUSENTE (o
`null` por deportista cuando todavía no hay sesión guardada).
"""

from __future__ import annotations

import uuid
from datetime import date, time
from typing import Literal

from pydantic import BaseModel, Field

Estado = Literal["PRESENTE", "AUSENTE"]


# --------------------------------------------------------------------------- #
# Sub-objetos anidados
# --------------------------------------------------------------------------- #
class SucursalRefAsistencia(BaseModel):
    """Sucursal embebida en la categoría visible del entrenador (C2)."""

    id: uuid.UUID
    nombre: str


class CategoriaAsistencia(BaseModel):
    """Item de `GET /asistencia/categorias` (C2).

    `[{id, nombre, nivel, sucursal:{id,nombre}, total_deportistas}]`.
    """

    id: uuid.UUID
    nombre: str
    nivel: str
    sucursal: SucursalRefAsistencia
    total_deportistas: int


class CategoriaRefAsistencia(BaseModel):
    """Categoría minimal embebida en el roster (`{id, nombre}`) (C2)."""

    id: uuid.UUID
    nombre: str


# --------------------------------------------------------------------------- #
# Roster (GET /asistencia/roster)
# --------------------------------------------------------------------------- #
class RosterItem(BaseModel):
    """Fila del roster: deportista + su estado (null si aún no hay sesión) (C2)."""

    deportista_id: uuid.UUID
    nombre_completo: str
    estado: Estado | None = None


class Resumen(BaseModel):
    """Contadores del roster/guardado: `{presentes, ausentes, total}` (C2)."""

    presentes: int
    ausentes: int
    total: int


class RosterOut(BaseModel):
    """`GET /asistencia/roster` / respuesta de `POST /asistencia/guardar` (C2).

    `sesion_id` es null cuando todavía no se ha guardado ninguna asistencia para
    la categoría+fecha (get-or-create lógico: no crea la sesión hasta guardar).
    """

    sesion_id: uuid.UUID | None = None
    categoria: CategoriaRefAsistencia
    fecha: date
    items: list[RosterItem]
    resumen: Resumen


# --------------------------------------------------------------------------- #
# Guardar (POST /asistencia/guardar)
# --------------------------------------------------------------------------- #
class MarcaIn(BaseModel):
    """Una marca por deportista en el body de guardado (C2)."""

    deportista_id: uuid.UUID
    estado: Estado


class GuardarBody(BaseModel):
    """Body de `POST /asistencia/guardar` (C2).

    `{categoria_id, fecha, hora?, marcas:[{deportista_id, estado}]}`. Idempotente:
    crea la sesión si no existe (por categoria+fecha+hora) y hace upsert de las
    marcas por (sesion_id, deportista_id).
    """

    categoria_id: uuid.UUID
    fecha: date
    hora: time | None = None
    # Filtro de disciplina activo en la vista: el roster devuelto se acota igual.
    disciplina_id: uuid.UUID | None = None
    marcas: list[MarcaIn] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Historial (GET /asistencia/sesiones)
# --------------------------------------------------------------------------- #
class SesionHistorialItem(BaseModel):
    """Item de `GET /asistencia/sesiones` (C2)."""

    id: uuid.UUID
    fecha: date
    hora: time | None = None
    presentes: int
    ausentes: int
    total: int


class SesionesPage(BaseModel):
    """`GET /asistencia/sesiones` -> `{items, total, page, page_size}` (C2)."""

    items: list[SesionHistorialItem]
    total: int
    page: int
    page_size: int
