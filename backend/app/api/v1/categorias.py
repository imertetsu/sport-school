"""Router de categorías (contrato C5): `GET /categorias?sucursal_id=` + CRUD ADMIN."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.tenant import CurrentUser, require_role, set_tenant_context
from app.models.categoria import Categoria
from app.models.deportista import Deportista
from app.models.horario_clase import HorarioClase
from app.models.sesion import Sesion
from app.models.sucursal import Sucursal
from app.schemas.catalogo import CategoriaCreate, CategoriaOut, CategoriaUpdate

router = APIRouter(prefix="/categorias", tags=["categorias"])


def _get_categoria_o_404(db: Session, categoria_id: uuid.UUID) -> Categoria:
    """Carga una categoría bajo RLS; 404 si no existe (o es de otra org)."""
    cat = db.execute(select(Categoria).where(Categoria.id == categoria_id)).scalar_one_or_none()
    if cat is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Categoría no encontrada")
    return cat


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


@router.post("", response_model=CategoriaOut, status_code=status.HTTP_201_CREATED)
def crear_categoria(
    body: CategoriaCreate,
    user: CurrentUser = Depends(require_role("ADMIN")),
    db: Session = Depends(get_db),
) -> CategoriaOut:
    """Crea una categoría en la org del token (ADMIN).

    Verifica que `sucursal_id` exista en la org (bajo RLS) ⇒ 404 si no. El `org_id`
    se fija EXPLÍCITO desde el token (`WITH CHECK` de RLS; fail-closed).
    """
    suc = db.execute(
        select(Sucursal.id).where(Sucursal.id == body.sucursal_id)
    ).scalar_one_or_none()
    if suc is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sucursal no encontrada")
    cat = Categoria(
        org_id=uuid.UUID(user.org_id),
        sucursal_id=body.sucursal_id,
        nombre=body.nombre,
        nivel=body.nivel,
        rango_edad=body.rango_edad,
    )
    db.add(cat)
    db.flush()
    return CategoriaOut.model_validate(cat)


@router.put("/{categoria_id}", response_model=CategoriaOut)
def actualizar_categoria(
    categoria_id: uuid.UUID,
    body: CategoriaUpdate,
    _user: CurrentUser = Depends(require_role("ADMIN")),
    db: Session = Depends(get_db),
) -> CategoriaOut:
    """Edita nombre/nivel/rango de una categoría (ADMIN). `sucursal_id` NO cambia.

    Otra org ⇒ 404 (RLS `USING`).
    """
    cat = _get_categoria_o_404(db, categoria_id)
    cat.nombre = body.nombre
    cat.nivel = body.nivel
    cat.rango_edad = body.rango_edad
    db.flush()
    return CategoriaOut.model_validate(cat)


@router.delete("/{categoria_id}", status_code=status.HTTP_204_NO_CONTENT)
def borrar_categoria(
    categoria_id: uuid.UUID,
    _user: CurrentUser = Depends(require_role("ADMIN")),
    db: Session = Depends(get_db),
) -> Response:
    """Borra una categoría SOLO si no está en uso (ADMIN). Otra org ⇒ 404.

    `horario_clase.categoria_id` y `sesion.categoria_id` están en CASCADE; borrar
    sin protección arrastraría horarios y sesiones (y con ellas la asistencia).
    `deportista.categoria_id` es SET NULL (no se borra, pero quedaría huérfano). Por eso
    se exige 409 si la categoría tiene deportistas, horarios o sesiones; NO cascada.
    """
    cat = _get_categoria_o_404(db, categoria_id)

    n_deportistas = db.execute(
        select(func.count()).select_from(Deportista).where(Deportista.categoria_id == categoria_id)
    ).scalar_one()
    n_horarios = db.execute(
        select(func.count())
        .select_from(HorarioClase)
        .where(HorarioClase.categoria_id == categoria_id)
    ).scalar_one()
    n_sesiones = db.execute(
        select(func.count()).select_from(Sesion).where(Sesion.categoria_id == categoria_id)
    ).scalar_one()

    if n_deportistas or n_horarios or n_sesiones:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"La categoría tiene {n_deportistas} deportista(s), {n_horarios} horario(s) y "
                f"{n_sesiones} sesión(es) asociados; reasígnalos antes de borrarla."
            ),
        )

    db.delete(cat)
    db.flush()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
