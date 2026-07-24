"""Tests del adaptador WhatsApp Meta Cloud (`MetaCloudWhatsAppAdapter`).

Sin BD ni red real: se mockea `httpx.post`. Foco de este track (whatsapp-go-live):
el adaptador normaliza el destinatario a E.164-sin-`+` antes de pegar a la Graph
API, y con un `to` inválido reporta `ok=False` SIN llamar a la red.
"""

from __future__ import annotations

import base64
from typing import Any

import pytest
from app.adapters.whatsapp import meta as meta_mod
from app.adapters.whatsapp.meta import MetaCloudWhatsAppAdapter
from app.domain.ports.whatsapp import (
    WhatsAppImage,
    WhatsAppImageMessage,
    WhatsAppTemplateMessage,
    WhatsAppTextMessage,
)


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


# --------------------------------------------------------------------------- #
# Subida de media (imágenes): Meta NO acepta base64 inline — hay que subir a
# `/media` y referenciar el `media_id`. Habilita el QR de cobro.
# --------------------------------------------------------------------------- #
_PNG_B64 = base64.b64encode(b"\x89PNG\r\n\x1a\n-fake").decode()
_TELEFONO = "+591 76123456"


def _capturar(monkeypatch: pytest.MonkeyPatch, respuestas: list[Any]) -> list[dict[str, Any]]:
    """Mockea `httpx.post` devolviendo `respuestas` en orden; registra cada llamada."""
    llamadas: list[dict[str, Any]] = []
    pendientes = list(respuestas)

    def _fake_post(url: str, **kwargs: Any) -> Any:
        llamadas.append({"url": url, **kwargs})
        return pendientes.pop(0)

    monkeypatch.setattr(meta_mod.httpx, "post", _fake_post)
    return llamadas


def test_send_image_sube_media_y_referencia_el_id(monkeypatch: pytest.MonkeyPatch) -> None:
    llamadas = _capturar(
        monkeypatch,
        [_FakeResponse({"id": "MEDIA_1"}), _FakeResponse({"messages": [{"id": "wamid.1"}]})],
    )
    res = MetaCloudWhatsAppAdapter().send_image(
        WhatsAppImageMessage(to=_TELEFONO, image_b64=_PNG_B64, mime="image/png", caption="Hola")
    )
    assert res.ok is True
    assert res.provider_message_id == "wamid.1"
    # 1ª llamada: subida multipart a /media.
    assert llamadas[0]["url"].endswith("/media")
    assert llamadas[0]["data"] == {"messaging_product": "whatsapp", "type": "image/png"}
    assert "file" in llamadas[0]["files"]
    # 2ª llamada: el mensaje referencia el media_id (nunca el base64) y normaliza el `to`.
    body = llamadas[1]["json"]
    assert llamadas[1]["url"].endswith("/messages")
    assert body["type"] == "image"
    assert body["image"] == {"id": "MEDIA_1", "caption": "Hola"}
    assert body["to"] == "59176123456"


def test_send_image_sin_caption_omite_la_clave(monkeypatch: pytest.MonkeyPatch) -> None:
    """Meta rechaza `caption: ""` ⇒ no se manda la clave cuando el caption es vacío."""
    llamadas = _capturar(
        monkeypatch,
        [_FakeResponse({"id": "MEDIA_1"}), _FakeResponse({"messages": [{"id": "wamid.2"}]})],
    )
    res = MetaCloudWhatsAppAdapter().send_image(
        WhatsAppImageMessage(to=_TELEFONO, image_b64=_PNG_B64, mime="image/png", caption="")
    )
    assert res.ok is True
    assert llamadas[1]["json"]["image"] == {"id": "MEDIA_1"}


def test_send_image_subida_fallida_no_manda_mensaje(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sin `media_id` ⇒ ok=False y NO se llama a /messages."""
    llamadas = _capturar(monkeypatch, [_FakeResponse({})])
    res = MetaCloudWhatsAppAdapter().send_image(
        WhatsAppImageMessage(to=_TELEFONO, image_b64=_PNG_B64, mime="image/png", caption="x")
    )
    assert res.ok is False
    assert res.error is not None and "media_id" in res.error
    assert len(llamadas) == 1


def test_send_image_base64_invalido_no_pega_a_la_red(monkeypatch: pytest.MonkeyPatch) -> None:
    """Base64 corrupto (padding imposible) ⇒ ok=False SIN subir nada.

    Se decodifica en modo tolerante (`validate=False`), así que un base64 real con
    saltos de línea sigue funcionando; solo falla el que no puede decodificarse.
    """
    llamadas = _capturar(monkeypatch, [])
    res = MetaCloudWhatsAppAdapter().send_image(
        WhatsAppImageMessage(to=_TELEFONO, image_b64="a", mime="image/png", caption="x")
    )
    assert res.ok is False
    assert res.error is not None and "base64" in res.error
    assert llamadas == []


def test_template_cabecera_data_url_sube_y_referencia(monkeypatch: pytest.MonkeyPatch) -> None:
    llamadas = _capturar(
        monkeypatch,
        [_FakeResponse({"id": "MEDIA_QR"}), _FakeResponse({"messages": [{"id": "wamid.3"}]})],
    )
    res = MetaCloudWhatsAppAdapter().send_template(
        WhatsAppTemplateMessage(
            to=_TELEFONO,
            template_name="recordatorio_cuota",
            lang_code="es",
            body_params=["ANA", "Bs 60"],
            header_image=WhatsAppImage(data_url=f"data:image/png;base64,{_PNG_B64}"),
        )
    )
    assert res.ok is True
    componentes = llamadas[1]["json"]["template"]["components"]
    assert componentes[0] == {
        "type": "header",
        "parameters": [{"type": "image", "image": {"id": "MEDIA_QR"}}],
    }
    assert [p["text"] for p in componentes[1]["parameters"]] == ["ANA", "Bs 60"]


def test_template_cabecera_link_no_sube_media(monkeypatch: pytest.MonkeyPatch) -> None:
    """Un `link` público va tal cual: sin subida previa."""
    llamadas = _capturar(monkeypatch, [_FakeResponse({"messages": [{"id": "wamid.4"}]})])
    res = MetaCloudWhatsAppAdapter().send_template(
        WhatsAppTemplateMessage(
            to=_TELEFONO,
            template_name="recordatorio_cuota",
            lang_code="es",
            body_params=[],
            header_image=WhatsAppImage(link="https://ejemplo.test/qr.png"),
        )
    )
    assert res.ok is True
    assert len(llamadas) == 1
    componentes = llamadas[0]["json"]["template"]["components"]
    assert componentes[0]["parameters"][0]["image"] == {"link": "https://ejemplo.test/qr.png"}


def test_template_cabecera_fallida_igual_manda_cuerpo(monkeypatch: pytest.MonkeyPatch) -> None:
    """Si la subida del QR falla, se omite la cabecera pero el cuerpo sale igual."""
    llamadas = _capturar(
        monkeypatch, [_FakeResponse({}), _FakeResponse({"messages": [{"id": "wamid.5"}]})]
    )
    res = MetaCloudWhatsAppAdapter().send_template(
        WhatsAppTemplateMessage(
            to=_TELEFONO,
            template_name="recordatorio_cuota",
            lang_code="es",
            body_params=["ANA"],
            header_image=WhatsAppImage(data_url=f"data:image/png;base64,{_PNG_B64}"),
        )
    )
    assert res.ok is True
    componentes = llamadas[1]["json"]["template"]["components"]
    assert all(c["type"] != "header" for c in componentes)
    assert componentes[0]["type"] == "body"
