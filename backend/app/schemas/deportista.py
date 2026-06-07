"""Schemas de Deportistas (contrato C5).

Las formas de respuesta (list item, detalle, nested) son **espejo exacto** de C5;
frontend-dev tipa contra ellas. La validación dura (≥1 tutor + consentimiento
obligatorio) vive en `DeportistaCreate` y produce 422 (RF-USR-04 / RNF-02).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator


# --------------------------------------------------------------------------- #
# Sub-objetos anidados
# --------------------------------------------------------------------------- #
class SucursalRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    nombre: str


class CategoriaRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    nombre: str
    nivel: str


class FichaMedica(BaseModel):
    """Estructura del JSONB `ficha_medica` (C1)."""

    tipo_sangre: str | None = None
    alergias: str | None = None
    condiciones: str | None = None


class TutorIn(BaseModel):
    """Tutor en el alta de deportista (C5)."""

    nombres: str
    telefono: str | None = None
    ci: str | None = None
    parentesco: str | None = None
    responsable_pago: bool = False


class TutorOut(BaseModel):
    """Tutor en el detalle del deportista (incluye datos del puente deportista_tutor)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    nombres: str
    telefono: str | None = None
    ci: str | None = None
    parentesco: str | None = None
    responsable_pago: bool = False


class TutorByCiOut(BaseModel):
    """Tutor recuperado por CI (`GET /tutores/por-ci/{ci}`, S3).

    Solo los datos propios del tutor (sin `parentesco`/`responsable_pago`, que viven
    en el puente `deportista_tutor` y dependen del vínculo, no del tutor en sí).
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    nombres: str
    telefono: str | None = None
    ci: str | None = None


class ConsentimientoIn(BaseModel):
    """Consentimiento obligatorio en el alta (C5)."""

    version_terminos: str
    canal: str | None = None


class ConsentimientoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    aceptado_en: datetime
    version_terminos: str
    canal: str | None = None


class InscripcionIn(BaseModel):
    """Inscripción opcional en el alta (C5)."""

    disciplina: str | None = None
    fecha_inscripcion: date
    monto_mensual: Decimal
    modo_cobro: str | None = None
    dia_corte: int | None = None
    estado: str = "ACTIVA"


class InscripcionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    fecha_inscripcion: date
    monto_mensual: Decimal
    disciplina: str | None = None
    estado: str


# --------------------------------------------------------------------------- #
# Create / Update
# --------------------------------------------------------------------------- #
class DeportistaCreate(BaseModel):
    """Body de `POST /deportistas` (C5).

    Validación dura: `tutores` con **≥1** elemento y `consentimiento` obligatorio.
    Pydantic produce 422 si falta cualquiera de los dos.
    """

    sucursal_id: uuid.UUID
    categoria_id: uuid.UUID | None = None
    ap_paterno: str | None = None
    ap_materno: str | None = None
    nombres: str
    ci: str | None = None
    fecha_nac: date | None = None
    disciplina: str | None = None
    contacto_emergencia: str | None = None
    ficha_medica: FichaMedica | None = None

    tutores: list[TutorIn] = Field(..., min_length=1)
    consentimiento: ConsentimientoIn
    inscripcion: InscripcionIn | None = None

    @field_validator("tutores")
    @classmethod
    def _al_menos_un_tutor(cls, value: list[TutorIn]) -> list[TutorIn]:
        if not value:
            raise ValueError("Se requiere al menos un tutor")
        return value


class DeportistaUpdate(BaseModel):
    """Body de `PUT /deportistas/{id}` (C5). No toca tutores en este slice."""

    sucursal_id: uuid.UUID | None = None
    categoria_id: uuid.UUID | None = None
    ap_paterno: str | None = None
    ap_materno: str | None = None
    nombres: str | None = None
    ci: str | None = None
    fecha_nac: date | None = None
    disciplina: str | None = None
    contacto_emergencia: str | None = None
    ficha_medica: FichaMedica | None = None


# --------------------------------------------------------------------------- #
# Respuestas de lista / detalle (formas exactas C5)
# --------------------------------------------------------------------------- #
class DeportistaListItem(BaseModel):
    """Item de `GET /deportistas` (C5)."""

    id: uuid.UUID
    ap_paterno: str | None = None
    ap_materno: str | None = None
    nombres: str
    nombre_completo: str
    ci: str | None = None
    disciplina: str | None = None
    categoria: CategoriaRef | None = None
    sucursal: SucursalRef


class DeportistaDetailOut(BaseModel):
    """Perfil completo de `GET /deportistas/{id}` (C5).

    `ficha_medica` se incluye solo si el rol tiene acceso (RNF-02); si no, `null`.
    """

    id: uuid.UUID
    ap_paterno: str | None = None
    ap_materno: str | None = None
    nombres: str
    nombre_completo: str
    ci: str | None = None
    fecha_nac: date | None = None
    edad: int | None = None
    disciplina: str | None = None
    contacto_emergencia: str | None = None
    sucursal: SucursalRef
    categoria: CategoriaRef | None = None
    inscripcion: InscripcionOut | None = None
    tutores: list[TutorOut]
    consentimiento: ConsentimientoOut | None = None
    ficha_medica: FichaMedica | None = None
