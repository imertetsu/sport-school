"""Router de Horarios (contrato C2 del epic Programación de clases).

Bearer + contexto de tenant (RLS). Endpoints:
- GET    /horarios          -> lista de horarios activos scoped por rol
- GET    /horarios/semana   -> rejilla semanal (7 días) scoped por rol
- POST   /horarios          -> alta   (SOLO ADMIN)
- PUT    /horarios/{id}     -> edición (SOLO ADMIN)
- DELETE /horarios/{id}     -> soft-delete (SOLO ADMIN, activo=false) -> 204

Las lecturas fijan `app.current_org` vía `Depends(set_tenant_context)` y el
servicio filtra por rol (ADMIN todos; ENTRENADOR solo sus `sucursal_ids`). La
escritura exige `Depends(require_role("ADMIN"))` (ENTRENADOR -> 403), encadenado
sobre `set_tenant_context`. Validación de invariante (hora_fin>hora_inicio,
dia_semana) -> 422 (schema); fuera de alcance -> 403; no encontrado -> 404;
unicidad (categoria, dia_semana, hora_inicio) -> 409.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.tenant import CurrentUser, require_role, set_tenant_context
from app.schemas.horarios import HorarioCreate, HorarioOut, HorarioUpdate, SemanaOut
from app.services import horarios as svc

router = APIRouter(prefix="/horarios", tags=["horarios"])


def _http_error(exc: svc.HorarioError) -> HTTPException:
    """Traduce errores de negocio del servicio a HTTP (403/404/409)."""
    if isinstance(exc, svc.CategoriaFuera):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    if isinstance(exc, svc.HorarioDuplicado):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    # CategoriaNoEncontrada / HorarioNoEncontrado
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


# --------------------------------------------------------------------------- #
# GET /horarios  (cualquier rol autenticado; lista scoped por rol)
# --------------------------------------------------------------------------- #
@router.get("", response_model=list[HorarioOut])
def listar_horarios(
    categoria_id: uuid.UUID | None = Query(default=None),
    sucursal_id: uuid.UUID | None = Query(default=None),
    user: CurrentUser = Depends(set_tenant_context),
    db: Session = Depends(get_db),
) -> list[HorarioOut]:
    """Horarios activos visibles por rol, filtrables por categoría/sucursal (C2)."""
    return svc.listar(
        db,
        role=user.role,
        sucursal_ids=user.sucursal_ids,
        categoria_id=categoria_id,
        sucursal_id=sucursal_id,
    )


# --------------------------------------------------------------------------- #
# GET /horarios/semana  (cualquier rol autenticado; rejilla scoped por rol)
# --------------------------------------------------------------------------- #
@router.get("/semana", response_model=SemanaOut)
def semana_horarios(
    categoria_id: uuid.UUID | None = Query(default=None),
    sucursal_id: uuid.UUID | None = Query(default=None),
    user: CurrentUser = Depends(set_tenant_context),
    db: Session = Depends(get_db),
) -> SemanaOut:
    """Rejilla semanal (7 días, 0..6) agrupando las clases visibles por rol (C2)."""
    return svc.vista_semana(
        db,
        role=user.role,
        sucursal_ids=user.sucursal_ids,
        categoria_id=categoria_id,
        sucursal_id=sucursal_id,
    )


# --------------------------------------------------------------------------- #
# POST /horarios  (SOLO ADMIN)
# --------------------------------------------------------------------------- #
@router.post("", response_model=HorarioOut)
def crear_horario(
    body: HorarioCreate,
    user: CurrentUser = Depends(require_role("ADMIN")),
    db: Session = Depends(get_db),
) -> HorarioOut:
    """Crea un horario (ADMIN). Valida invariante (422), alcance (403/404) y unicidad (409)."""
    try:
        return svc.crear(
            db,
            body,
            org_id=uuid.UUID(user.org_id),
            role=user.role,
            sucursal_ids=user.sucursal_ids,
        )
    except svc.HorarioError as exc:
        raise _http_error(exc) from exc


# --------------------------------------------------------------------------- #
# PUT /horarios/{id}  (SOLO ADMIN)
# --------------------------------------------------------------------------- #
@router.put("/{horario_id}", response_model=HorarioOut)
def editar_horario(
    horario_id: uuid.UUID,
    body: HorarioUpdate,
    user: CurrentUser = Depends(require_role("ADMIN")),
    db: Session = Depends(get_db),
) -> HorarioOut:
    """Edita un horario activo (ADMIN), misma validación que el alta (C2). 404/403/409."""
    try:
        return svc.editar(
            db,
            horario_id,
            body,
            role=user.role,
            sucursal_ids=user.sucursal_ids,
        )
    except svc.HorarioError as exc:
        raise _http_error(exc) from exc


# --------------------------------------------------------------------------- #
# DELETE /horarios/{id}  (SOLO ADMIN) -> soft-delete, 204
# --------------------------------------------------------------------------- #
@router.delete("/{horario_id}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar_horario(
    horario_id: uuid.UUID,
    _user: CurrentUser = Depends(require_role("ADMIN")),
    db: Session = Depends(get_db),
) -> Response:
    """Soft-delete del horario (`activo=false`, no borrado físico) -> 204 (C2). 404 si no existe."""
    try:
        svc.eliminar(db, horario_id)
    except svc.HorarioError as exc:
        raise _http_error(exc) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
