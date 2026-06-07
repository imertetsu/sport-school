"""Verifica el aislamiento RLS (criterio de aceptación del epic).

Con el rol `latinosport_app` (NOBYPASSRLS):
  1. Sin `app.current_org` fijado -> `SELECT * FROM deportista` devuelve 0 filas (fail-closed).
  2. Con org A fijada -> se ven las filas de A pero NINGUNA de B.

Requiere BD migrada (RLS + rol + GRANTs). Skip si no hay BD (ver conftest).
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

pytestmark = pytest.mark.db


def test_sin_contexto_no_devuelve_filas(app_engine: Engine, two_orgs: dict) -> None:
    """Sin `app.current_org`, RLS fail-closed -> 0 filas."""
    with app_engine.connect() as conn:
        # Nueva transacción sin SET de app.current_org.
        count = conn.execute(text("SELECT count(*) FROM deportista")).scalar_one()
    assert count == 0, "Sin contexto de tenant, deportista debe devolver 0 filas (fail-closed)"


def test_org_a_no_ve_filas_de_org_b(app_engine: Engine, two_orgs: dict) -> None:
    """Con org A fijada se ve A y no B."""
    org_a = str(two_orgs["org_a"])
    org_b = str(two_orgs["org_b"])

    with app_engine.begin() as conn:
        conn.execute(text("SELECT set_config('app.current_org', :o, true)"), {"o": org_a})
        rows = conn.execute(text("SELECT org_id FROM deportista")).scalars().all()

    org_ids = {str(r) for r in rows}
    assert org_a in org_ids, "Con org A fijada se deben ver sus deportistas"
    assert org_b not in org_ids, "Con org A fijada NO se deben ver deportistas de org B"


def test_org_b_solo_ve_lo_suyo(app_engine: Engine, two_orgs: dict) -> None:
    """Simétrico: con org B fijada se ve B y no A."""
    org_a = str(two_orgs["org_a"])
    org_b = str(two_orgs["org_b"])

    with app_engine.begin() as conn:
        conn.execute(text("SELECT set_config('app.current_org', :o, true)"), {"o": org_b})
        rows = conn.execute(text("SELECT org_id FROM deportista")).scalars().all()

    org_ids = {str(r) for r in rows}
    assert org_b in org_ids
    assert org_a not in org_ids
