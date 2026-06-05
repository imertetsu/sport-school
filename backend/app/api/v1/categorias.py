"""Router de categorías (contrato C5): `GET /categorias?sucursal_id=`."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.tenant import CurrentUser, set_tenant_context
from app.models.categoria import Categoria
from app.schemas.catalogo import CategoriaOut

router = APIRouter(prefix="/categorias", tags=["categorias"])


@router.get("", response_model=list[CategoriaOut])
def list_categorias(
    sucursal_id: uuid.UUID | None = Query(default=None),
    _user: CurrentUser = Depends(set_tenant_context),
    db: Session = Depends(get_db),
) -> list[CategoriaOut]:
    """Lista categorías de la org, opcionalmente filtradas por sucursal (C5)."""
    stmt = select(Categoria)
    if sucursal_id is not None:
        stmt = stmt.where(Categoria.sucursal_id == sucursal_id)
    stmt = stmt.order_by(Categoria.nombre)
    rows = db.execute(stmt).scalars().all()
    return [CategoriaOut.model_validate(r) for r in rows]
