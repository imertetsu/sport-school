"""Router de Alumnos (contrato C5) — la vertical de este epic.

- GET lista: filtros `q`, `sucursal_id`, paginación.
- GET detalle: arma el perfil completo; **`ficha_medica` gateada por rol** (RNF-02).
- POST: validación dura (≥1 tutor + consentimiento => 422 vía schema) y crea
  alumno + tutores + alumno_tutor + consentimiento (+inscripción).
- PUT: actualiza datos del alumno (no toca tutores en este slice).

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
from app.models.alumno import Alumno
from app.models.alumno_tutor import AlumnoTutor
from app.models.categoria import Categoria
from app.models.consentimiento import Consentimiento
from app.models.inscripcion import Inscripcion
from app.models.sucursal import Sucursal
from app.models.tutor import Tutor
from app.schemas.alumno import (
    AlumnoCreate,
    AlumnoDetailOut,
    AlumnoListItem,
    AlumnoUpdate,
    CategoriaRef,
    ConsentimientoOut,
    FichaMedica,
    InscripcionOut,
    SucursalRef,
    TutorOut,
)
from app.schemas.common import Page

router = APIRouter(prefix="/alumnos", tags=["alumnos"])


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _nombre_completo(a: Alumno) -> str:
    partes = [a.ap_paterno, a.ap_materno, a.nombres]
    return " ".join(p for p in partes if p).strip()


def _calc_edad(fecha_nac: date | None) -> int | None:
    if fecha_nac is None:
        return None
    hoy = datetime.now(UTC).date()
    edad = hoy.year - fecha_nac.year - (
        (hoy.month, hoy.day) < (fecha_nac.month, fecha_nac.day)
    )
    return edad


def _puede_ver_ficha(user: CurrentUser, alumno: Alumno) -> bool:
    """Gating de ficha médica (C5 / RNF-02).

    ADMIN siempre; ENTRENADOR solo si la sucursal del alumno está en sus
    `sucursal_ids` del token.
    """
    if user.role == "ADMIN":
        return True
    if user.role == "ENTRENADOR":
        return str(alumno.sucursal_id) in set(user.sucursal_ids)
    return False


# --------------------------------------------------------------------------- #
# GET /alumnos  (lista paginada)
# --------------------------------------------------------------------------- #
@router.get("", response_model=Page[AlumnoListItem])
def list_alumnos(
    q: str | None = Query(default=None),
    sucursal_id: uuid.UUID | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    _user: CurrentUser = Depends(set_tenant_context),
    db: Session = Depends(get_db),
) -> Page[AlumnoListItem]:
    """Lista alumnos de la org con filtros y paginación (C5). RLS aísla por org."""
    base = select(Alumno)
    if sucursal_id is not None:
        base = base.where(Alumno.sucursal_id == sucursal_id)
    if q:
        like = f"%{q.strip()}%"
        base = base.where(
            or_(
                Alumno.nombres.ilike(like),
                Alumno.ap_paterno.ilike(like),
                Alumno.ap_materno.ilike(like),
                Alumno.ci.ilike(like),
            )
        )

    total = db.execute(
        select(func.count()).select_from(base.subquery())
    ).scalar_one()

    rows = (
        db.execute(
            base.order_by(Alumno.ap_paterno, Alumno.nombres)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        .scalars()
        .all()
    )

    # Precarga sucursales y categorías referenciadas (evita N+1).
    suc_ids = {a.sucursal_id for a in rows}
    cat_ids = {a.categoria_id for a in rows if a.categoria_id is not None}
    sucursales = {
        s.id: s
        for s in db.execute(select(Sucursal).where(Sucursal.id.in_(suc_ids))).scalars().all()
    } if suc_ids else {}
    categorias = {
        c.id: c
        for c in db.execute(select(Categoria).where(Categoria.id.in_(cat_ids))).scalars().all()
    } if cat_ids else {}

    items: list[AlumnoListItem] = []
    for a in rows:
        suc = sucursales.get(a.sucursal_id)
        cat = categorias.get(a.categoria_id) if a.categoria_id else None
        items.append(
            AlumnoListItem(
                id=a.id,
                ap_paterno=a.ap_paterno,
                ap_materno=a.ap_materno,
                nombres=a.nombres,
                nombre_completo=_nombre_completo(a),
                ci=a.ci,
                disciplina=a.disciplina,
                categoria=(
                    CategoriaRef(id=cat.id, nombre=cat.nombre, nivel=cat.nivel) if cat else None
                ),
                sucursal=SucursalRef(id=suc.id, nombre=suc.nombre) if suc else None,  # type: ignore[arg-type]
            )
        )

    return Page(items=items, total=total, page=page, page_size=page_size)


# --------------------------------------------------------------------------- #
# GET /alumnos/{id}  (detalle)
# --------------------------------------------------------------------------- #
@router.get("/{alumno_id}", response_model=AlumnoDetailOut)
def get_alumno(
    alumno_id: uuid.UUID,
    user: CurrentUser = Depends(set_tenant_context),
    db: Session = Depends(get_db),
) -> AlumnoDetailOut:
    """Perfil completo del alumno (C5). `ficha_medica` gateada por rol/sucursal."""
    alumno = db.execute(select(Alumno).where(Alumno.id == alumno_id)).scalar_one_or_none()
    if alumno is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alumno no encontrado")

    suc = db.execute(
        select(Sucursal).where(Sucursal.id == alumno.sucursal_id)
    ).scalar_one_or_none()
    cat = None
    if alumno.categoria_id is not None:
        cat = db.execute(
            select(Categoria).where(Categoria.id == alumno.categoria_id)
        ).scalar_one_or_none()

    insc = (
        db.execute(
            select(Inscripcion)
            .where(Inscripcion.alumno_id == alumno.id)
            .order_by(Inscripcion.fecha_inscripcion.desc())
        )
        .scalars()
        .first()
    )

    # Tutores vía puente alumno_tutor (parentesco/responsable_pago del puente).
    tutor_rows = db.execute(
        select(Tutor, AlumnoTutor)
        .join(AlumnoTutor, AlumnoTutor.tutor_id == Tutor.id)
        .where(AlumnoTutor.alumno_id == alumno.id)
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
            .where(Consentimiento.alumno_id == alumno.id)
            .order_by(Consentimiento.aceptado_en.desc())
        )
        .scalars()
        .first()
    )

    ficha = None
    if alumno.ficha_medica and _puede_ver_ficha(user, alumno):
        ficha = FichaMedica(**alumno.ficha_medica)

    return AlumnoDetailOut(
        id=alumno.id,
        ap_paterno=alumno.ap_paterno,
        ap_materno=alumno.ap_materno,
        nombres=alumno.nombres,
        nombre_completo=_nombre_completo(alumno),
        ci=alumno.ci,
        fecha_nac=alumno.fecha_nac,
        edad=_calc_edad(alumno.fecha_nac),
        disciplina=alumno.disciplina,
        contacto_emergencia=alumno.contacto_emergencia,
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
# POST /alumnos  (alta con validación dura)
# --------------------------------------------------------------------------- #
@router.post("", response_model=AlumnoDetailOut, status_code=status.HTTP_201_CREATED)
def create_alumno(
    body: AlumnoCreate,
    user: CurrentUser = Depends(set_tenant_context),
    db: Session = Depends(get_db),
) -> AlumnoDetailOut:
    """Crea alumno + tutores + puente + consentimiento (+inscripción) (C5).

    La validación dura (≥1 tutor + consentimiento) la garantiza `AlumnoCreate`
    (Pydantic => 422 si falta). Aquí asumimos el body ya válido.
    """
    org_id = uuid.UUID(user.org_id)

    alumno = Alumno(
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
    db.add(alumno)
    db.flush()  # obtener alumno.id

    # Tutores + puente. Consentimiento se ata al primer tutor (responsable).
    primer_tutor_id: uuid.UUID | None = None
    for t in body.tutores:
        tutor = Tutor(org_id=org_id, nombres=t.nombres, telefono=t.telefono, ci=t.ci)
        db.add(tutor)
        db.flush()
        if primer_tutor_id is None:
            primer_tutor_id = tutor.id
        db.add(
            AlumnoTutor(
                org_id=org_id,
                alumno_id=alumno.id,
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
            alumno_id=alumno.id,
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
                alumno_id=alumno.id,
                disciplina=ins.disciplina,
                fecha_inscripcion=ins.fecha_inscripcion,
                monto_mensual=ins.monto_mensual,
                modo_cobro=ins.modo_cobro,
                dia_corte=ins.dia_corte,
                estado=ins.estado,
            )
        )

    db.flush()
    return get_alumno(alumno_id=alumno.id, user=user, db=db)


# --------------------------------------------------------------------------- #
# PUT /alumnos/{id}  (actualiza datos del alumno)
# --------------------------------------------------------------------------- #
@router.put("/{alumno_id}", response_model=AlumnoDetailOut)
def update_alumno(
    alumno_id: uuid.UUID,
    body: AlumnoUpdate,
    user: CurrentUser = Depends(set_tenant_context),
    db: Session = Depends(get_db),
) -> AlumnoDetailOut:
    """Actualiza datos del alumno (no toca tutores en este slice) (C5)."""
    alumno = db.execute(select(Alumno).where(Alumno.id == alumno_id)).scalar_one_or_none()
    if alumno is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alumno no encontrado")

    data = body.model_dump(exclude_unset=True)
    if "ficha_medica" in data:
        fm = data.pop("ficha_medica")
        alumno.ficha_medica = fm  # ya es dict (model_dump) o None
    for field_name, value in data.items():
        setattr(alumno, field_name, value)

    db.flush()
    return get_alumno(alumno_id=alumno.id, user=user, db=db)
