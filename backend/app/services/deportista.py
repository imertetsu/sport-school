"""Servicio de Deportistas (C5) — crea deportista+tutores+puente+consentimiento[+inscripción].

Factorizado del router `app/api/v1/deportistas.py` para poder **reutilizar** la creación
del deportista desde otros flujos (p. ej. aprobar una `solicitud_registro` del epic de
auto-registro) sin duplicar la lógica ni romper la validación dura (≥1 tutor +
consentimiento obligatorio, RNF-02).

Corre SIEMPRE con `app.current_org` ya fijado por el llamador (RLS es la barrera
real, no `WHERE org_id`). No se salta el contexto de tenant.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.consentimiento import Consentimiento
from app.models.deportista import Deportista
from app.models.deportista_tutor import DeportistaTutor
from app.models.inscripcion import Inscripcion
from app.models.tutor import Tutor
from app.schemas.deportista import DeportistaCreate, TutorIn


# --------------------------------------------------------------------------- #
# Errores de negocio (el router los traduce a HTTP)
# --------------------------------------------------------------------------- #
class DeportistaError(Exception):
    """Error base de negocio del módulo de Deportistas."""


class CIDuplicado(DeportistaError):
    """Ya existe un deportista con ese CI en la org (índice único parcial) -> 409."""


# --------------------------------------------------------------------------- #
# Lookup por CI (recuperar-por-CI; corre bajo `app.current_org` ya fijado, RLS)
# --------------------------------------------------------------------------- #
def buscar_deportista_por_ci(db: Session, ci: str) -> Deportista | None:
    """Devuelve el deportista de la org del contexto con ese CI, o None.

    Scoped por org vía RLS (no se filtra por `org_id` en Python; la barrera real es
    RLS). El índice único parcial `(org_id, ci) WHERE ci IS NOT NULL` garantiza a lo
    sumo una fila por CI dentro de la org.
    """
    return db.execute(select(Deportista).where(Deportista.ci == ci)).scalar_one_or_none()


def buscar_tutor_por_ci(db: Session, ci: str) -> Tutor | None:
    """Devuelve el tutor de la org del contexto con ese CI, o None (scoped por RLS)."""
    return db.execute(select(Tutor).where(Tutor.ci == ci)).scalar_one_or_none()


# --------------------------------------------------------------------------- #
# Reutilizar/crear tutor (recuperar-por-CI + actualizar teléfono, contrato #4)
# --------------------------------------------------------------------------- #
def _resolver_tutor(db: Session, t: TutorIn, *, org_id: uuid.UUID) -> Tutor:
    """Reutiliza un tutor existente por CI (en la org) o crea uno nuevo.

    Contrato #4: si el `ci` del tutor coincide con uno existente de la org, se
    **reusa** ese tutor (sin duplicar) y se **actualiza su teléfono** con el valor
    entrante (solo si viene). El CI del tutor es OPCIONAL: si no viene CI, siempre se
    crea un tutor nuevo (múltiples `ci IS NULL` permitidos por el índice parcial).
    """
    if t.ci:
        existente = buscar_tutor_por_ci(db, t.ci)
        if existente is not None:
            if t.telefono:
                existente.telefono = t.telefono
            db.flush()
            return existente

    tutor = Tutor(org_id=org_id, nombres=t.nombres, telefono=t.telefono, ci=t.ci)
    db.add(tutor)
    db.flush()
    return tutor


def crear_deportista(db: Session, body: DeportistaCreate, *, org_id: uuid.UUID) -> Deportista:
    """Crea deportista + tutores + puente + consentimiento (+inscripción) (C5).

    La validación dura (≥1 tutor + consentimiento) la garantiza `DeportistaCreate`
    (Pydantic => 422 antes de llegar aquí). Devuelve el `Deportista` creado (ya con
    `id` tras el `flush`). El llamador es responsable de commitear la transacción.

    Dedup por CI (contrato S3): si `ci` ya existe en la org, el índice único parcial
    lanza `IntegrityError`; lo traducimos a `CIDuplicado` (-> 409, RNF-06: no se
    descarta el dato silenciosamente). Pre-chequeo proactivo dentro de la org para un
    mejor mensaje; el `IntegrityError` es el backstop (carrera).
    """
    if body.ci and buscar_deportista_por_ci(db, body.ci) is not None:
        raise CIDuplicado("Ya existe un deportista con ese CI en esta organización")

    deportista = Deportista(
        org_id=org_id,
        sucursal_id=body.sucursal_id,
        categoria_id=body.categoria_id,
        ap_paterno=body.ap_paterno,
        ap_materno=body.ap_materno,
        nombres=body.nombres,
        ci=body.ci,
        fecha_nac=body.fecha_nac,
        disciplina=body.disciplina,
        contacto_emergencia=body.contacto_emergencia,
        ficha_medica=(body.ficha_medica.model_dump() if body.ficha_medica else None),
    )
    db.add(deportista)
    try:
        db.flush()  # fuerza el INSERT para detectar la violación del índice único parcial
    except IntegrityError as exc:
        db.rollback()
        raise CIDuplicado("Ya existe un deportista con ese CI en esta organización") from exc

    # Tutores + puente. Consentimiento se ata al primer tutor (responsable).
    # Recuperar-por-CI: un tutor con CI ya existente se REUSA (no se duplica) y se le
    # actualiza el teléfono entrante (contrato #4).
    primer_tutor_id: uuid.UUID | None = None
    for t in body.tutores:
        tutor = _resolver_tutor(db, t, org_id=org_id)
        if primer_tutor_id is None:
            primer_tutor_id = tutor.id
        db.add(
            DeportistaTutor(
                org_id=org_id,
                deportista_id=deportista.id,
                tutor_id=tutor.id,
                parentesco=t.parentesco,
                responsable_pago=t.responsable_pago,
            )
        )

    assert primer_tutor_id is not None  # garantizado por min_length=1
    db.add(
        Consentimiento(
            org_id=org_id,
            tutor_id=primer_tutor_id,
            deportista_id=deportista.id,
            version_terminos=body.consentimiento.version_terminos,
            canal=body.consentimiento.canal,
            aceptado_en=datetime.now(UTC),
        )
    )

    if body.inscripcion is not None:
        ins = body.inscripcion
        db.add(
            Inscripcion(
                org_id=org_id,
                deportista_id=deportista.id,
                disciplina=ins.disciplina,
                fecha_inscripcion=ins.fecha_inscripcion,
                monto_mensual=ins.monto_mensual,
                modo_cobro=ins.modo_cobro,
                dia_corte=ins.dia_corte,
                estado=ins.estado,
            )
        )

    db.flush()
    return deportista
