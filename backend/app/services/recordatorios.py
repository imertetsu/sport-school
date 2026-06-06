"""Recordatorios de cobro por WhatsApp (epic WhatsApp Cobro, saliente).

Envía recordatorios de cuota a los tutores responsables de pago vía el puerto
`WhatsAppPort`, adjuntando un **QR de cobro reconciliable**: el QR se crea con el
MISMO flujo de pago QR existente (`crear_pago_qr` + proveedor OpenBCB), de modo
que cuando el tutor paga, lo concilia el webhook `POST /webhooks/openbcb` ya
existente (idempotente por `transaccion_id`). NO se abre un segundo camino de
pago.

**Idempotencia (C1/RNF):** una fila `recordatorio_pago` por `(cuota_id, tipo,
ciclo)` (UNIQUE). El INSERT usa `ON CONFLICT DO NOTHING` (mismo patrón que
`_asignar_numero_recibo`): re-correr el cron el mismo día NO reenvía ni genera un
segundo QR. `estado` se marca `ENVIADO` solo tras `result.ok`; si el proveedor
falla queda `FALLIDO`.

Ciclo por tipo:
- `PROXIMO_VENCIMIENTO` → `cuota.vence_el.isoformat()` (1 recordatorio por
  vencimiento de la cuota).
- `MOROSIDAD` → `hoy.strftime("%Y-%m")` (máx. 1 morosidad por cuota por mes).

Resolución del destinatario: cuota → inscripcion → alumno → alumno_tutor
(`responsable_pago=True`) → `tutor.telefono`. Sin tutor con teléfono ⇒ se registra
una fila `FALLIDO`/`sin_telefono` (idempotente igual), NO se llama al puerto ni se
crea QR. Corre bajo el `app.current_org` ya fijado por el caller (RLS); este módulo
no commitea (sigue la tx del caller).
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import NamedTuple

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.domain.ports.whatsapp import WhatsAppPort, WhatsAppTemplateMessage
from app.models.alumno import Alumno
from app.models.alumno_tutor import AlumnoTutor
from app.models.cuota import Cuota
from app.models.inscripcion import Inscripcion
from app.models.organizacion import Organizacion
from app.models.recordatorio_pago import RecordatorioPago
from app.models.tutor import Tutor
from app.services import pagos as pagos_svc
from app.services.deps import get_payment_provider

logger = logging.getLogger(__name__)

# Plantillas pre-aprobadas (RNF-07): nombre por tipo de recordatorio.
_TEMPLATE_POR_TIPO = {
    "PROXIMO_VENCIMIENTO": "recordatorio_cuota_qr",
    "MOROSIDAD": "morosidad_cuota_qr",
}
_LANG_CODE = "es"


class RecordatorioResult(NamedTuple):
    """Resultado de intentar enviar un recordatorio de una cuota.

    `motivo` ∈ {"ok", "ya_enviado", "sin_telefono", "error_envio"}.
    """

    enviado: bool
    provider_message_id: str | None
    motivo: str


def _ciclo(tipo: str, *, cuota: Cuota, hoy: date) -> str:
    """Clave de deduplicación por tipo (ver docstring de módulo)."""
    if tipo == "MOROSIDAD":
        return hoy.strftime("%Y-%m")
    return cuota.vence_el.isoformat()


def _tutor_responsable(db: Session, alumno_id: uuid.UUID) -> Tutor | None:
    """Tutor `responsable_pago=True` del alumno (el primero, si hay varios)."""
    return db.execute(
        select(Tutor)
        .join(AlumnoTutor, AlumnoTutor.tutor_id == Tutor.id)
        .where(AlumnoTutor.alumno_id == alumno_id, AlumnoTutor.responsable_pago.is_(True))
        .limit(1)
    ).scalar_one_or_none()


def _nombre_completo(a: Alumno) -> str:
    partes = [a.ap_paterno, a.ap_materno, a.nombres]
    return " ".join(p for p in partes if p).strip() or a.nombres


def _insert_idempotente(
    db: Session,
    *,
    cuota: Cuota,
    tutor_id: uuid.UUID | None,
    tipo: str,
    ciclo: str,
    destino: str | None,
    estado: str,
) -> uuid.UUID | None:
    """INSERT ON CONFLICT DO NOTHING en `recordatorio_pago` (patrón idempotente).

    Devuelve el `id` insertado, o `None` si ya existía la fila
    `(cuota_id, tipo, ciclo)`. Mismo enfoque que `_asignar_numero_recibo`.
    """
    stmt = (
        pg_insert(RecordatorioPago)
        .values(
            org_id=cuota.org_id,
            cuota_id=cuota.id,
            tutor_id=tutor_id,
            tipo=tipo,
            ciclo=ciclo,
            canal="WHATSAPP",
            destino=destino,
            estado=estado,
        )
        .on_conflict_do_nothing(index_elements=["cuota_id", "tipo", "ciclo"])
        .returning(RecordatorioPago.id)
    )
    inserted = db.execute(stmt).scalar_one_or_none()
    db.flush()
    return inserted


def enviar_recordatorio_cuota(
    db: Session,
    *,
    cuota: Cuota,
    tipo: str,
    hoy: date,
    port: WhatsAppPort,
    forzar: bool = False,
) -> RecordatorioResult:
    """Envía (idempotentemente) un recordatorio de cobro de `cuota` por WhatsApp.

    Flujo:
    1. Resuelve `ciclo` por `tipo`.
    2. Resuelve el tutor responsable de pago y su teléfono. Sin teléfono ⇒ fila
       `FALLIDO`/`sin_telefono` (idempotente), sin llamar al puerto ni crear QR.
    3. INSERT idempotente de la fila (estado provisional `ENVIADO`). Ya existía y
       `forzar=False` ⇒ `ya_enviado` (no reenvía, no crea QR).
    4. Crea un QR de cobro RECONCILIABLE (reusa `crear_pago_qr` + proveedor) y lo
       guarda en `qr_ref`. El `payload` (deep-link) es la variable `{{5}}`.
    5. Arma y envía la plantilla pre-aprobada vía el puerto.
    6. `result.ok` ⇒ fija `ENVIADO` + `provider_message_id` + `enviado_en`; si no,
       `FALLIDO`. Todo en la MISMA tx del caller (no commitea aquí).
    """
    ciclo = _ciclo(tipo, cuota=cuota, hoy=hoy)

    # 2) Destinatario: cuota -> inscripcion -> alumno -> tutor responsable de pago.
    insc = db.execute(
        select(Inscripcion).where(Inscripcion.id == cuota.inscripcion_id)
    ).scalar_one_or_none()
    alumno = (
        db.execute(select(Alumno).where(Alumno.id == insc.alumno_id)).scalar_one_or_none()
        if insc is not None
        else None
    )
    tutor = _tutor_responsable(db, alumno.id) if alumno is not None else None
    telefono = tutor.telefono if (tutor is not None and tutor.telefono) else None

    if telefono is None:
        # Sin teléfono: registra el intento como FALLIDO (idempotente igual), no
        # llama al puerto ni crea QR. Nunca se "pierde" la cuota: queda auditada.
        _insert_idempotente(
            db,
            cuota=cuota,
            tutor_id=tutor.id if tutor is not None else None,
            tipo=tipo,
            ciclo=ciclo,
            destino=None,
            estado="FALLIDO",
        )
        return RecordatorioResult(enviado=False, provider_message_id=None, motivo="sin_telefono")

    # 3) INSERT idempotente (dedup por cuota+tipo+ciclo).
    inserted_id = _insert_idempotente(
        db,
        cuota=cuota,
        tutor_id=tutor.id if tutor is not None else None,
        tipo=tipo,
        ciclo=ciclo,
        destino=telefono,
        estado="ENVIADO",
    )

    if inserted_id is None and not forzar:
        # Ya existía y no se fuerza: no reenvía ni genera un segundo QR.
        return RecordatorioResult(enviado=False, provider_message_id=None, motivo="ya_enviado")

    # Fila sobre la que operar: la recién insertada o la existente (forzar=True).
    fila = db.execute(
        select(RecordatorioPago).where(
            RecordatorioPago.cuota_id == cuota.id,
            RecordatorioPago.tipo == tipo,
            RecordatorioPago.ciclo == ciclo,
        )
    ).scalar_one()

    # 4) QR de cobro RECONCILIABLE: mismo flujo que el pago QR del router. Cuando el
    #    tutor pague, lo concilia el webhook OpenBCB existente (idempotente).
    org = db.execute(
        select(Organizacion).where(Organizacion.id == cuota.org_id)
    ).scalar_one_or_none()
    moneda = org.moneda if org is not None else "BOB"
    nombre_escuela = org.nombre if org is not None else "Escuela"

    provider = get_payment_provider()
    charge = provider.create_qr_charge(reference="pending", amount=cuota.monto, currency=moneda)
    # Pago QR PENDIENTE reconciliable (side effect): lo confirmará el webhook OpenBCB.
    pagos_svc.crear_pago_qr(
        db,
        org_id=cuota.org_id,
        cuota_ids=[cuota.id],
        qr_ref=charge.qr_ref,
    )
    fila.qr_ref = charge.qr_ref
    db.flush()

    # 5) Plantilla pre-aprobada. body_params posicionales (RNF-07):
    #    {{1}} nombre alumno, {{2}} monto, {{3}} escuela, {{4}} vence (DD/MM/YYYY),
    #    {{5}} payload del QR (deep-link de cobro).
    nombre = _nombre_completo(alumno) if alumno is not None else "—"
    monto: Decimal = cuota.monto
    vence_el_ddmmyyyy = cuota.vence_el.strftime("%d/%m/%Y")
    msg = WhatsAppTemplateMessage(
        to=telefono,
        template_name=_TEMPLATE_POR_TIPO.get(tipo, _TEMPLATE_POR_TIPO["PROXIMO_VENCIMIENTO"]),
        lang_code=_LANG_CODE,
        body_params=[
            nombre,
            f"Bs {monto:.2f}",
            nombre_escuela,
            vence_el_ddmmyyyy,
            charge.payload,
        ],
        header_image=None,
    )
    result = port.send_template(msg)

    # 6) Resultado: ENVIADO solo si el proveedor aceptó.
    if result.ok:
        fila.estado = "ENVIADO"
        fila.provider_message_id = result.provider_message_id
        fila.enviado_en = datetime.now(UTC)
        db.flush()
        return RecordatorioResult(
            enviado=True, provider_message_id=result.provider_message_id, motivo="ok"
        )

    fila.estado = "FALLIDO"
    db.flush()
    logger.warning(
        "recordatorio %s cuota=%s envío falló: %s",
        tipo,
        cuota.id,
        result.error,
    )
    return RecordatorioResult(enviado=False, provider_message_id=None, motivo="error_envio")
