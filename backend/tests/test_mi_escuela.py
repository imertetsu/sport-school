"""Tests de `/mi-escuela` (contrato C2, epic escuela-y-bajas, Fase 1).

Cubre:
- **GET** como ADMIN ⇒ devuelve la escuela (nombre + color) del usuario.
- **PUT** como ADMIN ⇒ actualiza nombre + color y devuelve el recurso.
- **Roles:** ENTRENADOR ⇒ 403 (GET y PUT); sin token ⇒ 401.
- **Validación:** nombre vacío ⇒ 422; color mal formado ⇒ 422.
- **Borde de seguridad (clave del epic):** `organizacion` NO tiene RLS, así que el
  endpoint scopea SIEMPRE a `user.org_id`. Un ADMIN de la org A que dispare un PUT
  (incluso colando un `id` de la org B en el body) SOLO afecta a la org A; la org B
  queda intacta.

Patrón BD idéntico al resto de la suite (`owner_engine` siembra saltando RLS; el
TestClient ejercita la API bajo RLS real con JWT). `organizacion` no tiene RLS, pero
el resto de tablas tenant sí; el guardián de esta tabla es el código del endpoint.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator

import pytest
from app.core.security import create_access_token
from sqlalchemy import text
from sqlalchemy.engine import Engine


# --------------------------------------------------------------------------- #
# Helpers de siembra (con BD)
# --------------------------------------------------------------------------- #
def _sembrar_org(conn, *, org: uuid.UUID, nombre: str, color: str | None) -> None:
    conn.execute(
        text(
            "INSERT INTO organizacion (id, nombre, pais, moneda, modo_cobro_default, "
            "prorratea_primer_periodo, color, created_at, updated_at) "
            "VALUES (:id,:nombre,'BO','BOB','ANIVERSARIO',true,:color,now(),now()) "
            "ON CONFLICT (id) DO NOTHING"
        ),
        {"id": str(org), "nombre": nombre, "color": color},
    )


def _sembrar_admin(conn, *, org: uuid.UUID, user: uuid.UUID, email: str) -> None:
    conn.execute(
        text(
            "INSERT INTO usuario (id, org_id, email, password_hash, role, nombre, "
            "activo, created_at, updated_at) "
            "VALUES (:id,:org,:email,'x','ADMIN','Admin Test',true,now(),now())"
        ),
        {"id": str(user), "org": str(org), "email": email},
    )


def _borrar_org(conn, org: uuid.UUID) -> None:
    conn.execute(text("DELETE FROM usuario WHERE org_id = :o"), {"o": str(org)})
    conn.execute(text("DELETE FROM organizacion WHERE id = :o"), {"o": str(org)})


def _token_admin(org: uuid.UUID, user: uuid.UUID) -> str:
    return create_access_token(user_id=str(user), org_id=str(org), role="ADMIN", sucursal_ids=[])


def _client_or_skip():
    if not os.getenv("DATABASE_URL"):
        pytest.skip("DATABASE_URL no definido; requiere Postgres migrado")
    from app.main import app
    from fastapi.testclient import TestClient

    return TestClient(app)


@pytest.fixture()
def org_admin(owner_engine: Engine) -> Iterator[dict]:
    """Una org (con color de partida) + un usuario ADMIN; limpia al final."""
    org = uuid.uuid4()
    user = uuid.uuid4()
    with owner_engine.begin() as conn:
        _sembrar_org(conn, org=org, nombre="Academia Original", color="#112233")
        _sembrar_admin(conn, org=org, user=user, email=f"admin_{user.hex}@t.test")
    yield {"org": org, "user": user, "token": _token_admin(org, user)}
    with owner_engine.begin() as conn:
        _borrar_org(conn, org)


# --------------------------------------------------------------------------- #
# GET / PUT como ADMIN
# --------------------------------------------------------------------------- #
@pytest.mark.db
def test_get_mi_escuela_admin(org_admin: dict) -> None:
    client = _client_or_skip()
    headers = {"Authorization": f"Bearer {org_admin['token']}"}

    resp = client.get("/api/v1/mi-escuela", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == {"nombre": "Academia Original", "color": "#112233"}


@pytest.mark.db
def test_put_mi_escuela_admin_actualiza(org_admin: dict) -> None:
    client = _client_or_skip()
    headers = {"Authorization": f"Bearer {org_admin['token']}"}

    resp = client.put(
        "/api/v1/mi-escuela",
        headers=headers,
        json={"nombre": "Academia Renovada", "color": "#AABBCC"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"nombre": "Academia Renovada", "color": "#AABBCC"}

    # Persistido: un GET posterior lo refleja.
    again = client.get("/api/v1/mi-escuela", headers=headers).json()
    assert again == {"nombre": "Academia Renovada", "color": "#AABBCC"}


@pytest.mark.db
def test_put_mi_escuela_color_vacio_se_normaliza_a_null(org_admin: dict) -> None:
    """color vacío/None ⇒ se persiste NULL (el front usa default determinista)."""
    client = _client_or_skip()
    headers = {"Authorization": f"Bearer {org_admin['token']}"}

    resp = client.put(
        "/api/v1/mi-escuela",
        headers=headers,
        json={"nombre": "Sin Color", "color": ""},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"nombre": "Sin Color", "color": None}


# --------------------------------------------------------------------------- #
# Roles: ENTRENADOR ⇒ 403; sin token ⇒ 401
# --------------------------------------------------------------------------- #
@pytest.mark.db
def test_mi_escuela_entrenador_403(org_admin: dict) -> None:
    client = _client_or_skip()
    coach_token = create_access_token(
        user_id=str(uuid.uuid4()),
        org_id=str(org_admin["org"]),
        role="ENTRENADOR",
        sucursal_ids=[],
    )
    headers = {"Authorization": f"Bearer {coach_token}"}

    assert client.get("/api/v1/mi-escuela", headers=headers).status_code == 403
    assert (
        client.put(
            "/api/v1/mi-escuela",
            headers=headers,
            json={"nombre": "Hackeada", "color": "#000000"},
        ).status_code
        == 403
    )


@pytest.mark.db
def test_mi_escuela_sin_token_401(org_admin: dict) -> None:
    client = _client_or_skip()
    assert client.get("/api/v1/mi-escuela").status_code == 401
    assert (
        client.put("/api/v1/mi-escuela", json={"nombre": "x", "color": "#000000"}).status_code
        == 401
    )


# --------------------------------------------------------------------------- #
# Validación (422)
# --------------------------------------------------------------------------- #
@pytest.mark.db
def test_put_mi_escuela_nombre_vacio_422(org_admin: dict) -> None:
    client = _client_or_skip()
    headers = {"Authorization": f"Bearer {org_admin['token']}"}
    resp = client.put(
        "/api/v1/mi-escuela",
        headers=headers,
        json={"nombre": "   ", "color": "#112233"},
    )
    assert resp.status_code == 422


@pytest.mark.db
def test_put_mi_escuela_color_mal_formado_422(org_admin: dict) -> None:
    client = _client_or_skip()
    headers = {"Authorization": f"Bearer {org_admin['token']}"}
    for color in ("rojo", "#12345", "#1234ZZ", "112233"):
        resp = client.put(
            "/api/v1/mi-escuela",
            headers=headers,
            json={"nombre": "Academia", "color": color},
        )
        assert resp.status_code == 422, f"color {color!r} debería ser 422"


# --------------------------------------------------------------------------- #
# Borde de seguridad: el endpoint scopea a user.org_id (ignora id del cliente)
# --------------------------------------------------------------------------- #
@pytest.mark.db
def test_put_mi_escuela_no_afecta_a_otra_org(owner_engine: Engine, org_admin: dict) -> None:
    """Un ADMIN de la org A NO puede tocar la org B, ni colando su id en el body.

    `organizacion` no tiene RLS, así que esta prueba es el guardián del borde:
    aunque el body lleve el `id` de otra org, el endpoint solo escribe la org del
    token. La org B debe quedar EXACTAMENTE como estaba.
    """
    org_b = uuid.uuid4()
    with owner_engine.begin() as conn:
        _sembrar_org(conn, org=org_b, nombre="Otra Escuela", color="#FF0000")
    try:
        client = _client_or_skip()
        headers = {"Authorization": f"Bearer {org_admin['token']}"}

        # ADMIN de A intenta colar el id de B en el body (el endpoint lo ignora).
        resp = client.put(
            "/api/v1/mi-escuela",
            headers=headers,
            json={"id": str(org_b), "nombre": "Robada", "color": "#00FF00"},
        )
        assert resp.status_code == 200, resp.text

        with owner_engine.begin() as conn:
            row_a = conn.execute(
                text("SELECT nombre, color FROM organizacion WHERE id = :i"),
                {"i": str(org_admin["org"])},
            ).one()
            row_b = conn.execute(
                text("SELECT nombre, color FROM organizacion WHERE id = :i"),
                {"i": str(org_b)},
            ).one()

        # Solo A cambió; B quedó intacta.
        assert (row_a.nombre, row_a.color) == ("Robada", "#00FF00")
        assert (row_b.nombre, row_b.color) == ("Otra Escuela", "#FF0000")
    finally:
        with owner_engine.begin() as conn:
            _borrar_org(conn, org_b)
