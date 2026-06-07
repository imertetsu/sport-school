"""Router de Asistencia (contrato C2). Bearer + contexto de tenant (RLS).

Endpoints:
- GET  /asistencia/categorias   -> categorías visibles por rol (+ total_deportistas)
- GET  /asistencia/roster       -> get-or-create lógico (NO crea sesión)
- POST /asistencia/guardar      -> idempotente (crea sesión + upsert de marcas)
- GET  /asistencia/sesiones     -> historial paginado por categoría

ENTRENADOR ve solo categorías de sus `sucursal_ids` (igual criterio que ficha
médica); pedir una fuera de su alcance -> 403. Todos los endpoints fijan
`app.current_org` vía `Depends(set_tenant_context)` (no se salta el contexto).
"""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.tenant import CurrentUser, set_tenant_context
from app.models.sucursal import Sucursal
from app.schemas.asistencia import (
    CategoriaAsistencia,
    CategoriaRefAsistencia,
    GuardarBody,
    Resumen,
    RosterItem,
    RosterOut,
    SesionesPage,
    SesionHistorialItem,
    SucursalRefAsistencia,
)
from app.services import asistencia as svc
from app.services import entrenador as entrenador_svc

router = APIRouter(prefix="/asistencia", tags=["asistencia"])


def _http_error(exc: svc.AsistenciaError) -> HTTPException:
    """Traduce errores de negocio del servicio a HTTP (403/404)."""
    if isinstance(exc, svc.CategoriaFuera):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


def _disciplina_scope(db: Session, user: CurrentUser) -> set[uuid.UUID] | None:
    """Disciplinas que limitan al usuario, o `None` si ve todas (ADMIN).

    Un ENTRENADOR queda acotado a las disciplinas asignadas en `entrenador_disciplina`
    (aditivo al filtro de sucursal); sin disciplinas asignadas -> set vacío (no ve
    ninguna categoría). Resuelto server-side por request (no en el token).
    """
    if user.role == "ADMIN":
        return None
    return entrenador_svc.disciplina_ids_de_usuario(db, uuid.UUID(user.user_id))


# --------------------------------------------------------------------------- #
# GET /asistencia/categorias
# --------------------------------------------------------------------------- #
@router.get("/categorias", response_model=list[CategoriaAsistencia])
def list_categorias(
    user: CurrentUser = Depends(set_tenant_context),
    db: Session = Depends(get_db),
) -> list[CategoriaAsistencia]:
    """Categorías visibles por rol con su total de deportistas (C2)."""
    rows = svc.listar_categorias(
        db,
        role=user.role,
        sucursal_ids=user.sucursal_ids,
        disciplina_ids=_disciplina_scope(db, user),
    )

    # Precarga sucursales referenciadas (evita N+1).
    suc_ids = {cat.sucursal_id for (cat, _total) in rows}
    sucursales = (
        {
            s.id: s
            for s in db.execute(select(Sucursal).where(Sucursal.id.in_(suc_ids))).scalars().all()
        }
        if suc_ids
        else {}
    )

    out: list[CategoriaAsistencia] = []
    for cat, total in rows:
        suc = sucursales.get(cat.sucursal_id)
        out.append(
            CategoriaAsistencia(
                id=cat.id,
                nombre=cat.nombre,
                nivel=cat.nivel,
                sucursal=SucursalRefAsistencia(
                    id=cat.sucursal_id,
                    nombre=suc.nombre if suc else "",
                ),
                total_deportistas=total,
            )
        )
    return out


# --------------------------------------------------------------------------- #
# GET /asistencia/roster
# --------------------------------------------------------------------------- #
@router.get("/roster", response_model=RosterOut)
def get_roster(
    categoria_id: uuid.UUID = Query(...),
    fecha: date = Query(...),
    user: CurrentUser = Depends(set_tenant_context),
    db: Session = Depends(get_db),
) -> RosterOut:
    """Roster de la categoría para una fecha (get-or-create lógico) (C2).

    NO crea sesión: si aún no hay, `sesion_id=null` y `estado=null` por deportista.
    """
    try:
        cat, sesion, deportistas, estados = svc.obtener_roster(
            db,
            categoria_id=categoria_id,
            fecha=fecha,
            role=user.role,
            sucursal_ids=user.sucursal_ids,
            disciplina_ids=_disciplina_scope(db, user),
        )
    except svc.AsistenciaError as exc:
        raise _http_error(exc) from exc

    items = [
        RosterItem(
            deportista_id=a.id,
            nombre_completo=svc.nombre_completo(a),
            estado=estados.get(a.id),  # type: ignore[arg-type]
        )
        for a in deportistas
    ]
    presentes, ausentes, total = svc.contar_resumen([it.estado for it in items])

    return RosterOut(
        sesion_id=sesion.id if sesion else None,
        categoria=CategoriaRefAsistencia(id=cat.id, nombre=cat.nombre),
        fecha=fecha,
        items=items,
        resumen=Resumen(presentes=presentes, ausentes=ausentes, total=total),
    )


# --------------------------------------------------------------------------- #
# POST /asistencia/guardar
# --------------------------------------------------------------------------- #
@router.post("/guardar", response_model=RosterOut)
def guardar(
    body: GuardarBody,
    user: CurrentUser = Depends(set_tenant_context),
    db: Session = Depends(get_db),
) -> RosterOut:
    """Crea la sesión si falta y hace upsert de las marcas (idempotente) (C2).

    Devuelve el roster guardado + resumen. Re-guardar actualiza (no duplica).
    """
    disciplina_ids = _disciplina_scope(db, user)
    try:
        cat, sesion = svc.guardar_asistencia(
            db,
            org_id=uuid.UUID(user.org_id),
            categoria_id=body.categoria_id,
            fecha=body.fecha,
            hora=body.hora,
            marcas=[(m.deportista_id, m.estado) for m in body.marcas],
            registrado_por=uuid.UUID(user.user_id),
            role=user.role,
            sucursal_ids=user.sucursal_ids,
            disciplina_ids=disciplina_ids,
        )
    except svc.AsistenciaError as exc:
        raise _http_error(exc) from exc

    # Releer el roster guardado (refleja exactamente el estado persistido).
    _cat, _sesion, deportistas, estados = svc.obtener_roster(
        db,
        categoria_id=body.categoria_id,
        fecha=body.fecha,
        role=user.role,
        sucursal_ids=user.sucursal_ids,
        disciplina_ids=disciplina_ids,
    )
    items = [
        RosterItem(
            deportista_id=a.id,
            nombre_completo=svc.nombre_completo(a),
            estado=estados.get(a.id),  # type: ignore[arg-type]
        )
        for a in deportistas
    ]
    presentes, ausentes, total = svc.contar_resumen([it.estado for it in items])

    return RosterOut(
        sesion_id=sesion.id,
        categoria=CategoriaRefAsistencia(id=cat.id, nombre=cat.nombre),
        fecha=body.fecha,
        items=items,
        resumen=Resumen(presentes=presentes, ausentes=ausentes, total=total),
    )


# --------------------------------------------------------------------------- #
# GET /asistencia/sesiones
# --------------------------------------------------------------------------- #
@router.get("/sesiones", response_model=SesionesPage)
def list_sesiones(
    categoria_id: uuid.UUID = Query(...),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user: CurrentUser = Depends(set_tenant_context),
    db: Session = Depends(get_db),
) -> SesionesPage:
    """Historial paginado de sesiones de una categoría con contadores (C2)."""
    try:
        rows, total = svc.listar_sesiones(
            db,
            categoria_id=categoria_id,
            role=user.role,
            sucursal_ids=user.sucursal_ids,
            page=page,
            page_size=page_size,
            disciplina_ids=_disciplina_scope(db, user),
        )
    except svc.AsistenciaError as exc:
        raise _http_error(exc) from exc

    items = [
        SesionHistorialItem(
            id=sesion.id,
            fecha=sesion.fecha,
            hora=sesion.hora,
            presentes=presentes,
            ausentes=ausentes,
            total=total_ses,
        )
        for (sesion, presentes, ausentes, total_ses) in rows
    ]
    return SesionesPage(items=items, total=total, page=page, page_size=page_size)
