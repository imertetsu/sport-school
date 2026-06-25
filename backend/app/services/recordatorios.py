"""Recordatorios de cobro por WhatsApp (epic WhatsApp Cobro, saliente).

Envía recordatorios de cuota a los tutores responsables de pago vía el puerto
`WhatsAppPort`. **Epic pagos-qr-comprobante (C7):** adjunta el **QR estático de la
escuela** (`qr_cobro`, subido por el ADMIN) como **imagen** (`send_image`) con un
caption (deportista + monto + escuela + vence); si la escuela **no** tiene QR subido,
**degrada al texto** (`send_text`) — sin romper el flujo. La conciliación de este pago
es **asistida-manual** (el tutor responde con la captura → cola "Pagos por verificar");
por eso este recordatorio **ya NO crea** el `crear_pago_qr` reconciliable OpenBCB
(OpenBCB fuera de este epic).

**Idempotencia (C1/RNF):** una fila `recordatorio_pago` por `(cuota_id, tipo,
ciclo)` (UNIQUE). El INSERT usa `ON CONFLICT DO NOTHING` (mismo patrón que
`_asignar_numero_recibo`): re-correr el cron el mismo día NO reenvía. `estado` se marca
`ENVIADO` solo tras `result.ok`; si el proveedor falla queda `FALLIDO`.

Ciclo por tipo:
- `PROXIMO_VENCIMIENTO` → `cuota.vence_el.isoformat()` (1 recordatorio por
  vencimiento de la cuota).
- `MOROSIDAD` → `hoy.strftime("%Y-%m")` (máx. 1 morosidad por cuota por mes).

Resolución del destinatario: cuota → inscripcion → deportista → deportista_tutor
(`responsable_pago=True`) → `tutor.telefono`. Sin tutor con teléfono ⇒ se registra
una fila `FALLIDO`/`sin_telefono` (idempotente igual), NO se llama al puerto ni se
crea QR. Corre bajo el `app.current_org` ya fijado por el caller (RLS); este módulo
no commitea (sigue la tx del caller).
"""

from __future__ import annotations

import base64
import logging
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import NamedTuple

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.domain.ports.whatsapp import (
    WhatsAppImageMessage,
    WhatsAppPort,
    WhatsAppTextMessage,
)
from app.models.cuota import Cuota
from app.models.deportista import Deportista
from app.models.deportista_tutor import DeportistaTutor
from app.models.inscripcion import Inscripcion
from app.models.organizacion import Organizacion
from app.models.qr_cobro import QrCobro
from app.models.recordatorio_pago import RecordatorioPago
from app.models.tutor import Tutor

logger = logging.getLogger(__name__)


def _texto_recordatorio(
    tipo: str, *, deportista: str, monto: Decimal, escuela: str, vence: str
) -> str:
    """Caption/texto del recordatorio (deportista + monto + escuela + vence).

    Mismo cuerpo se usa como caption de la imagen del QR o como texto plano si la
    escuela no tiene QR subido (degradación). RNF-07: mensaje claro, sin datos
    sensibles de menores más allá del nombre.
    """
    if tipo == "MOROSIDAD":
        return (
            f"La cuota de {deportista} en {escuela} está vencida: Bs {monto:.2f} "
            f"(venció el {vence}). Adjuntamos el QR de pago de la escuela; "
            f"al pagar, responda con la captura del comprobante."
        )
    return (
        f"Recordatorio de cuota de {deportista} en {escuela}: Bs {monto:.2f}, "
        f"vence el {vence}. Adjuntamos el QR de pago de la escuela; "
        f"al pagar, responda con la captura del comprobante."
    )


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


def _nombre_completo(a: Deportista) -> str:
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

    Flujo (C7):
    1. Resuelve `ciclo` por `tipo`.
    2. Resuelve el tutor responsable de pago y su teléfono. Sin teléfono ⇒ fila
       `FALLIDO`/`sin_telefono` (idempotente), sin llamar al puerto.
    3. INSERT idempotente de la fila (estado provisional `ENVIADO`). Ya existía y
       `forzar=False` ⇒ `ya_enviado` (no reenvía).
    4. Lee el `qr_cobro` de la org. Si existe ⇒ `send_image` (QR como imagen + caption);
       si NO existe ⇒ degrada a `send_text` (mismo cuerpo, sin imagen). **Ya NO crea**
       el `crear_pago_qr` reconciliable OpenBCB (conciliación asistida-manual: el tutor
       responde con la captura → cola "Pagos por verificar").
    5. `result.ok` ⇒ fija `ENVIADO` + `provider_message_id` + `enviado_en`; si no,
       `FALLIDO`. Todo en la MISMA tx del caller (no commitea aquí).
    """
    ciclo = _ciclo(tipo, cuota=cuota, hoy=hoy)

    # 2) Destinatario: cuota -> inscripcion -> deportista -> tutor responsable de pago.
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
        # Ya existía y no se fuerza: no reenvía.
        return RecordatorioResult(enviado=False, provider_message_id=None, motivo="ya_enviado")

    # Fila sobre la que operar: la recién insertada o la existente (forzar=True).
    fila = db.execute(
        select(RecordatorioPago).where(
            RecordatorioPago.cuota_id == cuota.id,
            RecordatorioPago.tipo == tipo,
            RecordatorioPago.ciclo == ciclo,
        )
    ).scalar_one()

    # 4) QR estático de la escuela (C7). Lo lee de `qr_cobro`; si existe, se adjunta como
    #    imagen (send_image) con el caption; si NO, degrada a texto (send_text). NO crea
    #    el pago QR reconciliable OpenBCB (conciliación asistida-manual de este epic).
    org = db.execute(
        select(Organizacion).where(Organizacion.id == cuota.org_id)
    ).scalar_one_or_none()
    nombre_escuela = org.nombre if org is not None else "Escuela"

    nombre = _nombre_completo(deportista) if deportista is not None else "—"
    monto: Decimal = cuota.monto
    vence_el_ddmmyyyy = cuota.vence_el.strftime("%d/%m/%Y")
    cuerpo = _texto_recordatorio(
        tipo,
        deportista=nombre,
        monto=monto,
        escuela=nombre_escuela,
        vence=vence_el_ddmmyyyy,
    )

    qr = db.execute(select(QrCobro).where(QrCobro.org_id == cuota.org_id)).scalar_one_or_none()
    if qr is not None:
        # QR subido: se reenvía tal cual como imagen (no se decodifica) + caption.
        result = port.send_image(
            WhatsAppImageMessage(
                to=telefono,
                image_b64=base64.b64encode(qr.imagen).decode("ascii"),
                mime=qr.mime,
                caption=cuerpo,
            )
        )
    else:
        # Sin QR: degrada al texto (no rompe el flujo).
        result = port.send_text(WhatsAppTextMessage(to=telefono, body=cuerpo))

    # 5) Resultado: ENVIADO solo si el proveedor aceptó.
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
