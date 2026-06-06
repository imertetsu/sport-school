"""Router de sucursales (contrato C5): `GET /sucursales` + CRUD ADMIN."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.tenant import CurrentUser, require_role, set_tenant_context
from app.models.alumno import Alumno
from app.models.categoria import Categoria
from app.models.sucursal import Sucursal
from app.schemas.catalogo import SucursalCreate, SucursalOut, SucursalUpdate

router = APIRouter(prefix="/sucursales", tags=["sucursales"])


def _get_sucursal_o_404(db: Session, sucursal_id: uuid.UUID) -> Sucursal:
    """Carga una sucursal bajo RLS; 404 si no existe (o es de otra org)."""
    suc = db.execute(select(Sucursal).where(Sucursal.id == sucursal_id)).scalar_one_or_none()
    if suc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sucursal no encontrada")
    return suc


@router.get("", response_model=list[SucursalOut])
def list_sucursales(
    _user: CurrentUser = Depends(set_tenant_context),
    db: Session = Depends(get_db),
) -> list[SucursalOut]:
    """Lista las sucursales de la organización (RLS filtra por `app.current_org`)."""
    rows = db.execute(select(Sucursal).order_by(Sucursal.nombre)).scalars().all()
    return [SucursalOut.model_validate(r) for r in rows]


@router.post("", response_model=SucursalOut, status_code=status.HTTP_201_CREATED)
def crear_sucursal(
    body: SucursalCreate,
    user: CurrentUser = Depends(require_role("ADMIN")),
    db: Session = Depends(get_db),
) -> SucursalOut:
    """Crea una sucursal en la org del token (ADMIN).

    El `org_id` se fija EXPLÍCITO desde el token: el `WITH CHECK` de RLS lo exige
    (fail-closed). Una org distinta del contexto haría rebotar el INSERT.
    """
    suc = Sucursal(org_id=uuid.UUID(user.org_id), nombre=body.nombre, direccion=body.direccion)
    db.add(suc)
    db.flush()
    return SucursalOut.model_validate(suc)


@router.put("/{sucursal_id}", response_model=SucursalOut)
def actualizar_sucursal(
    sucursal_id: uuid.UUID,
    body: SucursalUpdate,
    _user: CurrentUser = Depends(require_role("ADMIN")),
    db: Session = Depends(get_db),
) -> SucursalOut:
    """Edita nombre/dirección de una sucursal (ADMIN). Otra org ⇒ 404 (RLS `USING`)."""
    suc = _get_sucursal_o_404(db, sucursal_id)
    suc.nombre = body.nombre
    suc.direccion = body.direccion
    db.flush()
    return SucursalOut.model_validate(suc)


@router.delete("/{sucursal_id}", status_code=status.HTTP_204_NO_CONTENT)
def borrar_sucursal(
    sucursal_id: uuid.UUID,
    _user: CurrentUser = Depends(require_role("ADMIN")),
    db: Session = Depends(get_db),
) -> Response:
    """Borra una sucursal SOLO si no está en uso (ADMIN). Otra org ⇒ 404.

    Las FKs `categoria.sucursal_id` y `alumno.sucursal_id` están en CASCADE: borrar
    sin protección arrastraría categorías y alumnos en silencio. Por eso se exige
    409 si la sucursal tiene categorías **o** alumnos asociados; NO se borra en
    cascada.
    """
    suc = _get_sucursal_o_404(db, sucursal_id)

    n_categorias = db.execute(
        select(func.count()).select_from(Categoria).where(Categoria.sucursal_id == sucursal_id)
    ).scalar_one()
    n_alumnos = db.execute(
        select(func.count()).select_from(Alumno).where(Alumno.sucursal_id == sucursal_id)
    ).scalar_one()

    if n_categorias or n_alumnos:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"La sucursal tiene {n_categorias} categoría(s) y {n_alumnos} alumno(s) "
                "asignados; reasígnalos o elimínalos antes de borrarla."
            ),
        )

    db.delete(suc)
    db.flush()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
