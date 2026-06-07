"""Fixtures de tests.

Los tests que tocan la BD requieren PostgreSQL **migrado** (esquema + RLS + rol
`latinosport_app` + función `login_lookup`), que levanta infra-dev con docker. Si no
hay BD alcanzable, los tests marcados `db` se **omiten** (skip) en vez de fallar.

Variables de entorno usadas:
- `DATABASE_URL`         -> conexión de la app (rol `latinosport_app`, NOBYPASSRLS).
- `MIGRATION_DATABASE_URL` -> conexión owner (rol postgres), para insertar datos de
  fixture saltando RLS al sembrar 2 orgs en el test de aislamiento.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine


def _db_url() -> str | None:
    return os.getenv("DATABASE_URL")


def _owner_url() -> str | None:
    return os.getenv("MIGRATION_DATABASE_URL")


def _reachable(url: str | None) -> bool:
    if not url:
        return False
    try:
        eng = create_engine(url, pool_pre_ping=True, future=True)
        with eng.connect() as conn:
            conn.execute(text("SELECT 1"))
        eng.dispose()
        return True
    except Exception:
        return False


@pytest.fixture(scope="session")
def app_engine() -> Iterator[Engine]:
    """Engine con el rol de app (`latinosport_app`). Skip si no hay BD."""
    url = _db_url()
    if not _reachable(url):
        pytest.skip("DATABASE_URL no alcanzable; requiere Postgres migrado (infra-dev/docker)")
    eng = create_engine(url, pool_pre_ping=True, future=True)  # type: ignore[arg-type]
    yield eng
    eng.dispose()


@pytest.fixture(scope="session")
def owner_engine() -> Iterator[Engine]:
    """Engine con el rol owner (postgres). Usado para sembrar fixtures saltando RLS."""
    url = _owner_url()
    if not _reachable(url):
        pytest.skip(
            "MIGRATION_DATABASE_URL no alcanzable; requiere Postgres migrado (infra-dev/docker)"
        )
    eng = create_engine(url, pool_pre_ping=True, future=True)  # type: ignore[arg-type]
    yield eng
    eng.dispose()


@pytest.fixture()
def two_orgs(owner_engine: Engine):
    """Crea 2 organizaciones con 1 deportista cada una (como owner, saltando RLS).

    Limpia al final. Devuelve `(org_a_id, org_b_id)`.
    """
    org_a = uuid.uuid4()
    org_b = uuid.uuid4()
    suc_a = uuid.uuid4()
    suc_b = uuid.uuid4()
    al_a = uuid.uuid4()
    al_b = uuid.uuid4()

    with owner_engine.begin() as conn:
        for org_id, nombre in ((org_a, "Org A (test)"), (org_b, "Org B (test)")):
            conn.execute(
                text(
                    "INSERT INTO organizacion (id, nombre, pais, moneda, "
                    "modo_cobro_default, prorratea_primer_periodo, created_at, updated_at) "
                    "VALUES (:id, :nombre, 'BO', 'BOB', 'ANIVERSARIO', true, now(), now())"
                ),
                {"id": str(org_id), "nombre": nombre},
            )
        for org_id, suc_id in ((org_a, suc_a), (org_b, suc_b)):
            conn.execute(
                text(
                    "INSERT INTO sucursal (id, org_id, nombre, created_at, updated_at) "
                    "VALUES (:id, :org, 'Sucursal', now(), now())"
                ),
                {"id": str(suc_id), "org": str(org_id)},
            )
        for org_id, suc_id, al_id, nom in (
            (org_a, suc_a, al_a, "Deportista A"),
            (org_b, suc_b, al_b, "Deportista B"),
        ):
            conn.execute(
                text(
                    "INSERT INTO deportista (id, org_id, sucursal_id, nombres, "
                    "created_at, updated_at) "
                    "VALUES (:id, :org, :suc, :nom, now(), now())"
                ),
                {"id": str(al_id), "org": str(org_id), "suc": str(suc_id), "nom": nom},
            )

    yield {"org_a": org_a, "org_b": org_b, "deportista_a": al_a, "deportista_b": al_b}

    with owner_engine.begin() as conn:
        for org_id in (org_a, org_b):
            conn.execute(text("DELETE FROM deportista WHERE org_id = :o"), {"o": str(org_id)})
            conn.execute(text("DELETE FROM sucursal WHERE org_id = :o"), {"o": str(org_id)})
            conn.execute(text("DELETE FROM organizacion WHERE id = :o"), {"o": str(org_id)})
