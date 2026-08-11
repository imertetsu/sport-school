"""Envío del comprobante de pago por WhatsApp (imagen del recibo + caption).

Rasteriza la 1ª página del PDF del comprobante a JPG (pypdfium2 + Pillow) y la manda por
WhatsApp al **tutor responsable de pago** del deportista. El frontend gatea por el estado
del canal antes de llamar; aquí solo se resuelve el destinatario, se renderiza y se envía.
No lanza: reporta vía `motivo`.

**Canal libre** (sidecar): imagen + caption (`send_image`).
**Canal oficial** (Meta, `port.requiere_plantilla()`): plantilla aprobada con el recibo en
la CABECERA. El comprobante lo inicia la escuela, y Meta solo acepta imagen libre dentro
de la ventana de 24 h desde el último mensaje del tutor; fuera de ella responde 131047
("Re-engagement") y el recibo no llega, aunque la API haya aceptado el envío.
"""

from __future__ import annotations

import base64
import io
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.org_context import set_current_org_id
from app.domain.ports.invoice import ComprobanteService
from app.domain.ports.whatsapp import (
    WhatsAppImage,
    WhatsAppImageMessage,
    WhatsAppPort,
    WhatsAppTemplateMessage,
)
from app.models.deportista import Deportista
from app.models.deportista_tutor import DeportistaTutor
from app.models.organizacion import Organizacion
from app.models.pago import Pago
from app.models.tutor import Tutor
from app.services import pagos as pagos_svc


@dataclass(frozen=True)
class EnvioComprobanteResult:
    """Resultado del envío.

    `motivo` ∈ {ok, sin_deportista, sin_telefono, sin_whatsapp, error_envio}.
    - `sin_whatsapp`: el número del tutor NO está registrado en WhatsApp (o mal cargado).
    - `error_envio`: otro fallo del gateway (sesión caída, timeout, etc.); ver `detalle`.
    """

    enviado: bool
    motivo: str
    provider_message_id: str | None = None
    detalle: str | None = None


def rasterizar_pdf_a_jpg(pdf_bytes: bytes, *, scale: float = 2.0) -> bytes:
    """Renderiza la 1ª página del PDF a JPG para adjuntarla como imagen en WhatsApp."""
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(pdf_bytes)
    try:
        pil = doc[0].render(scale=scale).to_pil()
        if pil.mode != "RGB":
            pil = pil.convert("RGB")
        buf = io.BytesIO()
        pil.save(buf, format="JPEG", quality=85)
        return buf.getvalue()
    finally:
        doc.close()


def _tutor_responsable(db: Session, deportista_id: uuid.UUID) -> tuple[str, str] | None:
    """`(telefono, nombres)` del tutor responsable de pago CON teléfono; si el responsable
    no tiene, el primer tutor con teléfono. `None` si ninguno tiene teléfono cargado."""
    rows = db.execute(
        select(Tutor.telefono, Tutor.nombres, DeportistaTutor.responsable_pago)
        .join(DeportistaTutor, DeportistaTutor.tutor_id == Tutor.id)
        .where(DeportistaTutor.deportista_id == deportista_id)
        .order_by(DeportistaTutor.responsable_pago.desc())
    ).all()
    for telefono, nombres, _resp in rows:
        if telefono and telefono.strip():
            return telefono.strip(), nombres
    return None


# Plantilla aprobada del comprobante (canal oficial). El recibo va en la CABECERA
# como imagen; los 6 parámetros, en este orden EXACTO:
#   {{1}} escuela · {{2}} recibo · {{3}} deportista · {{4}} cuotas · {{5}} monto · {{6}} método
TEMPLATE_COMPROBANTE = "comprobante_pago"
TEMPLATE_LANG = "es"


def _cuotas_texto(cuotas) -> str:
    """Las cuotas cubiertas en una línea ("MARZO 2026, ABRIL 2026").

    La plantilla tiene un nº FIJO de variables, así que el detalle multilínea del
    caption libre se colapsa a un solo parámetro.
    """
    partes = [
        f"{pagos_svc._MESES_LARGO[c.vence_el.month].upper()} {c.vence_el.year}" for c in cuotas
    ]
    return ", ".join(partes) if partes else "—"


def _template_params(
    org: Organizacion, pago: Pago, deportista: Deportista | None, cuotas
) -> list[str]:
    """Los 6 parámetros de la plantilla, en el orden aprobado."""
    return [
        org.nombre,
        pago.numero_recibo or "—",
        pagos_svc._nombre_completo(deportista) if deportista else "—",
        _cuotas_texto(cuotas),
        f"{pago.monto}",
        "Efectivo" if pago.metodo == "EFECTIVO" else "QR",
    ]


def _caption(org: Organizacion, pago: Pago, deportista: Deportista | None, cuotas) -> str:
    """Texto que acompaña la imagen del recibo (mismo formato que el 'copiar mensaje')."""
    lineas: list[str | None] = [
        f"🧾 *{org.nombre}* — Comprobante de pago",
        f"Recibo: {pago.numero_recibo}" if pago.numero_recibo else None,
        f"Deportista: {pagos_svc._nombre_completo(deportista)}" if deportista else None,
    ]
    for c in cuotas:
        mes = pagos_svc._MESES_LARGO[c.vence_el.month].upper()
        lineas.append(f"• Cuota {mes} {c.vence_el.year} (vence {pagos_svc._fecha_dma(c.vence_el)})")
    lineas.append(f"Monto: BOB {pago.monto}")
    lineas.append(f"Método: {'Efectivo' if pago.metodo == 'EFECTIVO' else 'QR'}")
    lineas.append("¡Gracias por tu pago! 🙌")
    return "\n".join(line for line in lineas if line)


def enviar_comprobante_whatsapp(
    db: Session,
    *,
    pago: Pago,
    org: Organizacion,
    port: WhatsAppPort,
    comprobante_svc: ComprobanteService,
) -> EnvioComprobanteResult:
    """Envía el comprobante (imagen del recibo + caption) al tutor responsable de pago."""
    # El adaptador del gateway resuelve la org por ContextVar (`app.core.org_context`).
    # En un request sync, el ContextVar que fija `set_tenant_context` (dependencia) NO
    # llega al cuerpo del endpoint: FastAPI corre las dependencias y el endpoint sync en
    # hilos distintos del threadpool y los ContextVars no se propagan de vuelta. Lo fijamos
    # aquí — mismo contexto que llama al puerto — o el envío falla con
    # "sin contexto de organización" (el GUC de RLS sí funciona porque va en la sesión de BD).
    set_current_org_id(str(org.id))
    cuotas = pagos_svc._cuotas_de_pago(db, pago.id)
    deportista = pagos_svc._deportista_de_cuotas(db, cuotas)
    if deportista is None:
        return EnvioComprobanteResult(enviado=False, motivo="sin_deportista")

    dest = _tutor_responsable(db, deportista.id)
    if dest is None:
        return EnvioComprobanteResult(enviado=False, motivo="sin_telefono")
    telefono, _tutor_nombre = dest

    data = pagos_svc.construir_comprobante_data(db, pago=pago, org=org)
    pdf_bytes = comprobante_svc.render_pdf(data)
    jpg_bytes = rasterizar_pdf_a_jpg(pdf_bytes)

    imagen_b64 = base64.b64encode(jpg_bytes).decode("ascii")

    if port.requiere_plantilla():
        # Canal OFICIAL: el comprobante lo INICIA la escuela, así que la imagen
        # libre no llega salvo que el tutor haya escrito en las últimas 24 h (Meta
        # responde 131047 "Re-engagement"). Sale como plantilla aprobada con el
        # recibo en la cabecera.
        result = port.send_template(
            WhatsAppTemplateMessage(
                to=telefono,
                template_name=TEMPLATE_COMPROBANTE,
                lang_code=TEMPLATE_LANG,
                body_params=_template_params(org, pago, deportista, cuotas),
                header_image=WhatsAppImage(data_url=f"data:image/jpeg;base64,{imagen_b64}"),
            )
        )
    else:
        result = port.send_image(
            WhatsAppImageMessage(
                to=telefono,
                image_b64=imagen_b64,
                mime="image/jpeg",
                caption=_caption(org, pago, deportista, cuotas),
            )
        )
    # El comprobante también es una burbuja del chat: el tutor suele responder al recibo
    # ("no me llegó", "está mal el monto") y sin él la conversación arranca sin contexto.
    # Import local: `chat_whatsapp` importa servicios que vuelven aquí (ciclo).
    from app.services import chat_whatsapp as chat_svc

    chat_svc.registrar_automatico(
        db,
        org_id=org.id,
        telefono=telefono,
        tipo="PLANTILLA" if port.requiere_plantilla() else "IMAGEN",
        texto=_caption(org, pago, deportista, cuotas),
        estado="ENVIADO" if result.ok else "FALLIDO",
        provider_message_id=result.provider_message_id,
        error_detalle=None if result.ok else result.error,
        autor=chat_svc.AUTOR_COMPROBANTE,
        # El recibo SÍ se guarda (a diferencia del QR, que se referencia): es único por
        # pago y es un documento de dinero. Regenerarlo mostraría el estado ACTUAL —si
        # el pago se anula después, la burbuja dejaría de reflejar lo que recibió el
        # tutor ese día—, y eso en un comprobante importa más que los 100 kB.
        media=jpg_bytes,
        media_mime="image/jpeg",
    )

    if result.ok:
        return EnvioComprobanteResult(
            enviado=True, motivo="ok", provider_message_id=result.provider_message_id
        )
    # El gateway responde `ok:false` con un `error`. Distinguimos el caso más común
    # (destinatario sin WhatsApp) del resto para dar un mensaje útil en la UI.
    err = (result.error or "").lower()
    sin_whatsapp = "registrado" in err or "no esta en whatsapp" in err
    motivo = "sin_whatsapp" if sin_whatsapp else "error_envio"
    return EnvioComprobanteResult(enviado=False, motivo=motivo, detalle=result.error)
