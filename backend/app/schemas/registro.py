"""Schemas de Auto-registro (contratos C2/C3) — versión EN SISTEMA.

Captura (autenticada, ADMIN/ENTRENADOR) → cola → aprobación/rechazo (ADMIN). NO
hay token ni nada público. Las formas de respuesta son **espejo exacto** de C2/C3;
frontend-dev tipa contra ellas. La validación dura (consentimiento aceptado + datos
mínimos del tutor) vive en `SolicitudCreate` y produce 422.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, field_validator

from app.schemas.alumno import CategoriaRef, FichaMedica, SucursalRef


# --------------------------------------------------------------------------- #
# Sub-objetos de entrada (captura)
# --------------------------------------------------------------------------- #
class TutorSolicitud(BaseModel):
    """Datos del tutor en la captura (C2). `nombres` obligatorio (dato mínimo)."""

    nombres: str
    telefono: str | None = None
    ci: str | None = None
    parentesco: str | None = None


class ConsentimientoSolicitud(BaseModel):
    """Consentimiento en la captura (C2). `aceptado` debe ser true (422 si no)."""

    aceptado: bool
    version_terminos: str


# --------------------------------------------------------------------------- #
# Create (POST /solicitudes)
# --------------------------------------------------------------------------- #
class SolicitudCreate(BaseModel):
    """Body de `POST /solicitudes` (C2).

    Validación dura: `consentimiento.aceptado` true + `tutor.nombres` no vacío.
    Pydantic produce 422 si falta cualquiera de los dos.
    """

    # Datos del alumno
    ap_paterno: str | None = None
    ap_materno: str | None = None
    nombres: str
    ci: str | None = None
    fecha_nac: date | None = None
    disciplina: str | None = None
    contacto_emergencia: str | None = None
    ficha_medica: FichaMedica | None = None

    # Datos del tutor + consentimiento
    tutor: TutorSolicitud
    consentimiento: ConsentimientoSolicitud

    # Sugerencias (lo administrativo lo decide el admin al aprobar)
    sucursal_sugerida_id: uuid.UUID | None = None
    categoria_sugerida_id: uuid.UUID | None = None

    @field_validator("nombres")
    @classmethod
    def _nombres_no_vacio(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("nombres del alumno es obligatorio")
        return v.strip()

    @field_validator("consentimiento")
    @classmethod
    def _consent_aceptado(cls, v: ConsentimientoSolicitud) -> ConsentimientoSolicitud:
        if not v.aceptado:
            raise ValueError("El consentimiento debe estar aceptado")
        return v

    @field_validator("tutor")
    @classmethod
    def _tutor_minimo(cls, v: TutorSolicitud) -> TutorSolicitud:
        if not v.nombres or not v.nombres.strip():
            raise ValueError("Se requieren datos mínimos del tutor (nombres)")
        return v


# --------------------------------------------------------------------------- #
# Aprobar / Rechazar
# --------------------------------------------------------------------------- #
class AprobarBody(BaseModel):
    """Body de `POST /solicitudes/{id}/aprobar` (C3, solo ADMIN).

    `sucursal_id` obligatorio (lo decide el admin). `monto_mensual` opcional: si
    viene, se crea la inscripción con ese monto.
    """

    sucursal_id: uuid.UUID
    categoria_id: uuid.UUID | None = None
    monto_mensual: Decimal | None = None
    modo_cobro: str | None = None


class RechazarBody(BaseModel):
    """Body de `POST /solicitudes/{id}/rechazar` (C3, solo ADMIN)."""

    motivo: str

    @field_validator("motivo")
    @classmethod
    def _motivo_no_vacio(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("El motivo de rechazo es obligatorio")
        return v.strip()


# --------------------------------------------------------------------------- #
# Salida (cola / detalle)
# --------------------------------------------------------------------------- #
class TutorSolicitudOut(BaseModel):
    """Tutor capturado, tal como se devuelve en la solicitud (C3)."""

    nombres: str
    telefono: str | None = None
    ci: str | None = None
    parentesco: str | None = None


class ConsentimientoSolicitudOut(BaseModel):
    """Consentimiento capturado (C3)."""

    aceptado: bool
    version_terminos: str
    canal: str
    aceptado_en: datetime


class SolicitudOut(BaseModel):
    """`SolicitudOut` (C3): datos enviados + estado + metadatos de revisión.

    `sucursal_sugerida`/`categoria_sugerida` se resuelven a `{id, nombre[, nivel]}`
    (o null). `alumno_id` y `motivo_rechazo` reflejan el resultado de la revisión.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    estado: str

    # Datos del alumno
    ap_paterno: str | None = None
    ap_materno: str | None = None
    nombres: str
    ci: str | None = None
    fecha_nac: date | None = None
    disciplina: str | None = None
    contacto_emergencia: str | None = None
    ficha_medica: FichaMedica | None = None

    # Tutor + consentimiento
    tutor: TutorSolicitudOut
    consentimiento: ConsentimientoSolicitudOut

    # Sugerencias resueltas
    sucursal_sugerida: SucursalRef | None = None
    categoria_sugerida: CategoriaRef | None = None

    # Captura + resultado
    creado_por_nombre: str | None = None
    alumno_id: uuid.UUID | None = None
    motivo_rechazo: str | None = None
    created_at: datetime


class SolicitudesPage(BaseModel):
    """`GET /solicitudes` -> `{items, total, page, page_size}` (C3)."""

    items: list[SolicitudOut]
    total: int
    page: int
    page_size: int
