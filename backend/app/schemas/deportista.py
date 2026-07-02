"""Schemas de Deportistas (contrato C5).

Las formas de respuesta (list item, detalle, nested) son **espejo exacto** de C5;
frontend-dev tipa contra ellas. La validación dura (≥1 tutor + consentimiento
obligatorio) vive en `DeportistaCreate` y produce 422 (RF-USR-04 / RNF-02).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, field_validator


# CI opcional normalizado: vacío/solo-espacios -> None (NUNCA cadena vacía '', que el
# índice único parcial `WHERE ci IS NOT NULL` SÍ indexaría y haría colisionar a dos
# registros "en blanco"). Se recorta y se conserva "0" (placeholder "presentará
# luego", no-único por diseño). Aplica a deportista y tutor en alta/edición.
def _ci_a_none_si_vacio(v: object) -> object:
    if isinstance(v, str):
        return v.strip() or None
    return v


CiOpcional = Annotated[str | None, BeforeValidator(_ci_a_none_si_vacio)]


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
    ci: CiOpcional = None
    parentesco: str | None = None
    responsable_pago: bool = False


class TutorUpsert(BaseModel):
    """Tutor en la edición completa de deportista (C3, epic escuela-y-bajas).

    Como `TutorIn` + `id: UUID | None`. La lista es **reconciliable por id**:
    con `id` ⇒ edita el vínculo/tutor existente; sin `id` ⇒ alta/recupera-por-CI.
    Para desvincular un tutor se omite de la lista entrante. El invariante de
    menores (≥1 tutor, no quitar el del consentimiento) se valida server-side
    en el servicio (Fase 3), no aquí.
    """

    id: uuid.UUID | None = None
    nombres: str
    telefono: str | None = None
    ci: CiOpcional = None
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
    # CI del DEPORTISTA: OPCIONAL (se puede dejar vacío -> null cuando aún no se tiene
    # el documento). Vacío se normaliza a None (no ''), y "0" sigue admitido como
    # placeholder "presentará luego". El índice único parcial excluye NULL y '0', así
    # que varios deportistas sin CI no colisionan.
    ci: CiOpcional = None
    fecha_nac: date | None = None
    # Texto LEGACY (se conserva, S2): disciplina escrita a mano.
    disciplina: str | None = None
    # FK canónica al catálogo GLOBAL de disciplinas (S3). Debe existir y estar activa
    # (el servicio valida → 422). None = sin disciplina del catálogo.
    disciplina_id: uuid.UUID | None = None
    contacto_emergencia: str | None = None
    domicilio: str | None = None
    lugar_nacimiento: str | None = None
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
    """Body de `PUT /deportistas/{id}` (C5 + C3).

    `tutores` es opcional (C3): si **no viene** (None), NO se tocan los tutores
    (preserva el comportamiento actual); si viene, la lista es reconciliable por
    id. El invariante de menores se valida server-side en el servicio (Fase 3).
    """

    sucursal_id: uuid.UUID | None = None
    categoria_id: uuid.UUID | None = None
    ap_paterno: str | None = None
    ap_materno: str | None = None
    nombres: str | None = None
    ci: CiOpcional = None
    fecha_nac: date | None = None
    disciplina: str | None = None
    disciplina_id: uuid.UUID | None = None
    contacto_emergencia: str | None = None
    domicilio: str | None = None
    lugar_nacimiento: str | None = None
    ficha_medica: FichaMedica | None = None
    tutores: list[TutorUpsert] | None = None
    # Inscripción (cobro) — epic motor de cuotas. Si viene, se hace UPSERT: crea la
    # inscripción si el deportista no tenía (caso de los registrados sin cobro, p. ej.
    # auto-registro) o actualiza la existente. Si NO viene (None / ausente), no se toca.
    inscripcion: InscripcionIn | None = None


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
    disciplina_id: uuid.UUID | None = None
    categoria: CategoriaRef | None = None
    sucursal: SucursalRef
    activo: bool


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
    disciplina_id: uuid.UUID | None = None
    contacto_emergencia: str | None = None
    domicilio: str | None = None
    lugar_nacimiento: str | None = None
    sucursal: SucursalRef
    categoria: CategoriaRef | None = None
    inscripcion: InscripcionOut | None = None
    tutores: list[TutorOut]
    consentimiento: ConsentimientoOut | None = None
    ficha_medica: FichaMedica | None = None
    activo: bool
