"""Bootstrap del primer super admin de PLATAFORMA (Epic Super Admin).

La BD de producción arranca vacía: no hay super admin para el primer login de la
consola `/plataforma`. Este comando crea uno a partir de las env
`PLATFORM_ADMIN_EMAIL` / `PLATFORM_ADMIN_PASSWORD` (settings opcionales).

Idempotente por email: si ya existe un super admin con ese email, NO falla ni
duplica (re-correrlo 2× es seguro). `plataforma_admin` NO tiene RLS, así que no
necesita fijar `app.current_org`; aun así, como `app.seed`, conviene correrlo con
una conexión OWNER/de seed.

Cómo correr (desde `backend/`, con la BD migrada a 0012):
    PLATFORM_ADMIN_EMAIL=ops@latinosport.bo PLATFORM_ADMIN_PASSWORD=... \
        .venv/Scripts/python -m app.seed_plataforma     # Windows
    .venv/bin/python -m app.seed_plataforma             # Linux/Mac
"""

from __future__ import annotations

from sqlalchemy import select

from app.core.config import settings
from app.core.db import SessionLocal
from app.core.security import hash_password
from app.models.plataforma_admin import PlataformaAdmin


def seed_plataforma() -> None:
    """Crea el primer super admin si no existe (idempotente por email)."""
    email = settings.platform_admin_email
    password = settings.platform_admin_password
    if not email or not password:
        print(
            "seed_plataforma: PLATFORM_ADMIN_EMAIL/PLATFORM_ADMIN_PASSWORD no definidos; "
            "no se creó ningún super admin."
        )
        return

    db = SessionLocal()
    try:
        existente = db.execute(
            select(PlataformaAdmin).where(PlataformaAdmin.email == email)
        ).scalar_one_or_none()
        if existente is not None:
            print(f"seed_plataforma OK: super admin '{email}' ya existe (sin cambios).")
            return

        db.add(
            PlataformaAdmin(
                email=email,
                password_hash=hash_password(password),
                nombre="Super Admin",
                activo=True,
            )
        )
        db.commit()
        print(f"seed_plataforma OK: super admin '{email}' creado.")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    seed_plataforma()
