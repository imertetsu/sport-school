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


# --------------------------------------------------------------------------- #
# Imagen (comprobante de pago) — epic pagos-qr-comprobante (C4). Sin BD: se
# parchea el servicio para verificar que el webhook lo invoca SOLO con tipo:image.
# --------------------------------------------------------------------------- #
_IMG_PAYLOAD = {
    "org_id": _ORG_ID,
    "from": "59176123456",
    "tipo": "image",
    "media": "Zm9v",  # base64 de "foo"
    "mime": "image/jpeg",
    "caption": "pago hecho",
    "message_id": "wamid.IMG1",
    "timestamp": 1718900000,
}


def test_tipo_image_invoca_servicio(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """`tipo:"image"` ⇒ se llama `procesar_comprobante_inbound` con los campos del body."""
    llamadas: list[dict] = []

    def _fake(db, **kwargs):  # type: ignore[no-untyped-def]
        llamadas.append(kwargs)
        return None

    monkeypatch.setattr(inbound_mod.comprobantes_svc, "procesar_comprobante_inbound", _fake)

    resp = client.post(
        "/api/v1/webhooks/whatsapp-inbound",
        json=_IMG_PAYLOAD,
        headers={"X-Gateway-Token": _TOKEN},
    )
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}
    assert len(llamadas) == 1
    kw = llamadas[0]
    assert kw["org_id"] == _ORG_ID
    assert kw["from_telefono"] == "59176123456"
    assert kw["media_b64"] == "Zm9v"
    assert kw["mime"] == "image/jpeg"
    assert kw["caption"] == "pago hecho"
    assert kw["message_id"] == "wamid.IMG1"


def test_tipo_text_no_invoca_servicio(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """Texto (sin `tipo`) ⇒ NO se procesa imagen (solo loguea)."""
    llamado = {"n": 0}

    def _fake(db, **kwargs):  # type: ignore[no-untyped-def]
        llamado["n"] += 1
        return None

    monkeypatch.setattr(inbound_mod.comprobantes_svc, "procesar_comprobante_inbound", _fake)

    resp = client.post(
        "/api/v1/webhooks/whatsapp-inbound",
        json=_PAYLOAD,  # body de texto, sin `tipo`
        headers={"X-Gateway-Token": _TOKEN},
    )
    assert resp.status_code == 200
    assert llamado["n"] == 0


def test_tipo_image_error_interno_igual_ack_200(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Si el procesamiento revienta, el webhook ACK 200 igual (no rompe el sidecar)."""

    def _boom(db, **kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("db down")

    monkeypatch.setattr(inbound_mod.comprobantes_svc, "procesar_comprobante_inbound", _boom)

    resp = client.post(
        "/api/v1/webhooks/whatsapp-inbound",
        json=_IMG_PAYLOAD,
        headers={"X-Gateway-Token": _TOKEN},
    )
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_tipo_image_token_invalido_401(client: TestClient) -> None:
    """Imagen con token inválido ⇒ 401 (no se procesa)."""
    resp = client.post(
        "/api/v1/webhooks/whatsapp-inbound",
        json=_IMG_PAYLOAD,
        headers={"X-Gateway-Token": "otro"},
    )
    assert resp.status_code == 401
