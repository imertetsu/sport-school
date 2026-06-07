"""Schemas de Horarios (contrato C2 del epic Programación de clases).

Formas de request/response **espejo exacto** de C2; frontend-dev tipa contra
ellas. Horas como `time`. `dia_semana` es 0..6 con **0=Lunes … 6=Domingo**
(= `date.weekday()`); `dia_label` es su nombre en español.

Validaciones (=> 422 en la API; el server es la fuente de verdad):
- `dia_semana` en 0..6,
- `hora_fin > hora_inicio`.
La unicidad `(categoria_id, dia_semana, hora_inicio)` es de BD y se traduce a 409
en el servicio/router (no es un 422 de schema).
"""

from __future__ import annotations

import uuid
from datetime import time

from pydantic import BaseModel, model_validator

# Etiquetas de día (0=Lunes … 6=Domingo, igual que date.weekday()). C2.
DIAS_LABEL: tuple[str, ...] = (
    "Lunes",
    "Martes",
    "Miércoles",
    "Jueves",
    "Viernes",
    "Sábado",
    "Domingo",
)


def dia_label(dia_semana: int) -> str:
    """Nombre en español del día (0=Lunes … 6=Domingo). Función pura.

    Lanza `ValueError` (=> 422) si `dia_semana` está fuera de 0..6.
    """
    if not 0 <= dia_semana <= 6:
        raise ValueError("dia_semana debe estar entre 0 (Lunes) y 6 (Domingo)")
    return DIAS_LABEL[dia_semana]


# --------------------------------------------------------------------------- #
# Sub-objetos anidados (refs)
# --------------------------------------------------------------------------- #
class CategoriaRefHorario(BaseModel):
    """Categoría embebida en un horario (`{id, nombre}`) (C2)."""

    id: uuid.UUID
    nombre: str


class SucursalRefHorario(BaseModel):
    """Sucursal (de la categoría) embebida en un horario (`{id, nombre}`) (C2)."""

    id: uuid.UUID
    nombre: str


class EntrenadorRefHorario(BaseModel):
    """Entrenador embebido en un horario (`{id, nombres}`), o null (C2)."""

    id: uuid.UUID
    nombres: str


# --------------------------------------------------------------------------- #
# Alta / edición (POST/PUT) — valida dia_semana y hora_fin > hora_inicio
# --------------------------------------------------------------------------- #
class HorarioCreate(BaseModel):
    """Body de `POST /horarios` (C2).

    `{categoria_id, dia_semana, hora_inicio, hora_fin, entrenador_id?}`. Valida
    `dia_semana` en 0..6 y `hora_fin > hora_inicio` (=> 422). La unicidad la
    impone la BD (=> 409 en el servicio).
    """

    categoria_id: uuid.UUID
    dia_semana: int
    hora_inicio: time
    hora_fin: time
    entrenador_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _check(self) -> HorarioCreate:
        if not 0 <= self.dia_semana <= 6:
            raise ValueError("dia_semana debe estar entre 0 (Lunes) y 6 (Domingo)")
        if self.hora_fin <= self.hora_inicio:
            raise ValueError("hora_fin debe ser mayor que hora_inicio")
        return self


class HorarioUpdate(BaseModel):
    """Body de `PUT /horarios/{id}` (C2). Misma validación que el alta.

    Edición completa del horario (no parcial): el frontend reenvía el horario
    entero. `activo` se gestiona vía DELETE (soft); no se acepta aquí.
    """

    categoria_id: uuid.UUID
    dia_semana: int
    hora_inicio: time
    hora_fin: time
    entrenador_id: uuid.UUID | None = None

    @model_validator(mode="after")
    def _check(self) -> HorarioUpdate:
        if not 0 <= self.dia_semana <= 6:
            raise ValueError("dia_semana debe estar entre 0 (Lunes) y 6 (Domingo)")
        if self.hora_fin <= self.hora_inicio:
            raise ValueError("hora_fin debe ser mayor que hora_inicio")
        return self


# --------------------------------------------------------------------------- #
# Salida (GET /horarios, respuesta de POST/PUT)
# --------------------------------------------------------------------------- #
class HorarioOut(BaseModel):
    """Item de `GET /horarios` y respuesta de `POST`/`PUT /horarios` (C2).

    `[{id, categoria:{id,nombre}, sucursal:{id,nombre}, dia_semana, dia_label,
    hora_inicio, hora_fin, entrenador:{id,nombres}|null, activo}]`.
    """

    id: uuid.UUID
    categoria: CategoriaRefHorario
    sucursal: SucursalRefHorario
    dia_semana: int
    dia_label: str
    hora_inicio: time
    hora_fin: time
    entrenador: EntrenadorRefHorario | None = None
    activo: bool


# --------------------------------------------------------------------------- #
# Vista semanal (GET /horarios/semana) — rejilla
# --------------------------------------------------------------------------- #
class ClaseSemana(BaseModel):
    """Bloque de clase dentro de un día de la rejilla semanal (C2).

    `{id, categoria:{id,nombre}, sucursal:{id,nombre}, hora_inicio, hora_fin,
    entrenador:{id,nombres}|null}`. `sucursal` (la de la categoría) permite al
    frontend mostrar en qué sede es la clase.
    """

    id: uuid.UUID
    categoria: CategoriaRefHorario
    sucursal: SucursalRefHorario
    hora_inicio: time
    hora_fin: time
    entrenador: EntrenadorRefHorario | None = None


class DiaSemana(BaseModel):
    """Un día de la rejilla (`{dia_semana, dia_label, clases:[...]}`) (C2)."""

    dia_semana: int
    dia_label: str
    clases: list[ClaseSemana]


class SemanaOut(BaseModel):
    """`GET /horarios/semana` -> `{dias:[...]}` con 7 días (0..6) (C2)."""

    dias: list[DiaSemana]
