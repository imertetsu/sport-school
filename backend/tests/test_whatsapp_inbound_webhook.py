"""Tests del webhook ENTRANTE del gateway (`POST /api/v1/webhooks/whatsapp-inbound`).

Sin BD: el webhook solo valida token, loguea y responde 200 (no escribe en BD). Cubre
C5 de la spec: token válido ⇒ 200; token ausente/incorrecto ⇒ 401.

`settings.whatsapp_gateway_token` se parchea sobre el objeto importado en el módulo del
webhook (`app.api.v1.webhooks.whatsapp_inbound.settings`).
"""

from __future__ import annotations

import pytest
from app.api.v1.webhooks import whatsapp_inbound as inbound_mod
from app.main import create_app
from fastapi.testclient import TestClient

_TOKEN = "gateway-secreto-de-test"

# whatsapp-multitenant: el sidecar multi-sesión ahora incluye `org_id` en el body.
_ORG_ID = "11111111-1111-1111-1111-111111111111"
_PAYLOAD = {
    "org_id": _ORG_ID,
    "from": "59176123456",
    "text": "hola escuela",
    "message_id": "wamid.IN123",
    "timestamp": 1718900000,
}


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(inbound_mod.settings, "whatsapp_gateway_token", _TOKEN, raising=False)
    return TestClient(create_app())


def test_token_valido_responde_200(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/webhooks/whatsapp-inbound",
        json=_PAYLOAD,
        headers={"X-Gateway-Token": _TOKEN},
    )
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_token_valido_con_org_id_loguea_org(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    """whatsapp-multitenant: el body trae `org_id` y el webhook lo incluye en el log."""
    with caplog.at_level("INFO", logger="app.api.v1.webhooks.whatsapp_inbound"):
        resp = client.post(
            "/api/v1/webhooks/whatsapp-inbound",
            json=_PAYLOAD,
            headers={"X-Gateway-Token": _TOKEN},
        )
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
    assert _ORG_ID in caplog.text


def test_token_ausente_responde_401(client: TestClient) -> None:
    resp = client.post("/api/v1/webhooks/whatsapp-inbound", json=_PAYLOAD)
    assert resp.status_code == 401


def test_token_incorrecto_responde_401(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/webhooks/whatsapp-inbound",
        json=_PAYLOAD,
        headers={"X-Gateway-Token": "otro-token"},
    )
    assert resp.status_code == 401


def test_token_configurado_vacio_rechaza_todo(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail-closed: sin token configurado en settings, ni siquiera un header vacío pasa."""
    monkeypatch.setattr(inbound_mod.settings, "whatsapp_gateway_token", None, raising=False)
    client = TestClient(create_app())
    resp = client.post(
        "/api/v1/webhooks/whatsapp-inbound",
        json=_PAYLOAD,
        headers={"X-Gateway-Token": ""},
    )
    assert resp.status_code == 401


def test_ruta_inbound_es_distinta_de_estados_meta(client: TestClient) -> None:
    """La ruta entrante (whatsapp-inbound) NO es la del webhook de estados de Meta.

    `POST /webhooks/whatsapp` (Meta) NO exige `X-Gateway-Token` y responde 200 (ACK).
    """
    resp = client.post("/api/v1/webhooks/whatsapp", json={"entry": []})
    assert resp.status_code == 200
