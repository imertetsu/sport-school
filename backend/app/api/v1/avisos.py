"""Router de Avisos (contrato C2). Bearer + contexto de tenant (RLS).

Endpoints:
- GET    /avisos        -> feed scoped por rol (cualquier rol autenticado)
- POST   /avisos        -> publicar (SOLO ADMIN; creado_por = usuario del token)
- PUT    /avisos/{id}   -> editar  (SOLO ADMIN; misma validación de invariante)
- DELETE /avisos/{id}   -> soft-delete (SOLO ADMIN; activo=false), 204

El GET fija `app.current_org` vía `Depends(set_tenant_context)` y el servicio filtra
el feed por rol (ADMIN ve todo; ENTRENADOR solo ORG + sus sucursales/categorías, no
vencidos). La escritura exige `Depends(require_role("ADMIN"))` (ENTRENADOR -> 403),
que se encadena sobre `set_tenant_context`. La invariante C1 la validan los schemas
(422); el aviso inexistente/inactivo -> 404 (servicio `AvisoNoEncontrado`).
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.tenant import CurrentUser, require_role, set_tenant_context
from app.schemas.aviso import AvisoCreate, AvisoOut, AvisosPage, AvisoUpdate
from app.services import aviso as svc

router = APIRouter(prefix="/avisos", tags=["avisos"])


# --------------------------------------------------------------------------- #
# GET /avisos  (cualquier rol autenticado; feed filtrado por rol)
# --------------------------------------------------------------------------- #
@router.get("", response_model=AvisosPage)
def listar_avisos(
    incluir_expirados: bool = Query(default=False),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user: CurrentUser = Depends(set_tenant_context),
    db: Session = Depends(get_db),
) -> AvisosPage:
    """Feed de avisos scoped por rol, paginado, orden `publicado_en` desc (C2).

    ADMIN ve todos los activos (con `incluir_expirados=true` también los vencidos);
    ENTRENADOR solo los que le aplican y no vencidos (el flag se ignora para él).
    """
    return svc.feed(
        db,
        role=user.role,
        sucursal_ids=user.sucursal_ids,
        incluir_expirados=incluir_expirados,
        page=page,
        page_size=page_size,
    )


# --------------------------------------------------------------------------- #
# POST /avisos  (SOLO ADMIN)
# --------------------------------------------------------------------------- #
@router.post("", response_model=AvisoOut)
def crear_aviso(
    body: AvisoCreate,
    user: CurrentUser = Depends(require_role("ADMIN")),
    db: Session = Depends(get_db),
) -> AvisoOut:
    """Publica un aviso; `creado_por` = usuario del token (C2, RNF-03).

    El body se valida con Pydantic (no vacíos + invariante alcance<->ids -> 422).
    Devuelve el aviso creado con sucursal/categoría/autor resueltos.
    """
    return svc.crear(
        db,
        body,
        org_id=uuid.UUID(user.org_id),
        usuario_id=uuid.UUID(user.user_id),
    )


# --------------------------------------------------------------------------- #
# PUT /avisos/{id}  (SOLO ADMIN)
# --------------------------------------------------------------------------- #
@router.put("/{aviso_id}", response_model=AvisoOut)
def editar_aviso(
    aviso_id: uuid.UUID,
    body: AvisoUpdate,
    _user: CurrentUser = Depends(require_role("ADMIN")),
    db: Session = Depends(get_db),
) -> AvisoOut:
    """Edita un aviso activo (misma validación de invariante que el alta) (C2). 404 si no existe."""
    try:
        return svc.editar(db, aviso_id, body)
    except svc.AvisoNoEncontrado as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


# --------------------------------------------------------------------------- #
# DELETE /avisos/{id}  (SOLO ADMIN) -> soft-delete, 204
# --------------------------------------------------------------------------- #
@router.delete("/{aviso_id}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar_aviso(
    aviso_id: uuid.UUID,
    _user: CurrentUser = Depends(require_role("ADMIN")),
    db: Session = Depends(get_db),
) -> Response:
    """Soft-delete del aviso (`activo=false`, no borrado físico) -> 204 (C2). 404 si no existe."""
    try:
        svc.eliminar(db, aviso_id)
    except svc.AvisoNoEncontrado as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
