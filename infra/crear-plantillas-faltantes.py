"""Crea en Meta las plantillas que el codigo usa y nunca se dieron de alta.

Contexto: con el canal no-oficial (Baileys) el nombre de la plantilla daba igual — el
sidecar mandaba el texto sin mas. Al pasar al canal oficial, todo `send_template` con un
nombre inexistente empezo a fallar con `132001 Template name does not exist`, y estos dos
flujos quedaron rotos en silencio hasta que el chat empezo a mostrar los fallos.

  - `nuevo_aviso`      -> avisos del muro reenviados por WhatsApp a tutores/entrenadores.
  - `resumen_deudores` -> digest semanal de morosos al entrenador (lunes 07:00).

El numero y ORDEN de las variables sale del codigo que las manda
(`aviso_notificacion.py` y `recordatorio_deudores.py`): si no coinciden, Meta rechaza el
envio. Ninguna lleva cabecera de imagen — son texto puro, que ademas se aprueba antes.

Uso:
    docker compose -f infra/docker-compose.yml run --rm --no-deps \\
        -v /opt/latinosport/infra:/app/infra -w /app api \\
        python infra/crear-plantillas-faltantes.py
"""

from __future__ import annotations

import httpx

from app.core.config import settings
from app.services.aviso_notificacion import _LANG_CODE as LANG_AVISO
from app.services.aviso_notificacion import _TEMPLATE_NUEVO_AVISO
from app.services.recordatorio_deudores import _LANG_CODE as LANG_DEUDORES
from app.services.recordatorio_deudores import _TEMPLATE_RESUMEN

V = settings.whatsapp_graph_version
WABA = settings.whatsapp_waba_id
H = {"Authorization": f"Bearer {settings.whatsapp_access_token}"}

# Meta rechaza los cuerpos que empiezan o terminan con variable, de ahi el texto fijo
# al principio y al final de los dos.
PLANTILLAS = [
    {
        "name": _TEMPLATE_NUEVO_AVISO,
        "language": LANG_AVISO,
        "category": "UTILITY",
        # {{1}} escuela · {{2}} titulo del aviso · {{3}} cuerpo recortado a 200 car.
        "cuerpo": (
            "Nuevo aviso de {{1}}\n"
            "\n"
            "*{{2}}*\n"
            "{{3}}\n"
            "\n"
            "Podés ver el detalle en la app."
        ),
        "ejemplos": [
            "Escuela Deportiva Águilas del Sur",
            "Suspensión del entrenamiento del sábado",
            "Por el mal clima se suspende el entrenamiento del sábado 9. Se recupera el domingo "
            "a la misma hora.",
        ],
    },
    {
        "name": _TEMPLATE_RESUMEN,
        "language": LANG_DEUDORES,
        "category": "UTILITY",
        # {{1}} entrenador · {{2}} sucursal · {{3}} nº de deudores · {{4}} monto YA
        # formateado como "Bs 1234.00" por el servicio (por eso el texto no repite "Bs").
        "cuerpo": (
            "Hola {{1}}, este es el resumen de cuotas pendientes de {{2}}.\n"
            "\n"
            "Deportistas con deuda: {{3}}\n"
            "Total adeudado: {{4}}\n"
            "\n"
            "Te enviamos el detalle a continuación."
        ),
        "ejemplos": [
            "Carlos Mendoza",
            "Sucursal Norte",
            "7",
            "Bs 1260.00",
        ],
    },
]


def crear(plantilla: dict) -> bool:
    payload = {
        "name": plantilla["name"],
        "language": plantilla["language"],
        "category": plantilla["category"],
        "components": [
            {
                "type": "BODY",
                "text": plantilla["cuerpo"],
                "example": {"body_text": [plantilla["ejemplos"]]},
            }
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
        print(f"  OK    {plantilla['name']:22} id={d.get('id')} estado={d.get('status')}")
        return True
    e = r.json().get("error", {})
    print(f"  ERROR {plantilla['name']:22} {e.get('error_user_msg') or e.get('message')}")
    return False


def main() -> int:
    if not WABA:
        print("falta WHATSAPP_WABA_ID")
        return 1
    print(f"WABA {WABA}\n")
    ok = all([crear(p) for p in PLANTILLAS])
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
