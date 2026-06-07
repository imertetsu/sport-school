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
from app.models.disciplina import Disciplina
from app.models.inscripcion import Inscripcion
from app.models.tutor import Tutor
from app.schemas.deportista import DeportistaCreate, DeportistaUpdate, TutorIn


# --------------------------------------------------------------------------- #
# Errores de negocio (el router los traduce a HTTP)
# --------------------------------------------------------------------------- #
class DeportistaError(Exception):
    """Error base de negocio del módulo de Deportistas."""


class CIDuplicado(DeportistaError):
    """Ya existe un deportista con ese CI en la org (índice único parcial) -> 409."""


class DisciplinaInvalida(DeportistaError):
    """`disciplina_id` no existe en el catálogo global o está inactiva -> 422.

    Evita un FK colgante (la FK `deportista.disciplina_id` lo impediría con un
    `IntegrityError` -> 500); el pre-chequeo lo traduce a 422 con mensaje claro.
    """


# --------------------------------------------------------------------------- #
# Validación de `disciplina_id` contra el catálogo GLOBAL (mismo patrón que
# `services/disciplina.get_disciplina_activa_o_error`, que usa categoría en S2).
# `disciplina` es una tabla GLOBAL sin RLS: se consulta directo por id (sin GUC).
# Aquí lanzamos un error de NEGOCIO (no HTTPException) para no acoplar el servicio
# a FastAPI; el router lo traduce a 422.
# --------------------------------------------------------------------------- #
def _validar_disciplina_id(db: Session, disciplina_id: uuid.UUID) -> None:
    """Exige que `disciplina_id` exista en el catálogo y esté activa. Si no, 422.

    Inexistente o inactiva ⇒ `DisciplinaInvalida` (-> 422; nunca 500 por FK colgante).
    La FK es el backstop ante carreras (borrado concurrente de la disciplina).
    """
    disc = db.execute(
        select(Disciplina.activo).where(Disciplina.id == disciplina_id)
    ).scalar_one_or_none()
    if disc is None:
        raise DisciplinaInvalida("La disciplina indicada no existe en el catálogo")
    if not disc:
        raise DisciplinaInvalida("La disciplina indicada está inactiva")


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

    # FK canónica al catálogo (S3): valida ANTES del INSERT para traducir un
    # `disciplina_id` inválido a 422 (no a un IntegrityError genérico de la FK -> 500,
    # ni confundible con la violación del índice único de CI del mismo flush).
    if body.disciplina_id is not None:
        _validar_disciplina_id(db, body.disciplina_id)

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
        disciplina_id=body.disciplina_id,
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


def actualizar_deportista(
    db: Session, deportista: Deportista, body: DeportistaUpdate
) -> Deportista:
    """Actualiza los campos enviados del deportista (no toca tutores en este slice).

    Solo aplica los campos presentes (`exclude_unset`). Si llega `disciplina_id` no nulo,
    se valida contra el catálogo global ANTES del flush (-> 422 si no existe/inactiva,
    evitando un FK colgante / 500). El `ci` no se valida aquí (el slice de edición no
    cambia el dedup; el índice único es el backstop si llegara a tocarse).

    `deportista` debe estar ya cargado bajo el contexto de tenant (RLS). El llamador
    commitea la transacción.
    """
    data = body.model_dump(exclude_unset=True)

    if data.get("disciplina_id") is not None:
        _validar_disciplina_id(db, data["disciplina_id"])

    if "ficha_medica" in data:
        deportista.ficha_medica = data.pop("ficha_medica")  # dict (model_dump) o None
    for field_name, value in data.items():
        setattr(deportista, field_name, value)

    db.flush()
    return deportista
