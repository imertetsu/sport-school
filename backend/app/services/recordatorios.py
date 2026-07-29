"""Recordatorios de cobro por WhatsApp (epic WhatsApp Cobro, saliente).

Envía recordatorios de cuota a los tutores responsables de pago vía el puerto
`WhatsAppPort`. **Epic pagos-qr-comprobante (C7):** adjunta el **QR estático de la
escuela** (`qr_cobro`, subido por el ADMIN) como **imagen** (`send_image`) con un
caption (deportista + monto + escuela + vence); si la escuela **no** tiene QR subido,
**degrada al texto** (`send_text`) — sin romper el flujo.

**Canal oficial (Meta):** cuando el puerto declara `requiere_plantilla()`, el envío
sale como **plantilla pre-aprobada** (`send_template`) con el QR en la **cabecera**.
Motivo: este recordatorio INICIA la conversación y Meta solo acepta texto/imagen
libres dentro de la ventana de 24 h desde el último mensaje del tutor. El texto de
la plantilla aprobada debe decir lo MISMO que `_texto_recordatorio` para que el
tutor reciba el mismo mensaje por cualquiera de los dos canales.

La conciliación de este pago
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

from app.core.org_context import set_current_org_id
from app.domain.ports.whatsapp import (
    WhatsAppImage,
    WhatsAppImageMessage,
    WhatsAppPort,
    WhatsAppTemplateMessage,
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


_MESES_MAY = (
    "",
    "ENERO",
    "FEBRERO",
    "MARZO",
    "ABRIL",
    "MAYO",
    "JUNIO",
    "JULIO",
    "AGOSTO",
    "SEPTIEMBRE",
    "OCTUBRE",
    "NOVIEMBRE",
    "DICIEMBRE",
)


def _mes_may(d: date) -> str:
    """Mes en MAYÚSCULAS, p.ej. `OCTUBRE` (la cuota se rotula por su vencimiento)."""
    return _MESES_MAY[d.month]


# --------------------------------------------------------------------------- #
# Plantillas del canal OFICIAL (Meta)
# --------------------------------------------------------------------------- #
# Nombres de las plantillas aprobadas en Meta. El canal oficial no deja escribir
# primero con texto libre (ventana de 24 h), así que el cron sale por aquí. El
# texto vive aprobado del lado de Meta; el de `_texto_recordatorio` debe decir lo
# MISMO para que el tutor reciba el mismo mensaje por cualquiera de los dos
# canales. Los 5 parámetros van en este orden EXACTO:
#   {{1}} deportista · {{2}} escuela · {{3}} meses · {{4}} vencimiento · {{5}} monto
# La cabecera es una IMAGEN: el QR de cobro de la escuela.
TEMPLATE_MORA = "recordatorio_mora"
TEMPLATE_PROXIMO = "recordatorio_proximo_vencimiento"
TEMPLATE_LANG = "es"


def _template_params(
    *, deportista: str, escuela: str, meses: list[str], vence: str, monto: Decimal
) -> list[str]:
    """Los 5 parámetros posicionales de la plantilla, en el orden aprobado."""
    return [
        deportista,
        escuela,
        ", ".join(meses) if meses else "—",
        vence,
        f"{monto:.2f}",
    ]


def _texto_recordatorio(
    tipo: str, *, deportista: str, monto: Decimal, escuela: str, meses: list[str], vence: str
) -> str:
    """Caption/texto del recordatorio.

    Empieza con el saludo pedido e incluye el DESGLOSE de las cuotas (por mes) junto
    a la fecha de vencimiento más antigua y el total. Mismo cuerpo se usa como caption
    de la imagen del QR o como texto plano si la escuela no tiene QR (degradación).
    RNF-07: mensaje claro, sin datos sensibles de menores más allá del nombre.
    """
    saludo = (
        f"Apreciado Padre y/o Madre de familia de {deportista}, este es un mensajito "
        f"de recordatorio."
    )
    lista_meses = ", ".join(meses) if meses else "—"
    if tipo == "MOROSIDAD":
        cuerpo = (
            f"Le informamos que en {escuela} tiene cuotas vencidas:\n"
            f"- Cuotas: {lista_meses}\n"
            f"- Vencimiento más antiguo: {vence}\n"
            f"- Total adeudado: Bs {monto:.2f}"
        )
    else:
        cuerpo = (
            f"Le recordamos su próximo pago en {escuela}:\n"
            f"- Cuota(s): {lista_meses}\n"
            f"- Vencimiento: {vence}\n"
            f"- Total: Bs {monto:.2f}"
        )
    cierre = (
        "Adjuntamos el QR de pago de la escuela; al pagar, responda con la captura del "
        "comprobante. ¡Gracias!"
    )
    return f"{saludo}\n\n{cuerpo}\n\n{cierre}"


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
    monto_override: Decimal | None = None,
    cuotas_desglose: list[Cuota] | None = None,
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

    # El adaptador del gateway resuelve la org por ContextVar. En un request sync ese
    # ContextVar (fijado por la dependencia) NO llega al cuerpo del endpoint (threadpool),
    # así que lo fijamos aquí; en el worker/cron ya viene fijado (idempotente).
    set_current_org_id(str(cuota.org_id))

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
    # `monto_override` permite que un recordatorio de MORA por deportista muestre el
    # TOTAL adeudado (suma de sus cuotas vencidas), no solo el de esta cuota ancla.
    monto: Decimal = monto_override if monto_override is not None else cuota.monto
    # Desglose: las cuotas a listar (todas las vencidas del deportista en la mora
    # manual; solo esta cuota en el cron/tabla). Meses únicos y en orden cronológico;
    # el vencimiento mostrado es el más antiguo.
    desglose = sorted(cuotas_desglose or [cuota], key=lambda c: c.vence_el)
    meses: list[str] = []
    for c in desglose:
        m = _mes_may(c.vence_el)
        if m not in meses:
            meses.append(m)
    vence_ddmmyyyy = desglose[0].vence_el.strftime("%d/%m/%Y")
    cuerpo = _texto_recordatorio(
        tipo,
        deportista=nombre,
        monto=monto,
        escuela=nombre_escuela,
        meses=meses,
        vence=vence_ddmmyyyy,
    )

    qr = db.execute(select(QrCobro).where(QrCobro.org_id == cuota.org_id)).scalar_one_or_none()
    qr_b64 = base64.b64encode(qr.imagen).decode("ascii") if qr is not None else None

    if port.requiere_plantilla() and qr_b64 is not None:
        # Canal OFICIAL (Meta): el recordatorio ARRANCA la conversación, así que el
        # texto libre no llega (ventana de 24 h). Sale como plantilla aprobada, con
        # el QR en la cabecera: es el único modo de que la imagen viaje en un
        # mensaje iniciado por la escuela.
        result = port.send_template(
            WhatsAppTemplateMessage(
                to=telefono,
                template_name=(TEMPLATE_MORA if tipo == "MOROSIDAD" else TEMPLATE_PROXIMO),
                lang_code=TEMPLATE_LANG,
                body_params=_template_params(
                    deportista=nombre,
                    escuela=nombre_escuela,
                    meses=meses,
                    vence=vence_ddmmyyyy,
                    monto=monto,
                ),
                header_image=WhatsAppImage(data_url=f"data:{qr.mime};base64,{qr_b64}"),
            )
        )
    elif qr_b64 is not None:
        # Canal libre (sidecar/mock): QR tal cual como imagen (no se decodifica) + caption.
        result = port.send_image(
            WhatsAppImageMessage(
                to=telefono,
                image_b64=qr_b64,
                mime=qr.mime,
                caption=cuerpo,
            )
        )
    else:
        # Sin QR: degrada al texto (no rompe el flujo). En el canal oficial este
        # texto solo llega si el tutor escribió en las últimas 24 h — la plantilla
        # exige la cabecera y sin QR no se puede rellenar. Queda FALLIDO y logueado,
        # que es más honesto que fingir un envío: la escuela debe subir su QR.
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
