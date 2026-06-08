"""Router de `/mi-escuela` (contrato C2, epic escuela-y-bajas, Fase 1).

`GET /mi-escuela` y `PUT /mi-escuela`: leer/editar `nombre` + `color` (monograma)
de la escuela del usuario. Solo ADMIN.

⚠️ Borde de seguridad clave del epic: la tabla `organizacion` **NO tiene RLS**
(es la única sin org_id/policy). Por eso el guardián es **el endpoint**: ambos
endpoints leen/escriben SIEMPRE la org de `user.org_id` (del token) e **IGNORAN
cualquier id** que pudiera venir del cliente (no hay parámetro de id en la ruta).
Un ADMIN solo puede ver/tocar SU escuela.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.tenant import CurrentUser, require_role
from app.models.organizacion import Organizacion
from app.schemas.organizacion import MiEscuelaOut, MiEscuelaUpdate

router = APIRouter(prefix="/mi-escuela", tags=["mi-escuela"])


def _org_del_usuario(db: Session, user: CurrentUser) -> Organizacion:
    """Carga la org del token (`user.org_id`). 404 si no existe.

    El id sale SIEMPRE del token, nunca del cliente: este es el único scope de
    `organizacion` (no hay RLS). `require_role("ADMIN")` garantiza que `org_id`
    no es vacío (el SUPERADMIN, sin org_id, queda fuera por rol).
    """
    org = db.execute(
        select(Organizacion).where(Organizacion.id == uuid.UUID(user.org_id))
    ).scalar_one_or_none()
    if org is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Escuela no encontrada")
    return org


@router.get("", response_model=MiEscuelaOut)
def obtener_mi_escuela(
    user: CurrentUser = Depends(require_role("ADMIN")),
    db: Session = Depends(get_db),
) -> MiEscuelaOut:
    """Devuelve `nombre` + `color` de la escuela del usuario (ADMIN)."""
    org = _org_del_usuario(db, user)
    return MiEscuelaOut.model_validate(org)


@router.put("", response_model=MiEscuelaOut)
def actualizar_mi_escuela(
    body: MiEscuelaUpdate,
    user: CurrentUser = Depends(require_role("ADMIN")),
    db: Session = Depends(get_db),
) -> MiEscuelaOut:
    """Actualiza `nombre` + `color` de la escuela del usuario (ADMIN).

    Scope server-side a `user.org_id`: aunque el cliente intente colar un id de
    OTRA org en el body, este endpoint no lee ningún id del body — solo toca la
    org del token.
    """
    org = _org_del_usuario(db, user)
    org.nombre = body.nombre
    org.color = body.color
    db.flush()
    return MiEscuelaOut.model_validate(org)
