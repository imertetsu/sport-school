"""Envío del recibo PDF por WhatsApp al confirmar un pago (epic Sucursales/Recibo).

Al confirmar un pago (EFECTIVO inmediato o QR vía webhook), se notifica al **tutor
responsable de pago** con un enlace al recibo PDF, reusando el `WhatsAppPort`
existente (mock-first) — NO se abre un segundo canal ni se modifica el puerto.

Resolución del destinatario (mismo patrón que `recordatorios.py`): pago → cuota
(vía `pago_cuota`) → inscripción → deportista → `deportista_tutor.responsable_pago=True` →
`tutor.telefono`. Sin teléfono ⇒ no llama al puerto (`motivo="sin_telefono"`),
nunca lanza: el recibo no es crítico para confirmar el pago.

Idempotencia: este servicio NO dedup por sí mismo; el llamador (`pagos.py`) lo
engancha exactamente una vez por confirmación (la guarda `pago.estado ==
"CONFIRMADO"` de `_confirmar_y_aplicar` y el flujo único de efectivo lo garantizan).
Corre bajo el `app.current_org` ya fijado por el caller (RLS); no commitea.
"""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal
from typing import NamedTuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.ports.whatsapp import WhatsAppPort, WhatsAppTemplateMessage
from app.models.cuota import Cuota
from app.models.deportista import Deportista
from app.models.deportista_tutor import DeportistaTutor
from app.models.inscripcion import Inscripcion
from app.models.organizacion import Organizacion
from app.models.pago import Pago
from app.models.pago_cuota import PagoCuota
from app.models.tutor import Tutor
from app.services import recibo_token

logger = logging.getLogger(__name__)

_TEMPLATE_RECIBO = "recibo_pago"
_LANG_CODE = "es"


class ReciboEnvioResult(NamedTuple):
    """Resultado de intentar enviar el recibo de un pago por WhatsApp.

    `motivo` ∈ {"ok", "sin_telefono", "sin_cuota", "error_envio"}.
    """

    enviado: bool
    provider_message_id: str | None
    motivo: str


def _nombre_completo(a: Deportista) -> str:
    partes = [a.ap_paterno, a.ap_materno, a.nombres]
    return " ".join(p for p in partes if p).strip() or a.nombres


def _tutor_responsable(db: Session, deportista_id: uuid.UUID) -> Tutor | None:
    """Tutor `responsable_pago=True` del deportista (el primero, si hay varios)."""
    return db.execute(
        select(Tutor)
        .join(DeportistaTutor, DeportistaTutor.tutor_id == Tutor.id)
        .where(
            DeportistaTutor.deportista_id == deportista_id,
            DeportistaTutor.responsable_pago.is_(True),
        )
        .limit(1)
    ).scalar_one_or_none()


def _primera_cuota_de_pago(db: Session, pago_id: uuid.UUID) -> Cuota | None:
    """Una cuota cubierta por el pago (vía puente), para resolver deportista/inscripción."""
    return db.execute(
        select(Cuota)
        .join(PagoCuota, PagoCuota.cuota_id == Cuota.id)
        .where(PagoCuota.pago_id == pago_id)
        .order_by(Cuota.vence_el, Cuota.periodo_inicio)
        .limit(1)
    ).scalar_one_or_none()


def enviar_recibo_whatsapp(
    db: Session,
    *,
    pago: Pago,
    port: WhatsAppPort,
) -> ReciboEnvioResult:
    """Envía al tutor responsable el enlace al recibo PDF del `pago` por WhatsApp.

    Flujo:
    1. Resuelve cuota → inscripción → deportista → tutor responsable de pago.
    2. Sin cuota asociada ⇒ `motivo="sin_cuota"` (no envía). Sin teléfono ⇒
       `motivo="sin_telefono"` (no llama al puerto).
    3. Arma la plantilla pre-aprobada `recibo_pago` con el enlace tokenizado y la
       envía. `result.ok` ⇒ `ok`; si no, `error_envio`. No lanza ni commitea.
    """
    cuota = _primera_cuota_de_pago(db, pago.id)
    if cuota is None:
        return ReciboEnvioResult(enviado=False, provider_message_id=None, motivo="sin_cuota")

    insc = db.execute(
        select(Inscripcion).where(Inscripcion.id == cuota.inscripcion_id)
    ).scalar_one_or_none()
    deportista = (
        db.execute(
            select(Deportista).where(Deportista.id == insc.deportista_id)
        ).scalar_one_or_none()
        if insc is not None
        else None
    )
    tutor = _tutor_responsable(db, deportista.id) if deportista is not None else None
    telefono = tutor.telefono if (tutor is not None and tutor.telefono) else None

    if telefono is None:
        return ReciboEnvioResult(enviado=False, provider_message_id=None, motivo="sin_telefono")

    org = db.execute(
        select(Organizacion).where(Organizacion.id == pago.org_id)
    ).scalar_one_or_none()
    nombre_escuela = org.nombre if org is not None else "Escuela"

    nombre_deportista = _nombre_completo(deportista) if deportista is not None else "—"
    monto: Decimal = pago.monto
    numero_recibo = pago.numero_recibo or "—"
    url = recibo_token.url_recibo(pago.org_id, pago.id)

    # Plantilla pre-aprobada (RNF-07). body_params posicionales:
    #   {{1}} nombre deportista, {{2}} monto, {{3}} escuela, {{4}} N° recibo, {{5}} enlace PDF.
    msg = WhatsAppTemplateMessage(
        to=telefono,
        template_name=_TEMPLATE_RECIBO,
        lang_code=_LANG_CODE,
        body_params=[
            nombre_deportista,
            f"Bs {monto:.2f}",
            nombre_escuela,
            numero_recibo,
            url,
        ],
        header_image=None,
    )
    result = port.send_template(msg)

    if result.ok:
        return ReciboEnvioResult(
            enviado=True, provider_message_id=result.provider_message_id, motivo="ok"
        )

    logger.warning("recibo pago=%s envío WhatsApp falló: %s", pago.id, result.error)
    return ReciboEnvioResult(enviado=False, provider_message_id=None, motivo="error_envio")
