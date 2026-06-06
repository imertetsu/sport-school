"""Alembic environment para LatinoSport.

Reglas del contrato (C2 del epic scaffolding-alumnos):
- Alembic corre como OWNER/superusuario (rol `postgres`), NUNCA como
  `latinosport_app`. La URL de conexion sale de la variable de entorno
  `MIGRATION_DATABASE_URL` (p.ej. postgresql+psycopg://postgres:postgres@db:5432/latinosport).
  No se hardcodean credenciales: se leen de os.environ.
- `target_metadata` es `Base.metadata` del backend (contrato compartido).
  `prepend_sys_path = backend` en alembic.ini hace que `import app...` funcione.

Soporta modo online (con conexion viva). El modo offline se incluye por
completitud estandar de Alembic.
"""
from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Config de Alembic (lee alembic.ini).
config = context.config

# Logging segun el ini, si hay archivo de config.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def _get_database_url() -> str:
    """Obtiene la URL de migracion exclusivamente del entorno.

    Alembic corre como owner: se usa MIGRATION_DATABASE_URL (rol postgres),
    no DATABASE_URL (rol latinosport_app, que es NOBYPASSRLS y no puede gestionar
    roles/policies/funciones SECURITY DEFINER).
    """
    url = os.environ.get("MIGRATION_DATABASE_URL")
    if not url:
        raise RuntimeError(
            "MIGRATION_DATABASE_URL no esta definida. Alembic debe correr como "
            "owner/superusuario. Ejemplo: "
            "postgresql+psycopg://postgres:postgres@db:5432/latinosport"
        )
    return url


# target_metadata: metadata de los modelos del backend (contrato compartido).
# Se importa de forma diferida y tolerante: la migracion 0001 esta escrita a
# mano (DDL explicito) y NO usa autogenerate, asi que puede aplicarse aunque
# los modelos aun no existan (trabajo en paralelo con backend-dev). Cuando los
# modelos existan, `--autogenerate` de revisiones futuras los detectara.
try:
    from app.models import Base  # type: ignore

    target_metadata = Base.metadata
except Exception:  # pragma: no cover - backend en paralelo / aun sin modelos
    target_metadata = None


def run_migrations_offline() -> None:
    """Ejecuta migraciones en modo 'offline' (genera SQL sin conexion)."""
    url = _get_database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Ejecuta migraciones en modo 'online' (con conexion viva)."""
    configuration = config.get_section(config.config_ini_section) or {}
    # La URL del entorno tiene prioridad: NUNCA se toma de alembic.ini.
    configuration["sqlalchemy.url"] = _get_database_url()

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
