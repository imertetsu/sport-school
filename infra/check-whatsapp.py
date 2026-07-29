#!/usr/bin/env python3
"""Estado del canal oficial de WhatsApp (Meta): número, límites y plantillas.

Uso (dentro del contenedor api):

    docker exec latinosport-api-1 python /app/infra/check-whatsapp.py
    docker exec latinosport-api-1 python /app/infra/check-whatsapp.py <WABA_ID>

Sin `WABA_ID` usa `settings.whatsapp_waba_id` (variable `WHATSAPP_WABA_ID` del
`.env`). Sin ninguno de los dos, informa el estado del número pero NO puede
listar plantillas: Meta las cuelga de la cuenta de WhatsApp Business (WABA), y
el id del número no permite llegar a ella.

Solo hace lecturas (GET): no envía mensajes ni modifica nada.
"""

from __future__ import annotations

import sys

import httpx

from app.core.config import settings

# Estados que devuelve Meta para una plantilla, con su lectura en castellano.
_ESTADOS = {
    "APPROVED": "aprobada — ya se puede usar",
    "PENDING": "en revisión — Meta aún no responde",
    "REJECTED": "rechazada — hay que corregirla y reenviarla",
    "PAUSED": "pausada por baja calidad",
    "DISABLED": "deshabilitada",
}

# Las que el código espera encontrar aprobadas para el cron de cobranza.
_ESPERADAS = ("recordatorio_mora", "recordatorio_proximo_vencimiento")


def _get(path: str, params: dict | None = None) -> tuple[int, dict]:
    url = f"https://graph.facebook.com/{settings.whatsapp_graph_version}/{path}"
    headers = {"Authorization": f"Bearer {settings.whatsapp_access_token}"}
    resp = httpx.get(url, params=params or {}, headers=headers, timeout=20)
    return resp.status_code, resp.json()


def main() -> int:
    if not settings.whatsapp_access_token:
        print("ERROR: falta WHATSAPP_ACCESS_TOKEN en el .env")
        return 1

    print("=== NÚMERO ===")
    code, data = _get(
        str(settings.whatsapp_phone_number_id),
        {
            "fields": "display_phone_number,verified_name,quality_rating,"
            "account_mode,messaging_limit_tier"
        },
    )
    if code != 200:
        print("  ERROR:", data.get("error", {}).get("message"))
        return 1
    print(f"  {data.get('display_phone_number')} · {data.get('verified_name')}")
    print(f"  calidad: {data.get('quality_rating')} · modo: {data.get('account_mode')}")
    print(f"  límite: {data.get('messaging_limit_tier')} (destinatarios únicos / 24 h)")

    waba = (sys.argv[1] if len(sys.argv) > 1 else None) or settings.whatsapp_waba_id
    if not waba:
        print("\n=== PLANTILLAS ===")
        print("  No se pueden consultar: falta el WABA_ID.")
        print("  Está en WhatsApp Manager → Configuración de la cuenta, o pasalo como")
        print("  argumento. Para dejarlo fijo: WHATSAPP_WABA_ID=<id> en el .env.")
        return 0

    print(f"\n=== PLANTILLAS (WABA {waba}) ===")
    code, data = _get(f"{waba}/message_templates", {"limit": 100})
    if code != 200:
        err = data.get("error", {})
        print("  ERROR:", err.get("message"))
        if err.get("code") == 200:
            print("  (al token le falta permiso sobre esta WABA)")
        return 1

    plantillas = data.get("data", [])
    if not plantillas:
        print("  No hay ninguna plantilla creada todavía.")
    for t in plantillas:
        estado = t.get("status", "?")
        print(f"  - {t.get('name')} [{t.get('language')}] → {estado}: "
              f"{_ESTADOS.get(estado, 'estado desconocido')}")
        if estado == "REJECTED" and t.get("rejected_reason"):
            print(f"      motivo: {t['rejected_reason']}")

    print("\n=== LISTO PARA EL CRON DE COBRANZA? ===")
    aprobadas = {
        t.get("name") for t in plantillas if t.get("status") == "APPROVED"
    }
    faltan = [n for n in _ESPERADAS if n not in aprobadas]
    if faltan:
        print("  TODAVÍA NO. Faltan aprobadas:", ", ".join(faltan))
    else:
        print("  SÍ: las dos plantillas están aprobadas.")
        print("  Siguiente paso: WHATSAPP_PROVIDER=meta y recrear api/worker/beat.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
