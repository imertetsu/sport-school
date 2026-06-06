"""Modelos SQLAlchemy.

Importa `Base` y **TODOS** los modelos para que `Base.metadata` quede completo.
db-dev hace `from app.models import Base` y autogenera la migración a partir de
`Base.metadata`; si un modelo no se importa aquí, no aparecerá en el esquema.
"""

from __future__ import annotations

from app.models.alumno import Alumno
from app.models.alumno_tutor import AlumnoTutor
from app.models.asistencia import Asistencia
from app.models.aviso import Aviso
from app.models.base import Base
from app.models.categoria import Categoria
from app.models.conciliacion_pendiente import ConciliacionPendiente
from app.models.consentimiento import Consentimiento
from app.models.credito import Credito
from app.models.cuota import Cuota
from app.models.egreso import Egreso
from app.models.entrenador import Entrenador
from app.models.horario_clase import HorarioClase
from app.models.inscripcion import Inscripcion
from app.models.organizacion import Organizacion
from app.models.pago import Pago
from app.models.pago_cuota import PagoCuota
from app.models.sesion import Sesion
from app.models.solicitud_registro import SolicitudRegistro
from app.models.sucursal import Sucursal
from app.models.tutor import Tutor
from app.models.usuario import Usuario

__all__ = [
    "Base",
    "Organizacion",
    "Usuario",
    "Sucursal",
    "Categoria",
    "Entrenador",
    "Alumno",
    "Tutor",
    "AlumnoTutor",
    "Consentimiento",
    "Inscripcion",
    "Cuota",
    "Pago",
    "PagoCuota",
    "Credito",
    "ConciliacionPendiente",
    "Sesion",
    "Asistencia",
    "Egreso",
    "Aviso",
    "HorarioClase",
    "SolicitudRegistro",
]
