"""Contexto de tenant y autorización (contratos C3, C4, C5).

La barrera real de aislamiento es **RLS en la BD**, no `WHERE org_id`. Estas
dependencias:
  1. Decodifican el Bearer -> `CurrentUser` (user_id, org_id, role, sucursal_ids).
  2. Ejecutan `SET LOCAL app.current_org = :org` en la *misma* transacción del
     request (fail-closed: sin contexto, RLS devuelve 0 filas).
  3. `require_role(...)` restringe endpoints por rol.

Usar `Depends(set_tenant_context)` en todos los endpoints protegidos. /login y
/health NO la aplican (login usa `login_lookup`, que salta RLS de forma
controlada vía SECURITY DEFINER).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.org_context import set_current_org_id
from app.core.security import decode_access_token

_bearer = HTTPBearer(auto_error=False)


@dataclass
class CurrentUser:
    """Identidad derivada del JWT (claims C4)."""

    user_id: str
    org_id: str
    role: str
    sucursal_ids: list[str] = field(default_factory=list)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> CurrentUser:
    """Decodifica el Bearer y devuelve `CurrentUser`. 401 si falta o es inválido."""
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="No autenticado",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = decode_access_token(credentials.credentials)
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido o expirado",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    user_id = payload.get("sub")
    org_id = payload.get("org_id")
    role = payload.get("role")
    # El token de PLATAFORMA (SUPERADMIN) viene SIN `org_id` a propósito (no opera
    # en ninguna escuela). Para ese rol, `org_id` queda en "" (cadena vacía: NUNCA
    # se usa como contexto, y RLS fail-closed con NULLIF da 0 filas). Para cualquier
    # otro rol, la ausencia de `org_id` sigue siendo 401 (sin regresión en escuela).
    if role == "SUPERADMIN":
        if not user_id:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token incompleto",
                headers={"WWW-Authenticate": "Bearer"},
            )
        return CurrentUser(user_id=str(user_id), org_id="", role="SUPERADMIN")

    if not user_id or not org_id or not role:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token incompleto",
            headers={"WWW-Authenticate": "Bearer"},
        )
    sucursal_ids = payload.get("sucursal_ids") or []
    return CurrentUser(
        user_id=str(user_id),
        org_id=str(org_id),
        role=str(role),
        sucursal_ids=[str(s) for s in sucursal_ids],
    )


def set_tenant_context(
    user: CurrentUser = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> CurrentUser:
    """Fija `app.current_org` en la transacción del request (C3, fail-closed).

    `SET LOCAL` solo vive dentro de la transacción actual; al cerrarla (commit/
    rollback en `get_db`) el GUC desaparece, evitando que una request herede el
    tenant de otra al reutilizar la conexión del pool.

    Se usa `set_config(..., true)` (is_local=true) parametrizado para no
    interpolar el uuid en el SQL.
    """
    db.execute(
        text("SELECT set_config('app.current_org', :org, true)"),
        {"org": user.org_id},
    )
    set_current_org_id(str(user.org_id))
    return user


def require_role(*roles: str):
    """Factory de dependencia que exige que el rol del usuario esté en `roles`.

    Se encadena sobre `set_tenant_context` para mantener el contexto fijado.
    """

    allowed = set(roles)

    def _checker(user: CurrentUser = Depends(set_tenant_context)) -> CurrentUser:
        if user.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Rol sin permiso para esta acción",
            )
        return user

    return _checker


def require_superadmin(
    user: CurrentUser = Depends(get_current_user),
) -> CurrentUser:
    """Dependencia de PLATAFORMA (Epic Super Admin): exige `role == "SUPERADMIN"`.

    Diferencia CLAVE con `require_role`: **NO** se encadena sobre `set_tenant_context`
    y por tanto **NUNCA** fija el GUC `app.current_org`. Así el super admin queda
    fail-closed sobre TODA tabla tenant (RLS con NULLIF → 0 filas), aunque consulte
    una por error. Las tablas de plataforma (`plataforma_admin`, `plataforma_auditoria`)
    y `organizacion` no tienen RLS, así que se leen/escriben sin contexto.

    403 si el rol no es SUPERADMIN (un token de escuela válido); 401 (en
    `get_current_user`) si falta o es inválido.
    """
    if user.role != "SUPERADMIN":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Requiere super administrador de plataforma",
        )
    return user
