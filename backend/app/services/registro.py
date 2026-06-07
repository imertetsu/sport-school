"""Servicio de Auto-registro (C2/C3) — versión EN SISTEMA.

Captura autenticada (ADMIN/ENTRENADOR) → cola PENDIENTE → el ADMIN aprueba
(crea el deportista real **reutilizando** `app/services/deportista.py`) o rechaza.

Reglas de dominio (con I/O; corre SIEMPRE con `app.current_org` ya fijado por el
llamador, RLS es la barrera real):
- **crear**: `creado_por` = usuario del token. Si el capturador es ENTRENADOR y
  manda `sucursal_sugerida_id`, esa sucursal debe estar en sus `sucursal_ids`
  (→ `SucursalFuera`, 403). La validación dura (consentimiento aceptado + datos
  mínimos del tutor) la garantiza el schema (422 antes de llegar aquí).
- **listar (cola)**: ADMIN ve todas las de la org; ENTRENADOR solo las de sus
  sucursales sugeridas (lo que capturó). Filtro opcional por `estado`.
- **aprobar (solo ADMIN)**: idempotencia/estado — 409 si la solicitud ya está
  resuelta (APROBADA/RECHAZADA). Crea el deportista reutilizando la lógica de Deportistas
  (deportista+tutor+puente+consentimiento; +inscripción si `monto_mensual`), marca
  `APROBADA` + `deportista_id` + `revisado_por`/`revisado_en`.
- **rechazar (solo ADMIN)**: 409 si ya resuelta; marca `RECHAZADA` + motivo +
  `revisado_por`/`revisado_en`.

No se salta el contexto de tenant (RLS). El gateo por rol (solo ADMIN aprueba/
rechaza) lo hace el router vía `require_role`; aquí se aplica el scoping por
sucursal del entrenador en la captura/cola.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.categoria import Categoria
from app.models.deportista import Deportista
from app.models.solicitud_registro import SolicitudRegistro
from app.models.sucursal import Sucursal
from app.models.usuario import Usuario
from app.schemas.deportista import (
    CategoriaRef,
    ConsentimientoIn,
    DeportistaCreate,
    FichaMedica,
    InscripcionIn,
    SucursalRef,
    TutorIn,
)
from app.schemas.registro import (
    AprobarBody,
    ConsentimientoSolicitudOut,
    RechazarBody,
    SolicitudCreate,
    SolicitudOut,
    TutorSolicitudOut,
)
from app.services import deportista as deportista_svc

ESTADO_PENDIENTE = "PENDIENTE"
ESTADO_APROBADA = "APROBADA"
ESTADO_RECHAZADA = "RECHAZADA"


# --------------------------------------------------------------------------- #
# Errores de negocio (el router los traduce a HTTP)
# --------------------------------------------------------------------------- #
class RegistroError(Exception):
    """Error base de negocio del módulo de auto-registro."""


class SolicitudNoEncontrada(RegistroError):
    """La solicitud no existe en la org del contexto -> 404."""


class SucursalFuera(RegistroError):
    """La sucursal sugerida está fuera del alcance del entrenador -> 403."""


class SolicitudYaResuelta(RegistroError):
    """La solicitud ya está APROBADA/RECHAZADA -> 409 (idempotencia)."""


# --------------------------------------------------------------------------- #
# Scoping por rol
# --------------------------------------------------------------------------- #
def _sucursales_permitidas(role: str, sucursal_ids: list[str]) -> set[uuid.UUID] | None:
    """Conjunto de sucursales que el rol puede ver, o `None` si ve todas (ADMIN).

    ENTRENADOR queda limitado a sus `sucursal_ids` del token (mismo criterio que
    asistencia/ficha médica). Cualquier otro rol no-ADMIN: sin sucursales.
    """
    if role == "ADMIN":
        return None
    permitidas: set[uuid.UUID] = set()
    for s in sucursal_ids:
        try:
            permitidas.add(uuid.UUID(s))
        except (ValueError, TypeError):
            continue
    return permitidas


# --------------------------------------------------------------------------- #
# Crear (captura)
# --------------------------------------------------------------------------- #
def crear(
    db: Session,
    body: SolicitudCreate,
    *,
    org_id: uuid.UUID,
    creado_por: uuid.UUID,
    role: str,
    sucursal_ids: list[str],
) -> SolicitudRegistro:
    """Crea una `solicitud_registro` PENDIENTE en la org del usuario (C2).

    La validación dura (consentimiento aceptado + tutor mínimo) ya la garantiza
    `SolicitudCreate` (422). Aquí solo aplicamos el scoping del entrenador sobre
    `sucursal_sugerida_id` (403 si está fuera de sus sucursales).
    """
    permitidas = _sucursales_permitidas(role, sucursal_ids)
    if (
        permitidas is not None
        and body.sucursal_sugerida_id is not None
        and body.sucursal_sugerida_id not in permitidas
    ):
        raise SucursalFuera("La sucursal sugerida está fuera de tu alcance")

    solicitud = SolicitudRegistro(
        org_id=org_id,
        estado=ESTADO_PENDIENTE,
        ap_paterno=body.ap_paterno,
        ap_materno=body.ap_materno,
        nombres=body.nombres,
        ci=body.ci,
        fecha_nac=body.fecha_nac,
        disciplina=body.disciplina,
        contacto_emergencia=body.contacto_emergencia,
        ficha_medica=(body.ficha_medica.model_dump() if body.ficha_medica else None),
        tutor_nombres=body.tutor.nombres,
        tutor_telefono=body.tutor.telefono,
        tutor_ci=body.tutor.ci,
        parentesco=body.tutor.parentesco,
        consent_version=body.consentimiento.version_terminos,
        consent_canal="SISTEMA",
        consent_aceptado_en=datetime.now(UTC),
        sucursal_sugerida_id=body.sucursal_sugerida_id,
        categoria_sugerida_id=body.categoria_sugerida_id,
        creado_por=creado_por,
    )
    db.add(solicitud)
    db.flush()
    return solicitud


# --------------------------------------------------------------------------- #
# Listar (cola) / obtener
# --------------------------------------------------------------------------- #
def listar(
    db: Session,
    *,
    role: str,
    sucursal_ids: list[str],
    estado: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[SolicitudRegistro], int]:
    """Cola de solicitudes scoped por rol (C3).

    ADMIN: todas las de la org. ENTRENADOR: solo las de sus sucursales sugeridas.
    Filtro opcional por `estado`. Devuelve `(items, total)` ordenado por más
    recientes primero.
    """
    base = select(SolicitudRegistro)
    if estado:
        base = base.where(SolicitudRegistro.estado == estado)

    permitidas = _sucursales_permitidas(role, sucursal_ids)
    if permitidas is not None:
        if not permitidas:
            return [], 0
        base = base.where(SolicitudRegistro.sucursal_sugerida_id.in_(permitidas))

    total = db.execute(select(func.count()).select_from(base.subquery())).scalar_one()
    rows = list(
        db.execute(
            base.order_by(SolicitudRegistro.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        .scalars()
        .all()
    )
    return rows, int(total)


def obtener(
    db: Session,
    solicitud_id: uuid.UUID,
    *,
    role: str,
    sucursal_ids: list[str],
) -> SolicitudRegistro:
    """Carga una solicitud aplicando el scoping por rol (C3).

    404 si no existe en la org del contexto o si el entrenador no tiene acceso a
    su sucursal sugerida (no revela su existencia fuera de su alcance).
    """
    solicitud = db.execute(
        select(SolicitudRegistro).where(SolicitudRegistro.id == solicitud_id)
    ).scalar_one_or_none()
    if solicitud is None:
        raise SolicitudNoEncontrada("Solicitud no encontrada")

    permitidas = _sucursales_permitidas(role, sucursal_ids)
    if permitidas is not None and (
        solicitud.sucursal_sugerida_id is None or solicitud.sucursal_sugerida_id not in permitidas
    ):
        raise SolicitudNoEncontrada("Solicitud no encontrada")
    return solicitud


# --------------------------------------------------------------------------- #
# Aprobar (solo ADMIN; reutiliza la creación de deportista)
# --------------------------------------------------------------------------- #
def aprobar(
    db: Session,
    solicitud_id: uuid.UUID,
    body: AprobarBody,
    *,
    org_id: uuid.UUID,
    revisado_por: uuid.UUID,
) -> Deportista:
    """Aprueba una solicitud: crea el deportista real y la marca APROBADA (C3).

    409 si la solicitud ya está resuelta (idempotencia de estado). Reutiliza
    `deportista_svc.crear_deportista` (deportista+tutor+puente+consentimiento; +inscripción si
    `monto_mensual`). El gateo a solo-ADMIN lo hace el router (`require_role`).
    """
    solicitud = db.execute(
        select(SolicitudRegistro).where(SolicitudRegistro.id == solicitud_id)
    ).scalar_one_or_none()
    if solicitud is None:
        raise SolicitudNoEncontrada("Solicitud no encontrada")
    if solicitud.estado != ESTADO_PENDIENTE:
        raise SolicitudYaResuelta(f"La solicitud ya está {solicitud.estado}")

    # Reconstruir el body de creación de deportista desde la solicitud + decisiones del admin.
    ficha = FichaMedica(**solicitud.ficha_medica) if solicitud.ficha_medica else None
    inscripcion = None
    if body.monto_mensual is not None:
        inscripcion = InscripcionIn(
            disciplina=solicitud.disciplina,
            fecha_inscripcion=datetime.now(UTC).date(),
            monto_mensual=body.monto_mensual,
            modo_cobro=body.modo_cobro,
            dia_corte=None,
            estado="ACTIVA",
        )

    deportista_create = DeportistaCreate(
        sucursal_id=body.sucursal_id,
        categoria_id=body.categoria_id,
        ap_paterno=solicitud.ap_paterno,
        ap_materno=solicitud.ap_materno,
        nombres=solicitud.nombres,
        ci=solicitud.ci,
        fecha_nac=solicitud.fecha_nac,
        disciplina=solicitud.disciplina,
        contacto_emergencia=solicitud.contacto_emergencia,
        ficha_medica=ficha,
        tutores=[
            TutorIn(
                nombres=solicitud.tutor_nombres,
                telefono=solicitud.tutor_telefono,
                ci=solicitud.tutor_ci,
                parentesco=solicitud.parentesco,
                responsable_pago=True,
            )
        ],
        consentimiento=ConsentimientoIn(
            version_terminos=solicitud.consent_version,
            canal=solicitud.consent_canal,
        ),
        inscripcion=inscripcion,
    )

    deportista = deportista_svc.crear_deportista(db, deportista_create, org_id=org_id)

    solicitud.estado = ESTADO_APROBADA
    solicitud.deportista_id = deportista.id
    solicitud.revisado_por = revisado_por
    solicitud.revisado_en = datetime.now(UTC)
    db.flush()
    return deportista


# --------------------------------------------------------------------------- #
# Rechazar (solo ADMIN)
# --------------------------------------------------------------------------- #
def rechazar(
    db: Session,
    solicitud_id: uuid.UUID,
    body: RechazarBody,
    *,
    revisado_por: uuid.UUID,
) -> SolicitudRegistro:
    """Rechaza una solicitud PENDIENTE con motivo (C3).

    409 si ya está resuelta. Marca RECHAZADA + `motivo_rechazo` +
    `revisado_por`/`revisado_en`. El gateo a solo-ADMIN lo hace el router.
    """
    solicitud = db.execute(
        select(SolicitudRegistro).where(SolicitudRegistro.id == solicitud_id)
    ).scalar_one_or_none()
    if solicitud is None:
        raise SolicitudNoEncontrada("Solicitud no encontrada")
    if solicitud.estado != ESTADO_PENDIENTE:
        raise SolicitudYaResuelta(f"La solicitud ya está {solicitud.estado}")

    solicitud.estado = ESTADO_RECHAZADA
    solicitud.motivo_rechazo = body.motivo
    solicitud.revisado_por = revisado_por
    solicitud.revisado_en = datetime.now(UTC)
    db.flush()
    return solicitud


# --------------------------------------------------------------------------- #
# Mapeo a salida (SolicitudOut) con refs resueltas
# --------------------------------------------------------------------------- #
def to_out(db: Session, solicitudes: list[SolicitudRegistro]) -> list[SolicitudOut]:
    """Mapea solicitudes a `SolicitudOut`, resolviendo sucursal/categoría/creador.

    Precarga las referencias (sucursal, categoría, usuario creador) para evitar
    N+1. Las refs ausentes quedan en `null`.
    """
    if not solicitudes:
        return []

    suc_ids = {s.sucursal_sugerida_id for s in solicitudes if s.sucursal_sugerida_id}
    cat_ids = {s.categoria_sugerida_id for s in solicitudes if s.categoria_sugerida_id}
    user_ids = {s.creado_por for s in solicitudes if s.creado_por}

    sucursales = (
        {
            s.id: s
            for s in db.execute(select(Sucursal).where(Sucursal.id.in_(suc_ids))).scalars().all()
        }
        if suc_ids
        else {}
    )
    categorias = (
        {
            c.id: c
            for c in db.execute(select(Categoria).where(Categoria.id.in_(cat_ids))).scalars().all()
        }
        if cat_ids
        else {}
    )
    nombres_usuario = (
        {
            u.id: u.nombre
            for u in db.execute(select(Usuario).where(Usuario.id.in_(user_ids))).scalars().all()
        }
        if user_ids
        else {}
    )

    out: list[SolicitudOut] = []
    for s in solicitudes:
        suc = sucursales.get(s.sucursal_sugerida_id) if s.sucursal_sugerida_id else None
        cat = categorias.get(s.categoria_sugerida_id) if s.categoria_sugerida_id else None
        out.append(
            SolicitudOut(
                id=s.id,
                estado=s.estado,
                ap_paterno=s.ap_paterno,
                ap_materno=s.ap_materno,
                nombres=s.nombres,
                ci=s.ci,
                fecha_nac=s.fecha_nac,
                disciplina=s.disciplina,
                contacto_emergencia=s.contacto_emergencia,
                ficha_medica=FichaMedica(**s.ficha_medica) if s.ficha_medica else None,
                tutor=TutorSolicitudOut(
                    nombres=s.tutor_nombres,
                    telefono=s.tutor_telefono,
                    ci=s.tutor_ci,
                    parentesco=s.parentesco,
                ),
                consentimiento=ConsentimientoSolicitudOut(
                    aceptado=True,
                    version_terminos=s.consent_version,
                    canal=s.consent_canal,
                    aceptado_en=s.consent_aceptado_en,
                ),
                sucursal_sugerida=(SucursalRef(id=suc.id, nombre=suc.nombre) if suc else None),
                categoria_sugerida=(
                    CategoriaRef(id=cat.id, nombre=cat.nombre, nivel=cat.nivel) if cat else None
                ),
                creado_por_nombre=(nombres_usuario.get(s.creado_por) if s.creado_por else None),
                deportista_id=s.deportista_id,
                motivo_rechazo=s.motivo_rechazo,
                created_at=s.created_at,
            )
        )
    return out
