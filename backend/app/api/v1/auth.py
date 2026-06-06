"""Router de autenticación (contratos C2 login, C4).

`POST /login` no puede consultar `usuario` directo: RLS lo bloquea porque aún no
hay `app.current_org`. Usa la función `SECURITY DEFINER` `login_lookup(email)`
(creada por db-dev) vía `text()`, que devuelve `(id, org_id, password_hash, role,
activo)` saltando RLS de forma controlada.

`GET /me` ya corre con contexto de tenant (Bearer) y devuelve el usuario actual.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import create_access_token, verify_password
from app.core.tenant import CurrentUser, set_tenant_context
from app.models.sucursal import Sucursal
from app.models.usuario import Usuario
from app.schemas.auth import LoginIn, TokenOut, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, db: Session = Depends(get_db)) -> TokenOut:
    """Autentica por email+clave y devuelve JWT + datos del usuario (C4)."""
    row = (
        db.execute(
            text(
                "SELECT id, org_id, password_hash, role, activo, nombre, email "
                "FROM login_lookup(:email)"
            ),
            {"email": body.email},
        )
        .mappings()
        .first()
    )

    invalid = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Credenciales inválidas",
    )
    if row is None or not row["activo"]:
        raise invalid
    if not verify_password(body.password, row["password_hash"]):
        raise invalid

    org_id = str(row["org_id"])

    # Escuela suspendida (Epic Super Admin): se rechaza el login con 403 antes de
    # emitir token. `organizacion` no tiene RLS → se consulta `estado` por org_id
    # directo (sin tocar el contrato de `login_lookup`, que pertenece a db).
    estado = db.execute(
        text("SELECT estado FROM organizacion WHERE id = :org"),
        {"org": org_id},
    ).scalar_one_or_none()
    if estado == "SUSPENDIDA":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Escuela suspendida, contacta al administrador",
        )

    # sucursal_ids para el claim: si es ENTRENADOR podría limitarse a sus
    # categorías en un epic posterior; en este slice damos todas las sucursales
    # de la org (ADMIN ve todo; el gating fino de ficha médica se hace por token).
    # La consulta corre con contexto fijado para respetar RLS.
    db.execute(text("SELECT set_config('app.current_org', :org, true)"), {"org": org_id})
    sucursal_ids = [str(s.id) for s in db.execute(_select_sucursales()).scalars().all()]

    token = create_access_token(
        user_id=str(row["id"]),
        org_id=org_id,
        role=row["role"],
        sucursal_ids=sucursal_ids,
    )
    user = UserOut(
        id=row["id"],
        nombre=row["nombre"],
        email=row["email"],
        role=row["role"],
        org_id=row["org_id"],
    )
    return TokenOut(access_token=token, user=user)


def _select_sucursales():
    from sqlalchemy import select

    return select(Sucursal)


@router.get("/me", response_model=UserOut)
def me(
    user: CurrentUser = Depends(set_tenant_context),
    db: Session = Depends(get_db),
) -> UserOut:
    """Devuelve el usuario autenticado (C4). Corre con contexto de tenant fijado."""
    from sqlalchemy import select

    obj = db.execute(select(Usuario).where(Usuario.id == user.user_id)).scalar_one_or_none()
    if obj is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado")
    return UserOut.model_validate(obj)
