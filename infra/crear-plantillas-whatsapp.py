"""Crea en Meta las 2 plantillas del recordatorio de cobranza.

El texto sale del MISMO código que arma el mensaje (`_texto_recordatorio`), con
cada dato sustituido por su marcador `{{n}}`: así la plantilla aprobada y el texto
libre no pueden divergir por una copia a mano.

La cabecera es una IMAGEN (el QR de cobro). Meta exige un EJEMPLO de esa imagen
al crear la plantilla, y no acepta base64: hay que subirla por la Resumable Upload
API (`/{app_id}/uploads`) y pasar el handle resultante.
"""

from __future__ import annotations

import sys
from decimal import Decimal

import httpx
from sqlalchemy import text

from app.core.config import settings
from app.core.db import SessionLocal
from app.services.recordatorios import (
    TEMPLATE_LANG,
    TEMPLATE_MORA,
    TEMPLATE_PROXIMO,
    _texto_recordatorio,
)

APP_ID = "1511283866884386"
V = settings.whatsapp_graph_version
TOK = settings.whatsapp_access_token
WABA = settings.whatsapp_waba_id
H = {"Authorization": f"Bearer {TOK}"}

# Ejemplos que ve el revisor de Meta (deben ser realistas o rechazan la plantilla).
EJEMPLOS = [
    "ANTEZANA RODRÍGUEZ LUIS MATÍAS",
    "Escuela Deportiva Águilas del Sur",
    "AGOSTO, SEPTIEMBRE, OCTUBRE",
    "11/08/2025",
    "610.00",
]


def texto_con_marcadores(tipo: str) -> str:
    """El cuerpo real, con cada dato reemplazado por `{{1}}..{{5}}` (orden aprobado)."""
    t = _texto_recordatorio(
        tipo,
        deportista="{{1}}",
        escuela="{{2}}",
        meses=["@@3@@"],
        vence="{{4}}",
        monto=Decimal("0"),
    )
    return t.replace("@@3@@", "{{3}}").replace("Bs 0.00", "Bs {{5}}")


def qr_de_ejemplo() -> tuple[bytes, str]:
    """Un QR de cobro real de la BD: es la imagen que de verdad va en la cabecera."""
    db = SessionLocal()
    try:
        org = db.execute(
            text("select id from organizacion where nombre like '%guilas%'")
        ).scalar_one()
        db.execute(
            text("select set_config('app.current_org', :o, true)"), {"o": str(org)}
        )
        fila = db.execute(text("select imagen, mime from qr_cobro limit 1")).one()
        return bytes(fila.imagen), fila.mime
    finally:
        db.rollback()
        db.close()


def subir_ejemplo(binario: bytes, mime: str) -> str:
    """Resumable Upload API -> handle para `example.header_handle`. Devuelve el handle."""
    r = httpx.post(
        f"https://graph.facebook.com/{V}/{APP_ID}/uploads",
        params={"file_name": "qr.png", "file_length": len(binario), "file_type": mime},
        headers=H,
        timeout=30,
    )
    r.raise_for_status()
    sesion = r.json()["id"]
    r2 = httpx.post(
        f"https://graph.facebook.com/{V}/{sesion}",
        headers={**H, "file_offset": "0"},
        content=binario,
        timeout=60,
    )
    r2.raise_for_status()
    return r2.json()["h"]


def crear(nombre: str, tipo: str, handle: str) -> None:
    cuerpo = texto_con_marcadores(tipo)
    payload = {
        "name": nombre,
        "language": TEMPLATE_LANG,
        "category": "UTILITY",
        "components": [
            {
                "type": "HEADER",
                "format": "IMAGE",
                "example": {"header_handle": [handle]},
            },
            {
                "type": "BODY",
                "text": cuerpo,
                "example": {"body_text": [EJEMPLOS]},
            },
        ],
    }
    r = httpx.post(
        f"https://graph.facebook.com/{V}/{WABA}/message_templates",
        headers={**H, "Content-Type": "application/json"},
        json=payload,
        timeout=30,
    )
    if r.status_code == 200:
        d = r.json()
        print(f"  OK  {nombre}: id={d.get('id')} estado={d.get('status')}")
    else:
        e = r.json().get("error", {})
        print(f"  ERROR {nombre}: {e.get('error_user_msg') or e.get('message')}")


def main() -> int:
    if not WABA:
        print("falta WHATSAPP_WABA_ID")
        return 1
    binario, mime = qr_de_ejemplo()
    print(f"QR de ejemplo: {len(binario)} bytes ({mime})")
    handle = subir_ejemplo(binario, mime)
    print(f"handle subido: {handle[:40]}…\n")
    print("Creando plantillas:")
    crear(TEMPLATE_MORA, "MOROSIDAD", handle)
    crear(TEMPLATE_PROXIMO, "PROXIMO_VENCIMIENTO", handle)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
