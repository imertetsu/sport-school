"""Schemas de Avisos (contrato C2).

Formas de request/response **espejo exacto** de C2; frontend-dev tipa contra ellas.
Fechas de caducidad como `date`; `publicado_en` como `datetime` (timestamptz).
`alcance` es ORG|SUCURSAL|CATEGORIA.

La **invariante** (C1) se valida aquí con un `model_validator` (=> 422 en la API),
el server es la fuente de verdad (el frontend no es la única barrera):
- `alcance=SUCURSAL` exige `sucursal_id` (y `categoria_id` nulo),
- `alcance=CATEGORIA` exige `categoria_id` (y `sucursal_id` nulo),
- `alcance=ORG` exige ambos nulos.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, field_validator, model_validator

Alcance = Literal["ORG", "SUCURSAL", "CATEGORIA"]


# --------------------------------------------------------------------------- #
# Invariante compartida (alcance <-> sucursal_id / categoria_id)
# --------------------------------------------------------------------------- #
def validar_invariante(
    alcance: str,
    sucursal_id: uuid.UUID | None,
    categoria_id: uuid.UUID | None,
) -> None:
    """Valida la invariante C1; lanza `ValueError` si no se cumple (=> 422).

    Función pura (sin I/O) reusable desde los schemas y desde el servicio.
    """
    if alcance == "SUCURSAL":
        if sucursal_id is None:
            raise ValueError("alcance=SUCURSAL requiere sucursal_id")
        if categoria_id is not None:
            raise ValueError("alcance=SUCURSAL no admite categoria_id")
    elif alcance == "CATEGORIA":
        if categoria_id is None:
            raise ValueError("alcance=CATEGORIA requiere categoria_id")
        if sucursal_id is not None:
            raise ValueError("alcance=CATEGORIA no admite sucursal_id")
    elif alcance == "ORG":
        if sucursal_id is not None or categoria_id is not None:
            raise ValueError("alcance=ORG no admite sucursal_id ni categoria_id")


# --------------------------------------------------------------------------- #
# Sub-objetos anidados
# --------------------------------------------------------------------------- #
class SucursalRefAviso(BaseModel):
    """Sucursal embebida en un item de aviso (`{id, nombre}`) (C2)."""

    id: uuid.UUID
    nombre: str


class CategoriaRefAviso(BaseModel):
    """Categoría embebida en un item de aviso (`{id, nombre}`) (C2)."""

    id: uuid.UUID
    nombre: str


# --------------------------------------------------------------------------- #
# Alta (POST /avisos)
# --------------------------------------------------------------------------- #
class AvisoCreate(BaseModel):
    """Body de `POST /avisos` (C2).

    `creado_por` NO se acepta del cliente (lo fija el servidor con el usuario del
    token, auditoría RNF-03). `titulo`/`cuerpo` no vacíos -> 422. La invariante
    alcance<->ids se valida con un `model_validator` (=> 422).

    `notificar_entrenadores`/`notificar_tutores` (epic avisos-whatsapp, C2) son flags
    **opt-in** del envío por WhatsApp, **desmarcados por defecto**: si alguno es `true`
    el alta encola el envío en segundo plano (Celery); sin ninguno, el alta se comporta
    exactamente como antes (no encola nada). NO existen en `AvisoUpdate` (editar no
    notifica).
    """

    titulo: str
    cuerpo: str
    alcance: Alcance
    sucursal_id: uuid.UUID | None = None
    categoria_id: uuid.UUID | None = None
    vigente_hasta: date | None = None
    notificar_entrenadores: bool = False
    notificar_tutores: bool = False

    @field_validator("titulo", "cuerpo")
    @classmethod
    def _no_vacio(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("no puede estar vacío")
        return v.strip()

    @model_validator(mode="after")
    def _check_invariante(self) -> AvisoCreate:
        validar_invariante(self.alcance, self.sucursal_id, self.categoria_id)
        return self


class AvisoUpdate(BaseModel):
    """Body de `PUT /avisos/{id}` (C2). Misma validación que el alta.

    Edición completa del aviso (no parcial): el frontend reenvía el aviso entero.
    """

    titulo: str
    cuerpo: str
    alcance: Alcance
    sucursal_id: uuid.UUID | None = None
    categoria_id: uuid.UUID | None = None
    vigente_hasta: date | None = None

    @field_validator("titulo", "cuerpo")
    @classmethod
    def _no_vacio(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("no puede estar vacío")
        return v.strip()

    @model_validator(mode="after")
    def _check_invariante(self) -> AvisoUpdate:
        validar_invariante(self.alcance, self.sucursal_id, self.categoria_id)
        return self


# --------------------------------------------------------------------------- #
# Listado / detalle (GET /avisos, respuesta de POST/PUT)
# --------------------------------------------------------------------------- #
class AvisoOut(BaseModel):
    """Item de `GET /avisos` y respuesta de `POST`/`PUT /avisos` (C2).

    `sucursal`/`categoria` son null salvo que el alcance las use. `vigente_hasta`
    null = sin caducidad; `expirado` = `vigente_hasta < hoy` (false si no caduca).
    `creado_por_nombre` puede ser null.
    """

    id: uuid.UUID
    titulo: str
    cuerpo: str
    alcance: Alcance
    sucursal: SucursalRefAviso | None = None
    categoria: CategoriaRefAviso | None = None
    publicado_en: datetime
    vigente_hasta: date | None = None
    creado_por_nombre: str | None = None
    expirado: bool


class AvisosPage(BaseModel):
    """`GET /avisos` -> `{items, total, page, page_size}` (C2). Orden publicado_en desc."""

    items: list[AvisoOut]
    total: int
    page: int
    page_size: int


# --------------------------------------------------------------------------- #
# Preview de notificación (POST /avisos/notificacion/preview) — C2
# --------------------------------------------------------------------------- #
class PreviewNotificacionIn(BaseModel):
    """Body de `POST /avisos/notificacion/preview` (C2). Cuenta sin enviar.

    Mismos campos de alcance que el alta (misma invariante alcance<->ids, => 422) más
    los flags opt-in: el conteo solo incluye los grupos marcados.
    """

    alcance: Alcance
    sucursal_id: uuid.UUID | None = None
    categoria_id: uuid.UUID | None = None
    notificar_entrenadores: bool = False
    notificar_tutores: bool = False

    @model_validator(mode="after")
    def _check_invariante(self) -> PreviewNotificacionIn:
        validar_invariante(self.alcance, self.sucursal_id, self.categoria_id)
        return self


class PreviewNotificacionOut(BaseModel):
    """Respuesta del preview (C2). Cuenta destinatarios **con** teléfono por grupo.

    `entrenadores`/`tutores` = destinatarios con teléfono de cada grupo marcado (0 si su
    flag está en `false`). `total = entrenadores + tutores`. `sin_telefono` =
    destinatarios resueltos (de los grupos marcados) omitidos por no tener teléfono.
    Dedupe por id aplicado. No inserta ni envía.
    """

    entrenadores: int
    tutores: int
    total: int
    sin_telefono: int
