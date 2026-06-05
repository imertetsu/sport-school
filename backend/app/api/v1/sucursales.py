"""Router de sucursales (contrato C5): `GET /sucursales`."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.tenant import CurrentUser, set_tenant_context
from app.models.sucursal import Sucursal
from app.schemas.catalogo import SucursalOut

router = APIRouter(prefix="/sucursales", tags=["sucursales"])


@router.get("", response_model=list[SucursalOut])
def list_sucursales(
    _user: CurrentUser = Depends(set_tenant_context),
    db: Session = Depends(get_db),
) -> list[SucursalOut]:
    """Lista las sucursales de la organización (RLS filtra por `app.current_org`)."""
    rows = db.execute(select(Sucursal).order_by(Sucursal.nombre)).scalars().all()
    return [SucursalOut.model_validate(r) for r in rows]
