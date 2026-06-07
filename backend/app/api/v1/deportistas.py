"""Router de Deportistas (contrato C5) — la vertical de este epic.

- GET lista: filtros `q`, `sucursal_id`, paginación.
- GET detalle: arma el perfil completo; **`ficha_medica` gateada por rol** (RNF-02).
- POST: validación dura (≥1 tutor + consentimiento => 422 vía schema) y crea
  deportista + tutores + deportista_tutor + consentimiento (+inscripción).
- PUT: actualiza datos del deportista (no toca tutores en este slice).

Todo corre con contexto de tenant fijado (RLS). No se salta el contexto.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.tenant import CurrentUser, set_tenant_context
from app.models.categoria import Categoria
from app.models.consentimiento import Consentimiento
from app.models.deportista import Deportista
from app.models.deportista_tutor import DeportistaTutor
from app.models.inscripcion import Inscripcion
from app.models.sucursal import Sucursal
from app.models.tutor import Tutor
from app.schemas.common import Page
from app.schemas.deportista import (
    CategoriaRef,
    ConsentimientoOut,
    DeportistaCreate,
    DeportistaDetailOut,
    DeportistaListItem,
    DeportistaUpdate,
    FichaMedica,
    InscripcionOut,
    SucursalRef,
    TutorOut,
)
from app.services import deportista as deportista_svc
from app.services import entrenador as entrenador_svc

router = APIRouter(prefix="/deportistas", tags=["deportistas"])


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _nombre_completo(a: Deportista) -> str:
    partes = [a.ap_paterno, a.ap_materno, a.nombres]
    return " ".join(p for p in partes if p).strip()


def _calc_edad(fecha_nac: date | None) -> int | None:
    if fecha_nac is None:
        return None
    hoy = datetime.now(UTC).date()
    edad = hoy.year - fecha_nac.year - ((hoy.month, hoy.day) < (fecha_nac.month, fecha_nac.day))
    return edad


def _puede_ver_ficha(user: CurrentUser, deportista: Deportista) -> bool:
    """Gating de ficha médica (C5 / RNF-02).

    ADMIN siempre; ENTRENADOR solo si la sucursal del deportista está en sus
    `sucursal_ids` del token.
    """
    if user.role == "ADMIN":
        return True
    if user.role == "ENTRENADOR":
        return str(deportista.sucursal_id) in set(user.sucursal_ids)
    return False


# --------------------------------------------------------------------------- #
# GET /deportistas  (lista paginada)
# --------------------------------------------------------------------------- #
@router.get("", response_model=Page[DeportistaListItem])
def list_deportistas(
    q: str | None = Query(default=None),
    sucursal_id: uuid.UUID | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user: CurrentUser = Depends(set_tenant_context),
    db: Session = Depends(get_db),
) -> Page[DeportistaListItem]:
    """Lista deportistas de la org con filtros y paginación (C5). RLS aísla por org.

    Un ENTRENADOR solo ve los deportistas de las DISCIPLINAS que tiene asignadas
    (`entrenador_disciplina`); si no tiene ninguna, la lista es vacía. ADMIN ve todo.
    El filtro por disciplina es **aditivo** sobre el existente de sucursal.
    """
    base = select(Deportista)
    if sucursal_id is not None:
        base = base.where(Deportista.sucursal_id == sucursal_id)

    # Scoping por disciplina para no-ADMIN: solo deportistas de las disciplinas del
    # entrenador. Sin disciplinas asignadas -> no ve nada (lista vacía, sin más query).
    if user.role != "ADMIN":
        disc_ids = entrenador_svc.disciplina_ids_de_usuario(db, uuid.UUID(user.user_id))
        if not disc_ids:
            return Page(items=[], total=0, page=page, page_size=page_size)
        base = base.where(Deportista.disciplina_id.in_(disc_ids))
    if q:
        like = f"%{q.strip()}%"
        base = base.where(
            or_(
                Deportista.nombres.ilike(like),
                Deportista.ap_paterno.ilike(like),
                Deportista.ap_materno.ilike(like),
                Deportista.ci.ilike(like),
            )
        )

    total = db.execute(select(func.count()).select_from(base.subquery())).scalar_one()

    rows = (
        db.execute(
            base.order_by(Deportista.ap_paterno, Deportista.nombres)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        .scalars()
        .all()
    )

    # Precarga sucursales y categorías referenciadas (evita N+1).
    suc_ids = {a.sucursal_id for a in rows}
    cat_ids = {a.categoria_id for a in rows if a.categoria_id is not None}
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

    items: list[DeportistaListItem] = []
    for a in rows:
        suc = sucursales.get(a.sucursal_id)
        cat = categorias.get(a.categoria_id) if a.categoria_id else None
        items.append(
            DeportistaListItem(
                id=a.id,
                ap_paterno=a.ap_paterno,
                ap_materno=a.ap_materno,
                nombres=a.nombres,
                nombre_completo=_nombre_completo(a),
                ci=a.ci,
                disciplina=a.disciplina,
                disciplina_id=a.disciplina_id,
                categoria=(
                    CategoriaRef(id=cat.id, nombre=cat.nombre, nivel=cat.nivel) if cat else None
                ),
                sucursal=SucursalRef(id=suc.id, nombre=suc.nombre) if suc else None,  # type: ignore[arg-type]
            )
        )

    return Page(items=items, total=total, page=page, page_size=page_size)


# --------------------------------------------------------------------------- #
# GET /deportistas/por-ci/{ci}  (recuperar-por-CI; S3)
# --------------------------------------------------------------------------- #
# IMPORTANTE: declarado ANTES de `/{deportista_id}` para que el path literal
# `por-ci` no compita con el parámetro UUID del detalle.
@router.get("/por-ci/{ci}", response_model=DeportistaDetailOut)
def get_deportista_por_ci(
    ci: str,
    user: CurrentUser = Depends(set_tenant_context),
    db: Session = Depends(get_db),
) -> DeportistaDetailOut:
    """Recupera el deportista de la org con ese CI (S3). 404 si no existe.

    Scoped por org vía RLS (no hay chequeo cross-org: un mismo CI en otra org es
    válido y no se revela). Reusa el armado de `get_deportista` (mismo schema C5).
    """
    deportista = deportista_svc.buscar_deportista_por_ci(db, ci)
    if deportista is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Deportista no encontrado"
        )
    return get_deportista(deportista_id=deportista.id, user=user, db=db)


# --------------------------------------------------------------------------- #
# GET /deportistas/{id}  (detalle)
# --------------------------------------------------------------------------- #
@router.get("/{deportista_id}", response_model=DeportistaDetailOut)
def get_deportista(
    deportista_id: uuid.UUID,
    user: CurrentUser = Depends(set_tenant_context),
    db: Session = Depends(get_db),
) -> DeportistaDetailOut:
    """Perfil completo del deportista (C5). `ficha_medica` gateada por rol/sucursal.

    Defensa en profundidad del scoping por disciplina: un ENTRENADOR que pide un
    deportista de una disciplina que NO tiene asignada recibe **404** (no se revela su
    existencia; 403 filtraría que el id existe). ADMIN ve cualquiera.
    """
    deportista = db.execute(
        select(Deportista).where(Deportista.id == deportista_id)
    ).scalar_one_or_none()
    if deportista is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Deportista no encontrado"
        )

    if user.role != "ADMIN":
        disc_ids = entrenador_svc.disciplina_ids_de_usuario(db, uuid.UUID(user.user_id))
        if deportista.disciplina_id not in disc_ids:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Deportista no encontrado"
            )

    suc = db.execute(
        select(Sucursal).where(Sucursal.id == deportista.sucursal_id)
    ).scalar_one_or_none()
    cat = None
    if deportista.categoria_id is not None:
        cat = db.execute(
            select(Categoria).where(Categoria.id == deportista.categoria_id)
        ).scalar_one_or_none()

    insc = (
        db.execute(
            select(Inscripcion)
            .where(Inscripcion.deportista_id == deportista.id)
            .order_by(Inscripcion.fecha_inscripcion.desc())
        )
        .scalars()
        .first()
    )

    # Tutores vía puente deportista_tutor (parentesco/responsable_pago del puente).
    tutor_rows = db.execute(
        select(Tutor, DeportistaTutor)
        .join(DeportistaTutor, DeportistaTutor.tutor_id == Tutor.id)
        .where(DeportistaTutor.deportista_id == deportista.id)
    ).all()
    tutores = [
        TutorOut(
            id=t.id,
            nombres=t.nombres,
            telefono=t.telefono,
            ci=t.ci,
            parentesco=link.parentesco,
            responsable_pago=link.responsable_pago,
        )
        for (t, link) in tutor_rows
    ]

    cons = (
        db.execute(
            select(Consentimiento)
            .where(Consentimiento.deportista_id == deportista.id)
            .order_by(Consentimiento.aceptado_en.desc())
        )
        .scalars()
        .first()
    )

    ficha = None
    if deportista.ficha_medica and _puede_ver_ficha(user, deportista):
        ficha = FichaMedica(**deportista.ficha_medica)

    return DeportistaDetailOut(
        id=deportista.id,
        ap_paterno=deportista.ap_paterno,
        ap_materno=deportista.ap_materno,
        nombres=deportista.nombres,
        nombre_completo=_nombre_completo(deportista),
        ci=deportista.ci,
        fecha_nac=deportista.fecha_nac,
        edad=_calc_edad(deportista.fecha_nac),
        disciplina=deportista.disciplina,
        disciplina_id=deportista.disciplina_id,
        contacto_emergencia=deportista.contacto_emergencia,
        sucursal=SucursalRef(id=suc.id, nombre=suc.nombre),  # type: ignore[union-attr]
        categoria=(CategoriaRef(id=cat.id, nombre=cat.nombre, nivel=cat.nivel) if cat else None),
        inscripcion=(
            InscripcionOut(
                fecha_inscripcion=insc.fecha_inscripcion,
                monto_mensual=insc.monto_mensual,
                disciplina=insc.disciplina,
                estado=insc.estado,
            )
            if insc
            else None
        ),
        tutores=tutores,
        consentimiento=(
            ConsentimientoOut(
                aceptado_en=cons.aceptado_en,
                version_terminos=cons.version_terminos,
                canal=cons.canal,
            )
            if cons
            else None
        ),
        ficha_medica=ficha,
    )


# --------------------------------------------------------------------------- #
# POST /deportistas  (alta con validación dura)
# --------------------------------------------------------------------------- #
@router.post("", response_model=DeportistaDetailOut, status_code=status.HTTP_201_CREATED)
def create_deportista(
    body: DeportistaCreate,
    user: CurrentUser = Depends(set_tenant_context),
    db: Session = Depends(get_db),
) -> DeportistaDetailOut:
    """Crea deportista + tutores + puente + consentimiento (+inscripción) (C5).

    La validación dura (≥1 tutor + consentimiento) la garantiza `DeportistaCreate`
    (Pydantic => 422 si falta). Aquí asumimos el body ya válido. La creación vive
    en `app/services/deportista.py` (reutilizable, p. ej. al aprobar una solicitud).

    Dedup por CI (S3): un `ci` ya existente en la org -> 409 (backstop del índice
    único parcial; el front usa el lookup proactivo, RNF-06).
    """
    try:
        deportista = deportista_svc.crear_deportista(db, body, org_id=uuid.UUID(user.org_id))
    except deportista_svc.CIDuplicado as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except deportista_svc.DisciplinaInvalida as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return get_deportista(deportista_id=deportista.id, user=user, db=db)


# --------------------------------------------------------------------------- #
# PUT /deportistas/{id}  (actualiza datos del deportista)
# --------------------------------------------------------------------------- #
@router.put("/{deportista_id}", response_model=DeportistaDetailOut)
def update_deportista(
    deportista_id: uuid.UUID,
    body: DeportistaUpdate,
    user: CurrentUser = Depends(set_tenant_context),
    db: Session = Depends(get_db),
) -> DeportistaDetailOut:
    """Actualiza datos del deportista (no toca tutores en este slice) (C5).

    Un `disciplina_id` que no existe en el catálogo (o inactivo) -> 422 (la validación
    vive en el servicio; aquí solo se traduce a HTTP).
    """
    deportista = db.execute(
        select(Deportista).where(Deportista.id == deportista_id)
    ).scalar_one_or_none()
    if deportista is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Deportista no encontrado"
        )

    try:
        deportista_svc.actualizar_deportista(db, deportista, body)
    except deportista_svc.DisciplinaInvalida as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return get_deportista(deportista_id=deportista.id, user=user, db=db)
