"""Tests de `/mi-escuela/whatsapp/*` (contrato 4, epic whatsapp-multitenant).

Cubre:
- **GET /estado**: reconcilia la fila contra el sidecar; sidecar caído ⇒ último estado de BD.
- **POST /vincular**: lazy QR del sidecar (qr / connected / qr:null) → fila + shape.
- **DELETE**: desvincula en el sidecar → fila DESVINCULADA, numero=null.
- **Roles**: ENTRENADOR ⇒ 403; sin token ⇒ 401 (solo ADMIN, org del token).
- **RLS** de `whatsapp_sesion`: sin contexto ⇒ 0 filas (fail-closed con NULLIF).

El backend es el ÚNICO que habla con el sidecar: se mockea `httpx.request` sobre el
módulo del router (`app.api.v1.whatsapp_sesion`) — ningún test pega a la red real. La
siembra de org/admin usa `owner_engine` (salta RLS); la API se ejercita bajo RLS real
con un JWT de ADMIN.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from app.core.security import create_access_token
from sqlalchemy import text
from sqlalchemy.engine import Engine

pytestmark = pytest.mark.db


# --------------------------------------------------------------------------- #
# Doble del sidecar: stub de httpx.request en el módulo del router
# --------------------------------------------------------------------------- #
class _FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


def _install_sidecar(monkeypatch: pytest.MonkeyPatch, responder: Any) -> list[dict[str, Any]]:
    """Parchea `httpx.request` del router para devolver lo que dicte `responder(method, url)`.

    Devuelve la lista de llamadas capturadas (para asegurar que se pega a `/sessions/{org}`).
    """
    from app.api.v1 import whatsapp_sesion as mod

    calls: list[dict[str, Any]] = []

    def _fake_request(method: str, url: str, **kwargs: Any) -> Any:
        calls.append({"method": method, "url": url, "kwargs": kwargs})
        return responder(method, url)

    monkeypatch.setattr(mod.httpx, "request", _fake_request)
    monkeypatch.setattr(mod.settings, "whatsapp_gateway_url", "http://gw:3000", raising=False)
    monkeypatch.setattr(mod.settings, "whatsapp_gateway_token", "tok-test", raising=False)
    return calls


# --------------------------------------------------------------------------- #
# Siembra
# --------------------------------------------------------------------------- #
def _sembrar_org_admin(conn, *, org: uuid.UUID, user: uuid.UUID) -> None:
    conn.execute(
        text(
            "INSERT INTO organizacion (id, nombre, pais, moneda, modo_cobro_default, "
            "prorratea_primer_periodo, created_at, updated_at) "
            "VALUES (:id,'Academia WA','BO','BOB','ANIVERSARIO',true,now(),now()) "
            "ON CONFLICT (id) DO NOTHING"
        ),
        {"id": str(org)},
    )
    conn.execute(
        text(
            "INSERT INTO usuario (id, org_id, email, password_hash, role, nombre, "
            "activo, created_at, updated_at) "
            "VALUES (:id,:org,:email,'x','ADMIN','Admin WA',true,now(),now())"
        ),
        {"id": str(user), "org": str(org), "email": f"admin_{user.hex}@t.test"},
    )


def _borrar_org(conn, org: uuid.UUID) -> None:
    conn.execute(text("DELETE FROM whatsapp_sesion WHERE org_id = :o"), {"o": str(org)})
    conn.execute(text("DELETE FROM usuario WHERE org_id = :o"), {"o": str(org)})
    conn.execute(text("DELETE FROM organizacion WHERE id = :o"), {"o": str(org)})


def _client_or_skip():
    if not os.getenv("DATABASE_URL"):
        pytest.skip("DATABASE_URL no definido; requiere Postgres migrado")
    from app.main import app
    from fastapi.testclient import TestClient

    return TestClient(app)


@pytest.fixture()
def org_admin(owner_engine: Engine) -> Iterator[dict]:
    org = uuid.uuid4()
    user = uuid.uuid4()
    with owner_engine.begin() as conn:
        _sembrar_org_admin(conn, org=org, user=user)
    token = create_access_token(user_id=str(user), org_id=str(org), role="ADMIN", sucursal_ids=[])
    yield {"org": org, "user": user, "token": token}
    with owner_engine.begin() as conn:
        _borrar_org(conn, org)


# --------------------------------------------------------------------------- #
# GET /estado — reconcilia
# --------------------------------------------------------------------------- #
def test_estado_conectado_reconcilia_fila(
    monkeypatch: pytest.MonkeyPatch, org_admin: dict, owner_engine: Engine
) -> None:
    def _responder(method: str, url: str) -> Any:
        return _FakeResponse(
            {"org_id": str(org_admin["org"]), "connected": True, "number": "59177"}
        )

    calls = _install_sidecar(monkeypatch, _responder)
    client = _client_or_skip()
    headers = {"Authorization": f"Bearer {org_admin['token']}"}

    resp = client.get("/api/v1/mi-escuela/whatsapp/estado", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["estado"] == "CONECTADA"
    assert body["numero"] == "59177"
    assert body["vinculado_en"] is not None
    # Pegó al sidecar por-org.
    assert calls and calls[0]["url"] == f"http://gw:3000/sessions/{org_admin['org']}/status"

    # La fila quedó persistida CONECTADA.
    with owner_engine.begin() as conn:
        row = conn.execute(
            text("SELECT estado, numero FROM whatsapp_sesion WHERE org_id = :o"),
            {"o": str(org_admin["org"])},
        ).one()
    assert (row.estado, row.numero) == ("CONECTADA", "59177")


def test_estado_sidecar_caido_devuelve_ultimo_estado_bd(
    monkeypatch: pytest.MonkeyPatch, org_admin: dict, owner_engine: Engine
) -> None:
    """Sidecar no responde ⇒ último estado conocido de la BD (no 500)."""
    import httpx

    # Siembra una fila CONECTADA previa (como owner, salta RLS).
    with owner_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO whatsapp_sesion (id, org_id, estado, numero, vinculado_en, "
                "created_at, updated_at) "
                "VALUES (:id,:org,'CONECTADA','59199',now(),now(),now())"
            ),
            {"id": str(uuid.uuid4()), "org": str(org_admin["org"])},
        )

    def _responder(method: str, url: str) -> Any:
        raise httpx.ConnectError("sidecar down")

    _install_sidecar(monkeypatch, _responder)
    client = _client_or_skip()
    headers = {"Authorization": f"Bearer {org_admin['token']}"}

    resp = client.get("/api/v1/mi-escuela/whatsapp/estado", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["estado"] == "CONECTADA"
    assert body["numero"] == "59199"


# --------------------------------------------------------------------------- #
# POST /vincular — lazy QR
# --------------------------------------------------------------------------- #
def test_vincular_devuelve_qr_y_marca_pendiente(
    monkeypatch: pytest.MonkeyPatch, org_admin: dict, owner_engine: Engine
) -> None:
    def _responder(method: str, url: str) -> Any:
        return _FakeResponse({"connected": False, "qr": "data:image/png;base64,AAA"})

    _install_sidecar(monkeypatch, _responder)
    client = _client_or_skip()
    headers = {"Authorization": f"Bearer {org_admin['token']}"}

    resp = client.post("/api/v1/mi-escuela/whatsapp/vincular", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == {"estado": "PENDIENTE_QR", "qr": "data:image/png;base64,AAA", "numero": None}

    with owner_engine.begin() as conn:
        row = conn.execute(
            text("SELECT estado FROM whatsapp_sesion WHERE org_id = :o"),
            {"o": str(org_admin["org"])},
        ).one()
    assert row.estado == "PENDIENTE_QR"


def test_vincular_qr_null_responde_pendiente_sin_qr(
    monkeypatch: pytest.MonkeyPatch, org_admin: dict
) -> None:
    def _responder(method: str, url: str) -> Any:
        return _FakeResponse({"connected": False, "qr": None, "error": "aun no hay QR"})

    _install_sidecar(monkeypatch, _responder)
    client = _client_or_skip()
    headers = {"Authorization": f"Bearer {org_admin['token']}"}

    resp = client.post("/api/v1/mi-escuela/whatsapp/vincular", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"estado": "PENDIENTE_QR", "qr": None, "numero": None}


def test_vincular_ya_conectado_marca_conectada(
    monkeypatch: pytest.MonkeyPatch, org_admin: dict, owner_engine: Engine
) -> None:
    def _responder(method: str, url: str) -> Any:
        return _FakeResponse({"connected": True, "number": "59188"})

    _install_sidecar(monkeypatch, _responder)
    client = _client_or_skip()
    headers = {"Authorization": f"Bearer {org_admin['token']}"}

    resp = client.post("/api/v1/mi-escuela/whatsapp/vincular", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"estado": "CONECTADA", "qr": None, "numero": "59188"}

    with owner_engine.begin() as conn:
        row = conn.execute(
            text("SELECT estado, numero FROM whatsapp_sesion WHERE org_id = :o"),
            {"o": str(org_admin["org"])},
        ).one()
    assert (row.estado, row.numero) == ("CONECTADA", "59188")


# --------------------------------------------------------------------------- #
# DELETE — desvincular
# --------------------------------------------------------------------------- #
def test_desvincular_marca_desvinculada(
    monkeypatch: pytest.MonkeyPatch, org_admin: dict, owner_engine: Engine
) -> None:
    # Fila CONECTADA previa.
    with owner_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO whatsapp_sesion (id, org_id, estado, numero, vinculado_en, "
                "created_at, updated_at) "
                "VALUES (:id,:org,'CONECTADA','59177',now(),now(),now())"
            ),
            {"id": str(uuid.uuid4()), "org": str(org_admin["org"])},
        )

    def _responder(method: str, url: str) -> Any:
        return _FakeResponse({"org_id": str(org_admin["org"]), "ok": True})

    calls = _install_sidecar(monkeypatch, _responder)
    client = _client_or_skip()
    headers = {"Authorization": f"Bearer {org_admin['token']}"}

    resp = client.request("DELETE", "/api/v1/mi-escuela/whatsapp", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"estado": "DESVINCULADA", "numero": None, "vinculado_en": None}
    assert calls and calls[0]["method"] == "DELETE"
    assert calls[0]["url"] == f"http://gw:3000/sessions/{org_admin['org']}"

    with owner_engine.begin() as conn:
        row = conn.execute(
            text("SELECT estado, numero FROM whatsapp_sesion WHERE org_id = :o"),
            {"o": str(org_admin["org"])},
        ).one()
    assert (row.estado, row.numero) == ("DESVINCULADA", None)


# --------------------------------------------------------------------------- #
# Roles
# --------------------------------------------------------------------------- #
def test_entrenador_403(monkeypatch: pytest.MonkeyPatch, org_admin: dict) -> None:
    _install_sidecar(monkeypatch, lambda m, u: _FakeResponse({"connected": False, "qr": None}))
    client = _client_or_skip()
    coach = create_access_token(
        user_id=str(uuid.uuid4()), org_id=str(org_admin["org"]), role="ENTRENADOR", sucursal_ids=[]
    )
    headers = {"Authorization": f"Bearer {coach}"}
    assert client.get("/api/v1/mi-escuela/whatsapp/estado", headers=headers).status_code == 403


def test_sin_token_401() -> None:
    client = _client_or_skip()
    assert client.get("/api/v1/mi-escuela/whatsapp/estado").status_code == 401


# --------------------------------------------------------------------------- #
# RLS de whatsapp_sesion: sin contexto ⇒ 0 filas (fail-closed)
# --------------------------------------------------------------------------- #
def test_rls_sin_contexto_no_devuelve_filas(
    app_engine: Engine, owner_engine: Engine, org_admin: dict
) -> None:
    """Con una fila sembrada para la org, una conexión SIN `app.current_org` ve 0 filas."""
    with owner_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO whatsapp_sesion (id, org_id, estado, created_at, updated_at) "
                "VALUES (:id,:org,'CONECTADA',now(),now())"
            ),
            {"id": str(uuid.uuid4()), "org": str(org_admin["org"])},
        )

    with app_engine.connect() as conn:
        count = conn.execute(text("SELECT count(*) FROM whatsapp_sesion")).scalar_one()
    assert count == 0, "Sin contexto de tenant, whatsapp_sesion debe devolver 0 filas (fail-closed)"


def test_rls_org_a_no_ve_fila_de_org_b(
    app_engine: Engine, owner_engine: Engine, org_admin: dict
) -> None:
    """Con org A fijada se ve SU fila y ninguna de otra org."""
    org_b = uuid.uuid4()
    user_b = uuid.uuid4()
    with owner_engine.begin() as conn:
        _sembrar_org_admin(conn, org=org_b, user=user_b)
        for org in (org_admin["org"], org_b):
            conn.execute(
                text(
                    "INSERT INTO whatsapp_sesion (id, org_id, estado, created_at, updated_at) "
                    "VALUES (:id,:org,'CONECTADA',now(),now())"
                ),
                {"id": str(uuid.uuid4()), "org": str(org)},
            )
    try:
        org_a = str(org_admin["org"])
        with app_engine.begin() as conn:
            conn.execute(text("SELECT set_config('app.current_org', :o, true)"), {"o": org_a})
            rows = conn.execute(text("SELECT org_id FROM whatsapp_sesion")).scalars().all()
        org_ids = {str(r) for r in rows}
        assert org_a in org_ids
        assert str(org_b) not in org_ids
    finally:
        with owner_engine.begin() as conn:
            _borrar_org(conn, org_b)
