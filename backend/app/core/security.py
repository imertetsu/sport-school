"""Hashing de contraseñas (bcrypt directo) y JWT HS256 (PyJWT) — claims de C4.

Se usa `bcrypt` directamente en vez de passlib: passlib 1.7.4 es incompatible con
bcrypt >= 4.1 (su `detect_wrap_bug` lanza ValueError al inicializar el backend).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
import jwt

from app.core.config import settings


# --------------------------------------------------------------------------- #
# Contraseñas
# --------------------------------------------------------------------------- #
def _pw_bytes(plain: str) -> bytes:
    """bcrypt sólo admite hasta 72 bytes; truncamos explícitamente (bcrypt 4.x
    ya no lo hace solo y lanza ValueError)."""
    return plain.encode("utf-8")[:72]


def hash_password(plain: str) -> str:
    """Devuelve el hash bcrypt de una contraseña en claro."""
    return bcrypt.hashpw(_pw_bytes(plain), bcrypt.gensalt()).decode("ascii")


def verify_password(plain: str, password_hash: str) -> bool:
    """Verifica una contraseña contra su hash bcrypt."""
    try:
        return bcrypt.checkpw(_pw_bytes(plain), password_hash.encode("ascii"))
    except (ValueError, TypeError):
        return False


# --------------------------------------------------------------------------- #
# JWT (HS256) — claims C4: sub, org_id, role, sucursal_ids, exp
# --------------------------------------------------------------------------- #
def create_access_token(
    *,
    user_id: str,
    org_id: str,
    role: str,
    sucursal_ids: list[str],
    expires_minutes: int | None = None,
) -> str:
    """Codifica un access token con los claims del contrato C4."""
    minutes = expires_minutes if expires_minutes is not None else settings.jwt_expire_minutes
    expire = datetime.now(UTC) + timedelta(minutes=minutes)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "org_id": str(org_id),
        "role": role,
        "sucursal_ids": [str(s) for s in sucursal_ids],
        "exp": expire,
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any]:
    """Decodifica/valida un access token. Lanza `jwt.PyJWTError` si es inválido/expirado."""
    decoded: dict[str, Any] = jwt.decode(
        token,
        settings.jwt_secret,
        algorithms=[settings.jwt_algorithm],
    )
    return decoded
