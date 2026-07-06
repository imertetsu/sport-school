"""Envío del comprobante de pago por WhatsApp (imagen del recibo + caption).

Rasteriza la 1ª página del PDF del comprobante a JPG (pypdfium2 + Pillow) y la manda por
el gateway de WhatsApp de la escuela (`send_image`) al **tutor responsable de pago** del
deportista. El frontend gatea por el estado de la sesión (CONECTADA) antes de llamar; aquí
solo se resuelve el destinatario, se renderiza y se envía. No lanza: reporta vía `motivo`.
"""

from __future__ import annotations

import base64
import io
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.ports.invoice import ComprobanteService
from app.domain.ports.whatsapp import WhatsAppImageMessage, WhatsAppPort
from app.models.deportista import Deportista
from app.models.deportista_tutor import DeportistaTutor
from app.models.organizacion import Organizacion
from app.models.pago import Pago
from app.models.tutor import Tutor
from app.services import pagos as pagos_svc


@dataclass(frozen=True)
class EnvioComprobanteResult:
    """Resultado del envío. `motivo` ∈ {ok, sin_deportista, sin_telefono, error_envio}."""

    enviado: bool
    motivo: str
    provider_message_id: str | None = None


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

    result = port.send_image(
        WhatsAppImageMessage(
            to=telefono,
            image_b64=base64.b64encode(jpg_bytes).decode("ascii"),
            mime="image/jpeg",
            caption=_caption(org, pago, deportista, cuotas),
        )
    )
    if result.ok:
        return EnvioComprobanteResult(
            enviado=True, motivo="ok", provider_message_id=result.provider_message_id
        )
    return EnvioComprobanteResult(enviado=False, motivo="error_envio")
