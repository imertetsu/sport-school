"""Router de Entrenadores (epic B). Bearer + contexto de tenant (RLS).

Endpoints:
- GET  /entrenadores              -> lista (cualquier rol autenticado; pobla selectores)
- POST /entrenadores              -> alta usuario(ENTRENADOR)+perfil (SOLO ADMIN), 201
- PUT  /entrenadores/{id}         -> editar/baja/reactivar (SOLO ADMIN)

El GET fija `app.current_org` vía `Depends(set_tenant_context)` y devuelve solo los
entrenadores de la org del usuario (RLS). La escritura exige
`Depends(require_role("ADMIN"))` (ENTRENADOR -> 403). Email ya en uso -> 409 (el
servicio caza el `IntegrityError` global del GOTCHA de RLS); inexistente -> 404.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.engine import Row
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.tenant import CurrentUser, require_role, set_tenant_context
from app.models.entrenador import Entrenador
from app.models.usuario import Usuario
from app.schemas.entrenador import EntrenadorCreate, EntrenadorOut, EntrenadorUpdate
from app.services import entrenador as svc

router = APIRouter(prefix="/entrenadores", tags=["entrenadores"])


def _to_out(row: Row[tuple[Entrenador, Usuario]]) -> EntrenadorOut:
    """Mapea una fila `(Entrenador, Usuario)` del join a `EntrenadorOut`."""
    entrenador, usuario = row
    return EntrenadorOut(
        id=entrenador.id,
        usuario_id=entrenador.usuario_id,
        nombres=entrenador.nombres,
        email=usuario.email,
        especialidad=entrenador.especialidad,
        disciplinas=entrenador.disciplinas,
        activo=usuario.activo,
    )


# --------------------------------------------------------------------------- #
# GET /entrenadores  (cualquier rol autenticado)
# --------------------------------------------------------------------------- #
@router.get("", response_model=list[EntrenadorOut])
def listar_entrenadores(
    solo_activos: bool = Query(default=False),
    _user: CurrentUser = Depends(set_tenant_context),
    db: Session = Depends(get_db),
) -> list[EntrenadorOut]:
    """Lista los entrenadores de la org (RLS), orden por nombres. Pobla selectores.

    `?solo_activos=true` excluye los dados de baja (`usuario.activo=false`).
    """
    return [_to_out(row) for row in svc.listar(db, solo_activos=solo_activos)]


# --------------------------------------------------------------------------- #
# POST /entrenadores  (SOLO ADMIN)
# --------------------------------------------------------------------------- #
@router.post("", response_model=EntrenadorOut, status_code=status.HTTP_201_CREATED)
def crear_entrenador(
    body: EntrenadorCreate,
    user: CurrentUser = Depends(require_role("ADMIN")),
    db: Session = Depends(get_db),
) -> EntrenadorOut:
    """Crea `usuario`(ENTRENADOR, activo) + perfil en una transacción -> 201.

    Email ya en uso (en esta org **o** en otra, vía el GOTCHA de RLS) -> 409.
    """
    try:
        row = svc.crear(db, body, org_id=uuid.UUID(user.org_id))
    except svc.EmailEnUso as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _to_out(row)


# --------------------------------------------------------------------------- #
# PUT /entrenadores/{id}  (SOLO ADMIN)
# --------------------------------------------------------------------------- #
@router.put("/{entrenador_id}", response_model=EntrenadorOut)
def editar_entrenador(
    entrenador_id: uuid.UUID,
    body: EntrenadorUpdate,
    _user: CurrentUser = Depends(require_role("ADMIN")),
    db: Session = Depends(get_db),
) -> EntrenadorOut:
    """Edita nombres/especialidad/disciplinas/activo/password (solo lo provisto).

    `activo=false` da de baja, `activo=true` reactiva. Inexistente -> 404.
    """
    try:
        row = svc.editar(db, entrenador_id, body)
    except svc.EntrenadorNoEncontrado as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except svc.EmailEnUso as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _to_out(row)
