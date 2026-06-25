"""Tests del adaptador WhatsApp Gateway no-oficial (`GatewayWhatsAppAdapter`) + fábrica.

Sin BD ni red real: se mockea `httpx.post`. Cubre los criterios de aceptación de la
Fase 1 del epic whatsapp-gateway:
- C1: la fábrica `get_whatsapp_port()` con `provider=gateway` + url/token ⇒
  `GatewayWhatsAppAdapter`; sin/incompletas ⇒ degrada a mock.
- C2: `send_text` con número NO normalizable ⇒ `ok=False` SIN llamar al sidecar.
- C3: cada una de las 5 plantillas renderiza el texto esperado con sus params en orden.
- C4: el sidecar reporta `ok:false` (200) ⇒ se mapea a `WhatsAppSendResult(ok=False)`.
"""

from __future__ import annotations

from typing import Any

import pytest
from app.adapters.whatsapp import gateway as gateway_mod
from app.adapters.whatsapp.gateway import GatewayWhatsAppAdapter
from app.adapters.whatsapp.mock import MockWhatsAppAdapter
from app.domain.ports.whatsapp import WhatsAppTemplateMessage, WhatsAppTextMessage


class _FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:  # pragma: no cover - sin error path en estos tests
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


# --------------------------------------------------------------------------- #
# C1 — fábrica `get_whatsapp_port()`
# --------------------------------------------------------------------------- #
def test_factory_gateway_con_credenciales(monkeypatch: pytest.MonkeyPatch) -> None:
    """provider=gateway + url/token ⇒ GatewayWhatsAppAdapter."""
    from app.services import deps as deps_mod

    monkeypatch.setattr(deps_mod.settings, "whatsapp_provider", "gateway", raising=False)
    monkeypatch.setattr(deps_mod.settings, "whatsapp_gateway_url", "http://gw:3000", raising=False)
    monkeypatch.setattr(deps_mod.settings, "whatsapp_gateway_token", "secreto", raising=False)

    port = deps_mod.get_whatsapp_port()
    assert isinstance(port, GatewayWhatsAppAdapter)


def test_factory_gateway_sin_url_degrada_a_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    """provider=gateway pero sin url ⇒ mock (fail-safe), no rompe el arranque."""
    from app.services import deps as deps_mod

    monkeypatch.setattr(deps_mod.settings, "whatsapp_provider", "gateway", raising=False)
    monkeypatch.setattr(deps_mod.settings, "whatsapp_gateway_url", None, raising=False)
    monkeypatch.setattr(deps_mod.settings, "whatsapp_gateway_token", "secreto", raising=False)

    port = deps_mod.get_whatsapp_port()
    assert isinstance(port, MockWhatsAppAdapter)


def test_factory_gateway_sin_token_degrada_a_mock(monkeypatch: pytest.MonkeyPatch) -> None:
    """provider=gateway pero sin token ⇒ mock (fail-safe)."""
    from app.services import deps as deps_mod

    monkeypatch.setattr(deps_mod.settings, "whatsapp_provider", "gateway", raising=False)
    monkeypatch.setattr(deps_mod.settings, "whatsapp_gateway_url", "http://gw:3000", raising=False)
    monkeypatch.setattr(deps_mod.settings, "whatsapp_gateway_token", "", raising=False)

    port = deps_mod.get_whatsapp_port()
    assert isinstance(port, MockWhatsAppAdapter)


# --------------------------------------------------------------------------- #
# C2 — número no normalizable ⇒ ok=False SIN pegar al sidecar
# --------------------------------------------------------------------------- #
def test_send_text_to_invalido_no_pega_al_sidecar(monkeypatch: pytest.MonkeyPatch) -> None:
    called = {"n": 0}

    def _boom(*args: Any, **kwargs: Any) -> Any:
        called["n"] += 1
        raise AssertionError("no debe llamarse al sidecar con un teléfono inválido")

    monkeypatch.setattr(gateway_mod.httpx, "post", _boom)

    adapter = GatewayWhatsAppAdapter()
    result = adapter.send_text(WhatsAppTextMessage(to="abc", body="hola"))

    assert result.ok is False
    assert result.provider_message_id is None
    assert result.error is not None
    assert "abc" in result.error
    assert called["n"] == 0


def test_send_template_to_invalido_no_pega_al_sidecar(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("no debe llamarse al sidecar con un teléfono inválido")

    monkeypatch.setattr(gateway_mod.httpx, "post", _boom)

    adapter = GatewayWhatsAppAdapter()
    result = adapter.send_template(
        WhatsAppTemplateMessage(
            to="",
            template_name="recordatorio_cuota_qr",
            lang_code="es",
            body_params=["Ana", "Bs 100.00", "Academia", "01/07/2026", "http://x"],
        )
    )

    assert result.ok is False
    assert result.error is not None


# --------------------------------------------------------------------------- #
# Envío OK: normaliza el `to`, header de token, mapea message_id
# --------------------------------------------------------------------------- #
def test_send_text_ok_normaliza_y_envia(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, Any] = {}

    def _fake_post(
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, Any],
        timeout: float,
    ) -> Any:
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        return _FakeResponse({"ok": True, "message_id": "gw.ABC"})

    monkeypatch.setattr(gateway_mod.httpx, "post", _fake_post)
    monkeypatch.setattr(
        gateway_mod.settings, "whatsapp_gateway_url", "http://gw:3000/", raising=False
    )
    monkeypatch.setattr(gateway_mod.settings, "whatsapp_gateway_token", "tok123", raising=False)

    adapter = GatewayWhatsAppAdapter()
    result = adapter.send_text(WhatsAppTextMessage(to="+591 76123456", body="hola\nmundo"))

    assert result.ok is True
    assert result.provider_message_id == "gw.ABC"
    assert captured["url"] == "http://gw:3000/send"
    assert captured["headers"]["X-Gateway-Token"] == "tok123"
    assert captured["json"] == {"to": "59176123456", "text": "hola\nmundo"}


# --------------------------------------------------------------------------- #
# C4 — el sidecar reporta ok:false (200) ⇒ WhatsAppSendResult(ok=False)
# --------------------------------------------------------------------------- #
def test_send_text_mapea_ok_false_del_sidecar(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_post(*args: Any, **kwargs: Any) -> Any:
        return _FakeResponse({"ok": False, "error": "no conectado"})

    monkeypatch.setattr(gateway_mod.httpx, "post", _fake_post)

    adapter = GatewayWhatsAppAdapter()
    result = adapter.send_text(WhatsAppTextMessage(to="76123456", body="hola"))

    assert result.ok is False
    assert result.provider_message_id is None
    assert result.error == "no conectado"


def test_send_template_mapea_ok_false_del_sidecar(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake_post(*args: Any, **kwargs: Any) -> Any:
        return _FakeResponse({"ok": False, "error": "número inválido"})

    monkeypatch.setattr(gateway_mod.httpx, "post", _fake_post)

    adapter = GatewayWhatsAppAdapter()
    result = adapter.send_template(
        WhatsAppTemplateMessage(
            to="76123456",
            template_name="nuevo_aviso",
            lang_code="es",
            body_params=["Academia", "Aviso", "Cuerpo"],
        )
    )

    assert result.ok is False
    assert result.error == "número inválido"


def test_send_template_excepcion_de_red_es_ok_false(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sidecar caído / error de red ⇒ ok=False, no lanza (gateway tolerado caído)."""

    def _raise(*args: Any, **kwargs: Any) -> Any:
        raise gateway_mod.httpx.ConnectError("connection refused")

    monkeypatch.setattr(gateway_mod.httpx, "post", _raise)

    adapter = GatewayWhatsAppAdapter()
    result = adapter.send_text(WhatsAppTextMessage(to="76123456", body="hola"))

    assert result.ok is False
    assert result.error is not None


def test_send_template_plantilla_desconocida_es_ok_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Defensivo: template_name fuera del dict ⇒ ok=False sin pegar al sidecar."""

    def _boom(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("no debe llamarse al sidecar con plantilla desconocida")

    monkeypatch.setattr(gateway_mod.httpx, "post", _boom)

    adapter = GatewayWhatsAppAdapter()
    result = adapter.send_template(
        WhatsAppTemplateMessage(
            to="76123456",
            template_name="no_existe",
            lang_code="es",
            body_params=["x"],
        )
    )

    assert result.ok is False
    assert result.error is not None
    assert "no_existe" in result.error


# --------------------------------------------------------------------------- #
# C3 — cada una de las 5 plantillas renderiza el texto esperado (orden de params)
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    ("template_name", "body_params", "esperado"),
    [
        (
            "recordatorio_cuota_qr",
            ["Ana Pérez", "Bs 150.00", "Academia Andina", "05/07/2026", "https://x/r/1"],
            "Hola, recordatorio de cuota de Ana Pérez en Academia Andina: Bs 150.00, "
            "vence el 05/07/2026. Pague aquí: https://x/r/1",
        ),
        (
            "morosidad_cuota_qr",
            ["Ana Pérez", "Bs 150.00", "Academia Andina", "01/06/2026", "https://x/r/1"],
            "La cuota de Ana Pérez en Academia Andina está vencida: Bs 150.00 "
            "(venció el 01/06/2026). Regularice aquí: https://x/r/1",
        ),
        (
            "recibo_pago",
            ["Ana Pérez", "Bs 150.00", "Academia Andina", "REC-000123", "https://x/pdf/1"],
            "Pago recibido de Ana Pérez en Academia Andina: Bs 150.00. "
            "Recibo REC-000123. Descárguelo aquí: https://x/pdf/1",
        ),
        (
            "resumen_deudores",
            ["Carlos Coach", "Sucursal Centro", "4", "600.00"],
            "Hola Carlos Coach, resumen de deudores en Sucursal Centro: 4 deportistas, "
            "total Bs 600.00. Detalle a continuación.",
        ),
        (
            "nuevo_aviso",
            ["Academia Andina", "Suspensión de clases", "No habrá clases el lunes."],
            "Academia Andina informa: Suspensión de clases. No habrá clases el lunes.",
        ),
    ],
)
def test_cada_plantilla_renderiza_texto_esperado(
    monkeypatch: pytest.MonkeyPatch,
    template_name: str,
    body_params: list[str],
    esperado: str,
) -> None:
    captured: dict[str, Any] = {}

    def _fake_post(
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, Any],
        timeout: float,
    ) -> Any:
        captured["json"] = json
        return _FakeResponse({"ok": True, "message_id": "gw.X"})

    monkeypatch.setattr(gateway_mod.httpx, "post", _fake_post)

    adapter = GatewayWhatsAppAdapter()
    result = adapter.send_template(
        WhatsAppTemplateMessage(
            to="76123456",
            template_name=template_name,
            lang_code="es",
            body_params=body_params,
        )
    )

    assert result.ok is True
    assert captured["json"]["text"] == esperado
    assert captured["json"]["to"] == "59176123456"
