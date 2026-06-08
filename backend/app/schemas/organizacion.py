"""Schemas de `/mi-escuela` (contrato C2, epic escuela-y-bajas).

Solo `nombre` + `color` del monograma (sin logo de archivo, RNF-02). El router
(Fase 1) scopea SIEMPRE a `user.org_id` server-side e ignora cualquier id del
cliente; `organizacion` no tiene RLS, así que el guardián es el endpoint.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict, field_validator

# Color del monograma: `#RRGGBB` (hex de 6 dígitos). Vacío/None ⇒ el front usa
# un default determinista (no se persiste cadena vacía: se normaliza a None).
_HEX_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}$")


class MiEscuelaOut(BaseModel):
    """Respuesta de `GET /mi-escuela` y `PUT /mi-escuela` (C2)."""

    model_config = ConfigDict(from_attributes=True)

    nombre: str
    color: str | None = None


class MiEscuelaUpdate(BaseModel):
    """Body de `PUT /mi-escuela` (C2). Validación server-side, no confiar en la UI."""

    nombre: str
    color: str | None = None

    @field_validator("nombre")
    @classmethod
    def _nombre_no_vacio(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("El nombre de la escuela es obligatorio")
        return v.strip()

    @field_validator("color")
    @classmethod
    def _color_valido(cls, v: str | None) -> str | None:
        # Vacío/None ⇒ None (el front usa default determinista).
        if v is None or not v.strip():
            return None
        v = v.strip()
        if not _HEX_COLOR.match(v):
            raise ValueError("El color debe tener formato #RRGGBB")
        return v
