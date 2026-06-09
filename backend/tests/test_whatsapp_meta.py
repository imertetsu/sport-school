"""Tests del adaptador WhatsApp Meta Cloud (`MetaCloudWhatsAppAdapter`).

Sin BD ni red real: se mockea `httpx.post`. Foco de este track (whatsapp-go-live):
el adaptador normaliza el destinatario a E.164-sin-`+` antes de pegar a la Graph
API, y con un `to` inválido reporta `ok=False` SIN llamar a la red.
"""

from __future__ import annotations

from typing import Any

import pytest
from app.adapters.whatsapp import meta as meta_mod
from app.adapters.whatsapp.meta import MetaCloudWhatsAppAdapter
from app.domain.ports.whatsapp import WhatsAppTemplateMessage, WhatsAppTextMessage


class _FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:  # pragma: no cover - no error path aquí
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


def test_to_invalido_no_pega_a_la_red(monkeypatch: pytest.MonkeyPatch) -> None:
    """Un `to` no plausible => ok=False y `httpx.post` NUNCA se invoca."""
    called = {"n": 0}

    def _boom(*args: Any, **kwargs: Any) -> Any:
        called["n"] += 1
        raise AssertionError("no debe llamarse a la red con un teléfono inválido")

    monkeypatch.setattr(meta_mod.httpx, "post", _boom)

    adapter = MetaCloudWhatsAppAdapter()
    result = adapter.send_text(WhatsAppTextMessage(to="abc", body="hola"))

    assert result.ok is False
    assert result.provider_message_id is None
    assert result.error is not None
    assert "abc" in result.error
    assert called["n"] == 0


def test_template_to_invalido_no_pega_a_la_red(monkeypatch: pytest.MonkeyPatch) -> None:
    def _boom(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("no debe llamarse a la red con un teléfono inválido")

    monkeypatch.setattr(meta_mod.httpx, "post", _boom)

    adapter = MetaCloudWhatsAppAdapter()
    result = adapter.send_template(
        WhatsAppTemplateMessage(
            to="",
            template_name="recordatorio_cuota",
            lang_code="es",
            body_params=["Ana", "100 Bs"],
        )
    )

    assert result.ok is False
    assert result.error is not None


def test_to_se_normaliza_antes_del_post(monkeypatch: pytest.MonkeyPatch) -> None:
    """El cuerpo enviado a Meta lleva el `to` en E.164-sin-`+` (`591…`)."""
    captured: dict[str, Any] = {}

    def _fake_post(
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, Any],
        timeout: float,
    ) -> Any:
        captured["json"] = json
        return _FakeResponse({"messages": [{"id": "wamid.TEST"}]})

    monkeypatch.setattr(meta_mod.httpx, "post", _fake_post)

    adapter = MetaCloudWhatsAppAdapter()
    result = adapter.send_text(WhatsAppTextMessage(to="+591 76123456", body="hola"))

    assert result.ok is True
    assert result.provider_message_id == "wamid.TEST"
    assert captured["json"]["to"] == "59176123456"
