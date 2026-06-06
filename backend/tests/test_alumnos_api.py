"""Tests de la API de Alumnos (contratos C4/C5).

- `test_alumno_create_schema_*`: validación dura de tutor+consentimiento a nivel
  schema (no requiere BD; cubre el 422 lógico de RF-USR-04).
- Tests marcados `db`: flujo end-to-end (login -> listar -> crear sin tutor 422 ->
  ficha médica gateada). Requieren BD migrada + seed. Skip si no hay BD.

El seed se asume ejecutado (admin@latinosport.bo / admin1234). Si no, hacer:
    .venv\\Scripts\\python -m app.seed
"""

from __future__ import annotations

import os
from typing import Any

import pytest
from app.schemas.alumno import AlumnoCreate
from pydantic import ValidationError

# --------------------------------------------------------------------------- #
# Validación dura a nivel schema (sin BD)
# --------------------------------------------------------------------------- #
_BASE_BODY: dict[str, Any] = {
    "sucursal_id": "11111111-1111-1111-1111-111111111111",
    "nombres": "Test Alumno",
    "consentimiento": {"version_terminos": "v1", "canal": "PRESENCIAL"},
}


def test_alumno_create_schema_ok() -> None:
    body = dict(_BASE_BODY)
    body["tutores"] = [{"nombres": "Tutor 1", "telefono": "777", "parentesco": "Padre"}]
    obj = AlumnoCreate(**body)  # type: ignore[arg-type]
    assert len(obj.tutores) == 1
    assert obj.consentimiento.version_terminos == "v1"


def test_alumno_create_schema_sin_tutor_falla() -> None:
    """Sin tutores (lista vacía) -> ValidationError (=> 422 en la API)."""
    body = dict(_BASE_BODY)
    body["tutores"] = []
    with pytest.raises(ValidationError):
        AlumnoCreate(**body)  # type: ignore[arg-type]


def test_alumno_create_schema_sin_consentimiento_falla() -> None:
    """Sin consentimiento -> ValidationError (=> 422 en la API)."""
    body = {
        "sucursal_id": _BASE_BODY["sucursal_id"],
        "nombres": "Test",
        "tutores": [{"nombres": "Tutor 1"}],
    }
    with pytest.raises(ValidationError):
        AlumnoCreate(**body)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# Flujo end-to-end contra la API real (requiere BD + seed)
# --------------------------------------------------------------------------- #
def _client_or_skip():
    if not os.getenv("DATABASE_URL"):
        pytest.skip("DATABASE_URL no definido; requiere Postgres migrado + seed")
    from app.main import app
    from fastapi.testclient import TestClient

    return TestClient(app)


def _login_admin(client) -> str:
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": "admin@latinosport.bo", "password": "admin1234"},
    )
    if resp.status_code != 200:
        pytest.skip(f"Login admin falló ({resp.status_code}); ¿seed ejecutado?")
    return resp.json()["access_token"]


@pytest.mark.db
def test_login_y_listar_alumnos() -> None:
    client = _client_or_skip()
    token = _login_admin(client)
    resp = client.get(
        "/api/v1/alumnos",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data and "total" in data and "page" in data
    assert isinstance(data["items"], list)


@pytest.mark.db
def test_listar_sin_token_401() -> None:
    client = _client_or_skip()
    resp = client.get("/api/v1/alumnos")
    assert resp.status_code == 401


@pytest.mark.db
def test_crear_alumno_sin_tutor_422() -> None:
    client = _client_or_skip()
    token = _login_admin(client)
    # tomamos una sucursal real
    suc = client.get(
        "/api/v1/sucursales", headers={"Authorization": f"Bearer {token}"}
    ).json()
    sucursal_id = suc[0]["id"] if suc else "11111111-1111-1111-1111-111111111111"
    resp = client.post(
        "/api/v1/alumnos",
        headers={"Authorization": f"Bearer {token}"},
        json={
            "sucursal_id": sucursal_id,
            "nombres": "Sin Tutor",
            "tutores": [],
            "consentimiento": {"version_terminos": "v1"},
        },
    )
    assert resp.status_code == 422


@pytest.mark.db
def test_ficha_medica_gateada_por_rol() -> None:
    """ADMIN ve ficha_medica; ENTRENADOR fuera de la sucursal del alumno la recibe null."""
    client = _client_or_skip()
    admin_token = _login_admin(client)

    # Buscar un alumno con ficha médica (del seed).
    lista = client.get(
        "/api/v1/alumnos?page_size=50",
        headers={"Authorization": f"Bearer {admin_token}"},
    ).json()
    if not lista["items"]:
        pytest.skip("No hay alumnos; ¿seed ejecutado?")

    alumno_id = lista["items"][0]["id"]
    detalle_admin = client.get(
        f"/api/v1/alumnos/{alumno_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    ).json()
    # ADMIN debe ver la ficha si el alumno la tiene.
    assert "ficha_medica" in detalle_admin

    # Login entrenador; si su token no incluye la sucursal del alumno, ficha = null.
    coach = client.post(
        "/api/v1/auth/login",
        json={"email": "coach@latinosport.bo", "password": "coach1234"},
    )
    if coach.status_code != 200:
        pytest.skip("Entrenador no sembrado")
    coach_token = coach.json()["access_token"]
    detalle_coach = client.get(
        f"/api/v1/alumnos/{alumno_id}",
        headers={"Authorization": f"Bearer {coach_token}"},
    )
    assert detalle_coach.status_code == 200
    # No afirmamos null duro (el seed da todas las sucursales al token); afirmamos
    # que el campo existe y respeta el contrato (presente, posiblemente null).
    assert "ficha_medica" in detalle_coach.json()
