"""Tests de la API de Deportistas (contratos C4/C5).

- `test_deportista_create_schema_*`: validación dura de tutor+consentimiento a nivel
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
from app.schemas.deportista import DeportistaCreate
from pydantic import ValidationError

# --------------------------------------------------------------------------- #
# Validación dura a nivel schema (sin BD)
# --------------------------------------------------------------------------- #
_BASE_BODY: dict[str, Any] = {
    "sucursal_id": "11111111-1111-1111-1111-111111111111",
    "nombres": "Test Deportista",
    # El CI del DEPORTISTA es OBLIGATORIO a nivel schema (regla de negocio).
    "ci": "CI-12345678",
    "consentimiento": {"version_terminos": "v1", "canal": "PRESENCIAL"},
}


def test_deportista_create_schema_ok() -> None:
    body = dict(_BASE_BODY)
    body["tutores"] = [{"nombres": "Tutor 1", "telefono": "777", "parentesco": "Padre"}]
    obj = DeportistaCreate(**body)  # type: ignore[arg-type]
    assert len(obj.tutores) == 1
    assert obj.consentimiento.version_terminos == "v1"


def test_deportista_create_schema_sin_tutor_falla() -> None:
    """Sin tutores (lista vacía) -> ValidationError (=> 422 en la API)."""
    body = dict(_BASE_BODY)
    body["tutores"] = []
    with pytest.raises(ValidationError):
        DeportistaCreate(**body)  # type: ignore[arg-type]


def test_deportista_create_schema_sin_consentimiento_falla() -> None:
    """Sin consentimiento -> ValidationError (=> 422 en la API)."""
    body = {
        "sucursal_id": _BASE_BODY["sucursal_id"],
        "nombres": "Test",
        "ci": "CI-99999999",
        "tutores": [{"nombres": "Tutor 1"}],
    }
    with pytest.raises(ValidationError):
        DeportistaCreate(**body)  # type: ignore[arg-type]


def test_deportista_create_schema_sin_ci_falla() -> None:
    """CI del DEPORTISTA OBLIGATORIO: sin `ci` (o vacío) -> ValidationError (=> 422).

    Refuerza la asimetría: el deportista DEBE llevar CI; el TUTOR no.
    """
    # Sin `ci` en absoluto.
    body = {
        "sucursal_id": _BASE_BODY["sucursal_id"],
        "nombres": "Sin CI",
        "tutores": [{"nombres": "Tutor 1"}],
        "consentimiento": {"version_terminos": "v1"},
    }
    with pytest.raises(ValidationError):
        DeportistaCreate(**body)  # type: ignore[arg-type]

    # CI presente pero vacío / solo espacios -> también rechazado (validador strip).
    for ci_vacio in ("", "   "):
        body_vacio = dict(body)
        body_vacio["ci"] = ci_vacio
        with pytest.raises(ValidationError):
            DeportistaCreate(**body_vacio)  # type: ignore[arg-type]


def test_deportista_create_tutor_sin_ci_ok() -> None:
    """El TUTOR sin CI SÍ se permite (su CI es opcional), aun con CI del deportista."""
    body = dict(_BASE_BODY)
    # Tutor explícitamente sin `ci` (campo opcional).
    body["tutores"] = [{"nombres": "Tutor sin CI", "telefono": "777"}]
    obj = DeportistaCreate(**body)  # type: ignore[arg-type]
    assert obj.ci == "CI-12345678"
    assert obj.tutores[0].ci is None


def test_deportista_create_disciplina_id_opcional() -> None:
    """`DeportistaCreate` acepta `disciplina_id` opcional (default None) sin perder el
    texto legacy `disciplina` (S3: FK canónica al catálogo global)."""
    import uuid

    body = dict(_BASE_BODY)
    body["tutores"] = [{"nombres": "Tutor 1"}]
    sin = DeportistaCreate(**body)  # type: ignore[arg-type]
    assert sin.disciplina_id is None

    disc_id = uuid.uuid4()
    body2 = dict(_BASE_BODY)
    body2["tutores"] = [{"nombres": "Tutor 1"}]
    body2["disciplina_id"] = str(disc_id)
    body2["disciplina"] = "Voley (texto legacy)"
    con = DeportistaCreate(**body2)  # type: ignore[arg-type]
    assert con.disciplina_id == disc_id
    assert con.disciplina == "Voley (texto legacy)"  # legacy se conserva


def test_deportista_update_acepta_disciplina_id() -> None:
    """`DeportistaUpdate` acepta `disciplina_id` opcional (S3)."""
    import uuid

    from app.schemas.deportista import DeportistaUpdate

    disc_id = uuid.uuid4()
    u = DeportistaUpdate(disciplina_id=disc_id)
    assert u.disciplina_id == disc_id
    # Si no se envía, queda exclude_unset (no fuerza None destructivo).
    assert "disciplina_id" not in DeportistaUpdate().model_dump(exclude_unset=True)


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
def test_login_y_listar_deportistas() -> None:
    client = _client_or_skip()
    token = _login_admin(client)
    resp = client.get(
        "/api/v1/deportistas",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data and "total" in data and "page" in data
    assert isinstance(data["items"], list)


@pytest.mark.db
def test_listar_sin_token_401() -> None:
    client = _client_or_skip()
    resp = client.get("/api/v1/deportistas")
    assert resp.status_code == 401


@pytest.mark.db
def test_crear_deportista_sin_tutor_422() -> None:
    client = _client_or_skip()
    token = _login_admin(client)
    # tomamos una sucursal real
    suc = client.get("/api/v1/sucursales", headers={"Authorization": f"Bearer {token}"}).json()
    sucursal_id = suc[0]["id"] if suc else "11111111-1111-1111-1111-111111111111"
    resp = client.post(
        "/api/v1/deportistas",
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
    """Comportamiento REAL hoy: el ENTRENADOR lista/ve sus deportistas (red de seguridad
    por disciplina) y, como su JWT incluye TODAS las sucursales de la org (auth.py lo
    hace a propósito), `_puede_ver_ficha` da True -> el coach SÍ ve la ficha médica.

    NOTA: el gating fino "el coach NO ve la ficha de otra sucursal" requiere que el token
    LIMITE las sucursales del entrenador (épica futura); hoy el entrenador trae todas, así
    que aquí solo afirmamos lo que el auth produce de verdad: el coach ve al deportista
    (200) y su ficha (campo presente, con datos si el deportista los tiene).
    """
    client = _client_or_skip()
    admin_token = _login_admin(client)

    # ADMIN: el contrato del detalle incluye `ficha_medica`.
    lista_admin = client.get(
        "/api/v1/deportistas?page_size=50",
        headers={"Authorization": f"Bearer {admin_token}"},
    ).json()
    if not lista_admin["items"]:
        pytest.skip("No hay deportistas; ¿seed ejecutado?")
    detalle_admin = client.get(
        f"/api/v1/deportistas/{lista_admin['items'][0]['id']}",
        headers={"Authorization": f"Bearer {admin_token}"},
    ).json()
    assert "ficha_medica" in detalle_admin

    # ENTRENADOR: tomar el deportista de SU PROPIA lista (siempre visible bajo la red
    # de seguridad por disciplina), no de la del admin.
    coach = client.post(
        "/api/v1/auth/login",
        json={"email": "coach@latinosport.bo", "password": "coach1234"},
    )
    if coach.status_code != 200:
        pytest.skip("Entrenador no sembrado")
    coach_token = coach.json()["access_token"]
    coach_headers = {"Authorization": f"Bearer {coach_token}"}

    lista_coach = client.get("/api/v1/deportistas?page_size=50", headers=coach_headers).json()
    if not lista_coach["items"]:
        pytest.skip("El entrenador no ve deportistas; ¿seed con disciplinas?")

    deportista_id = lista_coach["items"][0]["id"]
    detalle_coach = client.get(f"/api/v1/deportistas/{deportista_id}", headers=coach_headers)
    # 200 (visible) y el contrato del detalle expone `ficha_medica` (no 404 genérico del
    # scoping viejo: la red de seguridad solo bloquea si hay conflicto real de disciplina).
    assert detalle_coach.status_code == 200, detalle_coach.text
    assert "ficha_medica" in detalle_coach.json()


@pytest.mark.db
def test_crear_y_actualizar_campos_opcionales() -> None:
    """`domicilio` y `lugar_nacimiento` se persisten en el alta, vuelven en el detalle
    y se actualizan vía PUT (misma semántica que `contacto_emergencia`).

    No están en el item de lista (resumen), solo en el detalle (C5).
    """
    client = _client_or_skip()
    token = _login_admin(client)
    headers = {"Authorization": f"Bearer {token}"}

    suc = client.get("/api/v1/sucursales", headers=headers).json()
    if not suc:
        pytest.skip("No hay sucursales; ¿seed ejecutado?")
    sucursal_id = suc[0]["id"]

    import uuid as _uuid

    ci = f"CI-OPT-{_uuid.uuid4().hex[:10]}"
    resp = client.post(
        "/api/v1/deportistas",
        headers=headers,
        json={
            "sucursal_id": sucursal_id,
            "nombres": "Campos Opcionales",
            "ci": ci,
            "domicilio": "Calle Falsa 123, Zona Sur",
            "lugar_nacimiento": "Cochabamba, Bolivia",
            "tutores": [{"nombres": "Tutor Opt", "telefono": "777"}],
            "consentimiento": {"version_terminos": "v1", "canal": "PRESENCIAL"},
        },
    )
    assert resp.status_code == 201, resp.text
    creado = resp.json()
    assert creado["domicilio"] == "Calle Falsa 123, Zona Sur"
    assert creado["lugar_nacimiento"] == "Cochabamba, Bolivia"
    deportista_id = creado["id"]

    # El detalle (GET) los devuelve.
    detalle = client.get(f"/api/v1/deportistas/{deportista_id}", headers=headers)
    assert detalle.status_code == 200
    detalle_json = detalle.json()
    assert detalle_json["domicilio"] == "Calle Falsa 123, Zona Sur"
    assert detalle_json["lugar_nacimiento"] == "Cochabamba, Bolivia"

    # El item de lista NO los incluye (es resumen).
    lista = client.get(f"/api/v1/deportistas?q={ci}&page_size=50", headers=headers).json()
    items = [it for it in lista["items"] if it["id"] == deportista_id]
    if items:
        assert "domicilio" not in items[0]
        assert "lugar_nacimiento" not in items[0]

    # PUT los actualiza.
    upd = client.put(
        f"/api/v1/deportistas/{deportista_id}",
        headers=headers,
        json={
            "domicilio": "Av. Nueva 456",
            "lugar_nacimiento": "La Paz, Bolivia",
        },
    )
    assert upd.status_code == 200, upd.text
    upd_json = upd.json()
    assert upd_json["domicilio"] == "Av. Nueva 456"
    assert upd_json["lugar_nacimiento"] == "La Paz, Bolivia"
