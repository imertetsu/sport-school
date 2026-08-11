"""Crea en Meta la plantilla `contacto_escuela` — la escuela INICIA la conversación.

Por qué hace falta una plantilla para esto: WhatsApp solo deja mandar texto libre dentro
de las 24 h siguientes al último mensaje DEL tutor. Un tutor que nunca escribió (la
mayoría: 62 tutores y 5 hilos en Águilas) está siempre fuera de esa ventana, así que sin
plantilla la escuela no puede contactarlo nunca. Con ella puede, y en cuanto el tutor
responde se abre la ventana y el chat sigue con texto libre normal.

La plantilla es deliberadamente GENÉRICA: `{{3}}` es el mensaje que escribe la secretaria
tal cual. El resto (saludo, escuela, invitación a responder) es texto fijo, porque Meta
rechaza los cuerpos que son casi todo variable y exige que no empiecen ni terminen con
una.

SIN cabecera de imagen, a diferencia de las de cobranza: no hay nada que ilustrar y una
plantilla de solo texto se aprueba antes.

Uso (la WABA y el token salen de la config del entorno):
    docker compose -f infra/docker-compose.yml run --rm --no-deps \
        -v /opt/latinosport/infra:/app/infra -w /app api \
        python infra/crear-plantilla-contacto.py
"""

from __future__ import annotations

import httpx

from app.core.config import settings
from app.services.chat_whatsapp import TEMPLATE_CONTACTO, TEMPLATE_CONTACTO_LANG

V = settings.whatsapp_graph_version
WABA = settings.whatsapp_waba_id
H = {"Authorization": f"Bearer {settings.whatsapp_access_token}"}

# {{1}} tutor · {{2}} escuela · {{3}} el mensaje que escribe la secretaria.
CUERPO = (
    "Hola {{1}}, te escribimos de {{2}}.\n"
    "\n"
    "{{3}}\n"
    "\n"
    "Podés responder a este mensaje."
)

EJEMPLOS = [
    "Roxana Villca",
    "Escuela Deportiva Águilas del Sur",
    "Te avisamos que mañana la clase del grupo A empieza 30 minutos más tarde.",
]


def main() -> int:
    if not WABA:
        print("falta WHATSAPP_WABA_ID")
        return 1

    payload = {
        "name": TEMPLATE_CONTACTO,
        "language": TEMPLATE_CONTACTO_LANG,
        # UTILITY: es comunicación operativa dentro de una relación existente
        # (la familia está inscrita). Meta puede recategorizarla a MARKETING por su
        # cuenta; si lo hace, el envío sigue funcionando pero cuesta más por mensaje.
        "category": "UTILITY",
        "components": [{"type": "BODY", "text": CUERPO, "example": {"body_text": [EJEMPLOS]}}],
    }
    r = httpx.post(
        f"https://graph.facebook.com/{V}/{WABA}/message_templates",
        headers={**H, "Content-Type": "application/json"},
        json=payload,
        timeout=30,
    )
    if r.status_code == 200:
        d = r.json()
        print(f"OK  {TEMPLATE_CONTACTO}: id={d.get('id')} estado={d.get('status')}")
        return 0
    e = r.json().get("error", {})
    print("ERROR:", e.get("error_user_msg") or e.get("message"))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
