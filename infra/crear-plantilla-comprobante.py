"""Crea en Meta la plantilla del COMPROBANTE de pago (cabecera = imagen del recibo)."""
import httpx
from app.core.config import settings
from app.services.comprobante_whatsapp import TEMPLATE_COMPROBANTE, TEMPLATE_LANG

APP_ID = "1511283866884386"
V, WABA, TOK = settings.whatsapp_graph_version, settings.whatsapp_waba_id, settings.whatsapp_access_token
H = {"Authorization": f"Bearer {TOK}"}

# El cuerpo NO puede empezar ni terminar con variable (Meta lo rechaza).
CUERPO = (
    "Comprobante de pago de {{1}}.\n"
    "\n"
    "Recibo: {{2}}\n"
    "Deportista: {{3}}\n"
    "Cuota(s): {{4}}\n"
    "Monto: Bs {{5}}\n"
    "Método: {{6}}\n"
    "\n"
    "¡Gracias por tu pago!"
)
EJEMPLOS = [
    "Escuela Deportiva Águilas del Sur",
    "REC-000177",
    "COAGUILA VILLCA ALEXIA KEYRA",
    "MARZO 2026",
    "60.00",
    "Efectivo",
]


def imagen_ejemplo() -> bytes:
    """Un recibo real rasterizado: es la imagen que de verdad va en la cabecera."""
    from sqlalchemy import select
    from app.core.db import SessionLocal
    from sqlalchemy import text
    from app.models.pago import Pago
    from app.models.organizacion import Organizacion
    from app.services import pagos as pagos_svc
    from app.services.comprobante_whatsapp import rasterizar_pdf_a_jpg
    from app.adapters.comprobante.pdf import PdfComprobanteService

    db = SessionLocal()
    try:
        org_id = db.execute(text("select id from organizacion where nombre like '%guilas%'")).scalar_one()
        db.execute(text("select set_config('app.current_org', :o, true)"), {"o": str(org_id)})
        org = db.execute(select(Organizacion).where(Organizacion.id == org_id)).scalar_one()
        pago = db.execute(
            select(Pago).where(Pago.estado == "CONFIRMADO", Pago.numero_recibo.is_not(None)).limit(1)
        ).scalar_one()
        data = pagos_svc.construir_comprobante_data(db, pago=pago, org=org)
        return rasterizar_pdf_a_jpg(PdfComprobanteService().render_pdf(data))
    finally:
        db.rollback()
        db.close()


def subir(binario: bytes) -> str:
    r = httpx.post(
        f"https://graph.facebook.com/{V}/{APP_ID}/uploads",
        params={"file_name": "recibo.jpg", "file_length": len(binario), "file_type": "image/jpeg"},
        headers=H, timeout=30)
    r.raise_for_status()
    r2 = httpx.post(f"https://graph.facebook.com/{V}/{r.json()['id']}",
                    headers={**H, "file_offset": "0"}, content=binario, timeout=60)
    r2.raise_for_status()
    return r2.json()["h"]


binario = imagen_ejemplo()
print(f"recibo de ejemplo: {len(binario)} bytes")
handle = subir(binario)
payload = {
    "name": TEMPLATE_COMPROBANTE,
    "language": TEMPLATE_LANG,
    "category": "UTILITY",
    "components": [
        {"type": "HEADER", "format": "IMAGE", "example": {"header_handle": [handle]}},
        {"type": "BODY", "text": CUERPO, "example": {"body_text": [EJEMPLOS]}},
    ],
}
r = httpx.post(f"https://graph.facebook.com/{V}/{WABA}/message_templates",
               headers={**H, "Content-Type": "application/json"}, json=payload, timeout=30)
if r.status_code == 200:
    d = r.json()
    print(f"OK  {TEMPLATE_COMPROBANTE}: id={d.get('id')} estado={d.get('status')}")
else:
    e = r.json().get("error", {})
    print("ERROR:", e.get("error_user_msg") or e.get("message"))
