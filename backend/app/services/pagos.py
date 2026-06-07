"""Servicio de pagos y conciliación (C3) — efectivo, QR, webhook idempotente.

Reglas:
- **Efectivo**: pago CONFIRMADO directo; aplica a cuotas (FIFO) vía `pago_cuota`,
  marca cuotas PAGADO, genera comprobante, notifica.
- **QR**: pago PENDIENTE + `qr_ref` (del proveedor sandbox); la confirmación llega
  por webhook (o por el endpoint de simulación, que reentra al mismo flujo).
- **Webhook**: idempotente por `transaccion_id`; resuelve el pago con
  `webhook_resolver(:ref)` (SECURITY DEFINER), fija `app.current_org`, valida el
  monto, confirma y aplica; si no resuelve o el monto no cuadra → fila en
  `conciliacion_pendiente` (NUNCA descarta el pago, RNF-06).

Todo lo "tenant" corre con `app.current_org` fijado (RLS). El webhook lo fija él
mismo tras resolver, en su propia transacción.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.core.config import settings
from app.domain.cobranza.abono_engine import distribuir_abono
from app.domain.ports.invoice import ComprobanteData, ComprobanteService, CuotaLinea
from app.domain.ports.notification import NotificationService
from app.models.conciliacion_pendiente import ConciliacionPendiente
from app.models.credito import Credito
from app.models.cuota import Cuota
from app.models.deportista import Deportista
from app.models.inscripcion import Inscripcion
from app.models.organizacion import Organizacion
from app.models.pago import Pago
from app.models.pago_cuota import PagoCuota


def _saldo(cuota: Cuota) -> Decimal:
    """Saldo derivado de una cuota (RF-ABO-03): `monto - monto_pagado`."""
    return cuota.monto - cuota.monto_pagado


def _estado_destino(cuota: Cuota, hoy: date) -> str:
    """Estado destino tras aplicar un abono (RF-ABO-05).

    `saldo == 0` → PAGADO; elif `vence_el < hoy` → VENCIDO (precedencia sobre
    parcial); elif `monto_pagado > 0` → PARCIAL; else sin cambio (estado actual).
    """
    if _saldo(cuota) <= Decimal("0"):
        return "PAGADO"
    if cuota.vence_el < hoy:
        return "VENCIDO"
    if cuota.monto_pagado > Decimal("0"):
        return "PARCIAL"
    return cuota.estado


class PagoError(Exception):
    """Error de negocio en el flujo de pagos (lo traduce el router a HTTP)."""


# --------------------------------------------------------------------------- #
# Helpers de cuotas / FIFO
# --------------------------------------------------------------------------- #
def cargar_cuotas_fifo(db: Session, cuota_ids: list[uuid.UUID]) -> list[Cuota]:
    """Carga las cuotas pedidas y las ordena FIFO (vencidas más antiguas primero).

    RLS garantiza que solo se ven cuotas de la org del contexto. Si alguna no
    existe (otra org o id inválido), se lanza PagoError (404 en el router).
    """
    cuotas = db.execute(select(Cuota).where(Cuota.id.in_(cuota_ids))).scalars().all()
    encontradas = {c.id for c in cuotas}
    faltan = [str(cid) for cid in cuota_ids if cid not in encontradas]
    if faltan:
        raise PagoError(f"Cuota(s) no encontrada(s): {', '.join(faltan)}")
    # FIFO: vence_el asc, luego periodo_inicio asc.
    return sorted(cuotas, key=lambda c: (c.vence_el, c.periodo_inicio))


def _aplicar_pago_a_cuotas(
    db: Session,
    *,
    pago: Pago,
    cuotas: list[Cuota],
    org_id: uuid.UUID,
    aplicaciones: dict[uuid.UUID, Decimal] | None = None,
    hoy: date | None = None,
) -> None:
    """Aplica el pago a las cuotas (FIFO) vía `pago_cuota` y recalcula su estado.

    `aplicaciones` mapea `cuota_id -> monto a aplicar`. Si es `None`, se aplica el
    saldo completo de cada cuota (camino del pago total / QR).

    **Idempotente (RF-ABO-07):** solo incrementa `cuota.monto_pagado` y recalcula
    `cuota.estado` cuando **INSERTA** la fila puente (rama `ya is None`). El
    `UNIQUE(pago_id, cuota_id)` es la barrera: re-aplicar el mismo pago a la misma
    cuota no altera nada (no doble cobro). El estado destino sigue RF-ABO-05.
    """
    hoy = hoy or datetime.now(UTC).date()
    for cuota in cuotas:
        monto_aplicado = aplicaciones.get(cuota.id) if aplicaciones is not None else _saldo(cuota)
        if monto_aplicado is None:
            monto_aplicado = Decimal("0")
        ya = db.execute(
            select(PagoCuota.id).where(PagoCuota.pago_id == pago.id, PagoCuota.cuota_id == cuota.id)
        ).first()
        if ya is None:
            db.add(
                PagoCuota(
                    org_id=org_id,
                    pago_id=pago.id,
                    cuota_id=cuota.id,
                    monto_aplicado=monto_aplicado,
                )
            )
            cuota.monto_pagado = cuota.monto_pagado + monto_aplicado
            cuota.estado = _estado_destino(cuota, hoy)
    db.flush()


def _cuotas_de_pago(db: Session, pago_id: uuid.UUID) -> list[Cuota]:
    """Cuotas cubiertas por un pago (vía puente), ordenadas FIFO."""
    rows = (
        db.execute(
            select(Cuota)
            .join(PagoCuota, PagoCuota.cuota_id == Cuota.id)
            .where(PagoCuota.pago_id == pago_id)
            .order_by(Cuota.vence_el, Cuota.periodo_inicio)
        )
        .scalars()
        .all()
    )
    return list(rows)


# --------------------------------------------------------------------------- #
# Comprobante + notificación
# --------------------------------------------------------------------------- #
def _deportista_de_cuotas(db: Session, cuotas: list[Cuota]) -> Deportista | None:
    if not cuotas:
        return None
    insc = db.execute(
        select(Inscripcion).where(Inscripcion.id == cuotas[0].inscripcion_id)
    ).scalar_one_or_none()
    if insc is None:
        return None
    return db.execute(
        select(Deportista).where(Deportista.id == insc.deportista_id)
    ).scalar_one_or_none()


def _nombre_completo(a: Deportista) -> str:
    partes = [a.ap_paterno, a.ap_materno, a.nombres]
    return " ".join(p for p in partes if p).strip() or a.nombres


def construir_comprobante_data(db: Session, *, pago: Pago, org: Organizacion) -> ComprobanteData:
    """Arma `ComprobanteData` (dominio) a partir del pago y sus cuotas.

    Abonos: cada línea lleva `monto_aplicado` (de la fila puente) y `saldo_restante`
    (saldo de la cuota tras aplicar). Pie: `credito_aplicado` (crédito previo
    consumido por este pago) y `credito_generado` (saldo a favor de la inscripción
    tras el pago). Para QR full → aplicado = monto, saldo = 0, créditos = 0 (igual
    que hoy).
    """
    cuotas = _cuotas_de_pago(db, pago.id)
    deportista = _deportista_de_cuotas(db, cuotas)

    aplicados: dict[uuid.UUID, Decimal] = {
        row.cuota_id: row.monto_aplicado
        for row in db.execute(
            select(PagoCuota.cuota_id, PagoCuota.monto_aplicado).where(PagoCuota.pago_id == pago.id)
        ).all()
    }

    lineas = [
        CuotaLinea(
            periodo_inicio=c.periodo_inicio.isoformat(),
            vence_el=c.vence_el.isoformat(),
            monto=c.monto,
            monto_aplicado=aplicados.get(c.id, c.monto),
            saldo_restante=_saldo(c),
        )
        for c in cuotas
    ]

    credito_generado = Decimal("0")
    if cuotas:
        credito_generado = saldo_credito_inscripcion(db, cuotas[0].inscripcion_id)

    return ComprobanteData(
        numero=str(pago.id),
        org_nombre=org.nombre,
        moneda=org.moneda,
        deportista_nombre=_nombre_completo(deportista) if deportista else "—",
        metodo=pago.metodo,
        fecha=pago.pagado_en or datetime.now(UTC),
        monto_total=pago.monto,
        cuotas=lineas,
        credito_aplicado=pago.credito_aplicado,
        credito_generado=credito_generado,
        numero_recibo=pago.numero_recibo or "—",
        emisor=settings.recibo_emisor,
    )


def _enviar_recibo_por_whatsapp(db: Session, *, pago: Pago) -> None:
    """Engancha (aditivo) el envío del recibo PDF por WhatsApp tras confirmar el pago.

    Se llama UNA vez por confirmación (efectivo: flujo único; QR: la guarda
    `pago.estado == "CONFIRMADO"` de `_confirmar_y_aplicar` ya corta el reenvío en
    webhooks duplicados). Selecciona el adaptador por configuración vía
    `get_whatsapp_port()` (mock en dev/CI). NO altera la conciliación ni lanza: el
    recibo no es crítico para confirmar el pago (sin teléfono/fallo ⇒ se ignora).

    Import diferido de `deps`/`recibo_envio` para no acoplar el módulo de pagos al
    wiring de adaptadores en import time.
    """
    from app.services import recibo_envio
    from app.services.deps import get_whatsapp_port

    recibo_envio.enviar_recibo_whatsapp(db, pago=pago, port=get_whatsapp_port())


def _asignar_numero_recibo(db: Session, pago: Pago) -> None:
    """Asigna el correlativo `REC-NNNNNN` por org al pago, si aún no tiene (RF-REC).

    **Idempotente (RF-REC-03):** si `pago.numero_recibo` ya está fijado, no reasigna
    ni consume número. El incremento del contador de la org es **atómico** (un solo
    `INSERT ... ON CONFLICT (org_id) DO UPDATE ... RETURNING`, RF-REC-04), de modo que
    dos confirmaciones concurrentes de la misma org no obtienen el mismo número. Corre
    bajo el `app.current_org` ya fijado (RLS de `recibo_contador`).
    """
    if pago.numero_recibo is not None:
        return
    n = db.execute(
        text(
            "INSERT INTO recibo_contador (org_id, ultimo_numero) "
            "VALUES (:org_id, 1) "
            "ON CONFLICT (org_id) "
            "DO UPDATE SET ultimo_numero = recibo_contador.ultimo_numero + 1, "
            "updated_at = now() "
            "RETURNING ultimo_numero"
        ),
        {"org_id": str(pago.org_id)},
    ).scalar_one()
    pago.numero_recibo = f"REC-{int(n):06d}"
    db.flush()


def _confirmar_y_aplicar(
    db: Session,
    *,
    pago: Pago,
    cuotas: list[Cuota],
    org_id: uuid.UUID,
    comprobante: ComprobanteService | None,
    notifier: NotificationService | None,
) -> None:
    """Marca el pago CONFIRMADO, aplica el saldo a las cuotas, fija comprobante y notifica.

    Camino **QR/webhook**: el pago cubre el total. Las filas puente `pago_cuota` ya
    existen (creadas en `crear_pago_qr` como intención); por eso la aplicación del
    saldo a `monto_pagado`/estado se hace aquí, guardada por la idempotencia de
    `pago.estado == "CONFIRMADO"` (no reaplica ni renotifica un pago ya confirmado).
    El QR full cae en el motor con `monto_recibido == Σ saldo` → todas PAGADO, sin
    crédito (RF-ABO QR intacto).
    """
    if pago.estado == "CONFIRMADO":
        return

    hoy = datetime.now(UTC).date()
    pago.estado = "CONFIRMADO"
    if pago.pagado_en is None:
        pago.pagado_en = datetime.now(UTC)
    # Recibo: correlativo por org al confirmar (idempotente; ver _asignar_numero_recibo).
    _asignar_numero_recibo(db, pago)

    # QR full: cada cuota se salda por completo. El motor reparte el monto del pago
    # (== Σ saldos) sobre los saldos FIFO; sin remanente.
    saldos = [_saldo(c) for c in cuotas]
    resultado = distribuir_abono(pago.monto, saldos)
    aplicaciones = {c.id: m for c, m in zip(cuotas, resultado.aplicaciones, strict=True)}
    for cuota, monto_aplicado in zip(cuotas, resultado.aplicaciones, strict=True):
        cuota.monto_pagado = cuota.monto_pagado + monto_aplicado
        cuota.estado = _estado_destino(cuota, hoy)
    # Sincroniza el monto_aplicado de las filas puente pre-creadas (intención QR).
    _sincronizar_puentes(db, pago=pago, aplicaciones=aplicaciones)
    db.flush()

    # comprobante_url apunta al endpoint que genera el PDF on-the-fly (C5).
    pago.comprobante_url = f"/api/v1/cobranza/comprobantes/{pago.id}.pdf"
    db.flush()

    if notifier is not None:
        notifier.send(
            to=str(pago.id),
            template="comprobante",
            variables={"pago_id": str(pago.id), "monto": str(pago.monto)},
        )

    # Recibo PDF al tutor por WhatsApp (epic Sucursales/Recibo). Aditivo: una sola
    # vez por confirmación (la guarda `estado == "CONFIRMADO"` de arriba garantiza
    # que un webhook duplicado no reentra aquí, así que no se reenvía).
    _enviar_recibo_por_whatsapp(db, pago=pago)


def _sincronizar_puentes(
    db: Session, *, pago: Pago, aplicaciones: dict[uuid.UUID, Decimal]
) -> None:
    """Fija el `monto_aplicado` real en las filas puente del pago (QR confirm).

    Las filas se crearon como intención en `crear_pago_qr` con `monto_aplicado =
    cuota.monto`; tras confirmar, lo igualamos a lo realmente aplicado (= saldo del
    momento). Para el QR full coinciden, pero lo dejamos explícito por robustez.
    """
    puentes = db.execute(select(PagoCuota).where(PagoCuota.pago_id == pago.id)).scalars().all()
    for puente in puentes:
        nuevo = aplicaciones.get(puente.cuota_id)
        if nuevo is not None:
            puente.monto_aplicado = nuevo


# --------------------------------------------------------------------------- #
# Crédito (saldo a favor por inscripción) — RF-ABO-06/07
# --------------------------------------------------------------------------- #
def _credito_de_inscripcion(db: Session, inscripcion_id: uuid.UUID) -> Credito | None:
    """Fila de crédito de la inscripción (única por `UNIQUE(inscripcion_id)`)."""
    return db.execute(
        select(Credito).where(Credito.inscripcion_id == inscripcion_id)
    ).scalar_one_or_none()


def _upsert_credito(
    db: Session, *, org_id: uuid.UUID, inscripcion_id: uuid.UUID, saldo: Decimal
) -> None:
    """Fija el `saldo` de crédito de la inscripción (upsert por UNIQUE inscripcion_id).

    Crea la fila si no existe (solo cuando hay saldo > 0; nunca persiste un crédito
    en 0 que no existía). `CHECK(saldo >= 0)` lo garantiza el motor (remanente ≥ 0).
    """
    credito = _credito_de_inscripcion(db, inscripcion_id)
    if credito is None:
        if saldo > Decimal("0"):
            db.add(Credito(org_id=org_id, inscripcion_id=inscripcion_id, saldo=saldo))
            db.flush()
        return
    credito.saldo = saldo
    db.flush()


def saldo_credito_inscripcion(db: Session, inscripcion_id: uuid.UUID) -> Decimal:
    """Saldo a favor actual de la inscripción (0 si no hay crédito)."""
    credito = _credito_de_inscripcion(db, inscripcion_id)
    return credito.saldo if credito is not None else Decimal("0")


# --------------------------------------------------------------------------- #
# Efectivo (con abonos parciales + crédito)
# --------------------------------------------------------------------------- #
def registrar_pago_efectivo(
    db: Session,
    *,
    org_id: uuid.UUID,
    cuota_ids: list[uuid.UUID],
    registrado_por: uuid.UUID,
    monto_recibido: Decimal | None = None,
    comprobante: ComprobanteService | None = None,
    notifier: NotificationService | None = None,
) -> Pago:
    """Crea un pago EFECTIVO CONFIRMADO y lo aplica FIFO con abonos (RF-ABO).

    `monto_recibido` es el efectivo de caja. `None` ⇒ Σ saldos (paga todo, igual que
    hoy). El servicio consume primero el **crédito previo** de la inscripción (como
    monto inicial) y luego el efectivo; `pago.monto` = efectivo, `pago.credito_aplicado`
    = crédito consumido. El remanente (sobrepago) → upsert del crédito de la
    inscripción. Invariante RF-ABO-08:
    `Σ pago_cuota.monto_aplicado = pago.monto + pago.credito_aplicado`.

    Asume cuotas homogéneas en inscripción (RF-ABO-11): el form lo restringe.
    """
    hoy = datetime.now(UTC).date()
    cuotas = cargar_cuotas_fifo(db, cuota_ids)
    inscripcion_id = cuotas[0].inscripcion_id

    saldos = [_saldo(c) for c in cuotas]
    suma_saldos = sum(saldos, Decimal("0"))

    efectivo_recibido = monto_recibido if monto_recibido is not None else suma_saldos
    credito_previo = saldo_credito_inscripcion(db, inscripcion_id)

    # Monto disponible = crédito previo (se consume PRIMERO) + efectivo de caja.
    disponible = credito_previo + efectivo_recibido
    resultado = distribuir_abono(disponible, saldos)
    total_aplicado = sum(resultado.aplicaciones, Decimal("0"))

    # Imputación: el crédito previo entra primero, así que se consume primero.
    #   credito_aplicado = min(credito_previo, total_aplicado)
    #   pago.monto       = total_aplicado - credito_aplicado  (efectivo realmente aplicado)
    # El sobrante (efectivo recibido no aplicado + crédito no consumido) = remanente,
    # que se vuelve crédito de la inscripción. Esto hace que la invariante RF-ABO-08
    # (Σ aplicado = pago.monto + pago.credito_aplicado) se cumpla en TODOS los flujos.
    credito_aplicado = credito_previo if credito_previo < total_aplicado else total_aplicado
    monto_efectivo_aplicado = total_aplicado - credito_aplicado

    pago = Pago(
        org_id=org_id,
        metodo="EFECTIVO",
        estado="PENDIENTE",  # se confirma abajo
        monto=monto_efectivo_aplicado,  # efectivo de caja aplicado (RF-ABO-07/08)
        credito_aplicado=credito_aplicado,
        registrado_por=registrado_por,
        pagado_en=datetime.now(UTC),
    )
    db.add(pago)
    db.flush()

    pago.estado = "CONFIRMADO"
    # Recibo: correlativo por org al confirmar (efectivo NO pasa por _confirmar_y_aplicar).
    _asignar_numero_recibo(db, pago)
    aplicaciones = {c.id: m for c, m in zip(cuotas, resultado.aplicaciones, strict=True)}
    _aplicar_pago_a_cuotas(
        db,
        pago=pago,
        cuotas=cuotas,
        org_id=org_id,
        aplicaciones=aplicaciones,
        hoy=hoy,
    )

    # Remanente (sobrepago) → crédito de la inscripción (RF-ABO-06).
    _upsert_credito(db, org_id=org_id, inscripcion_id=inscripcion_id, saldo=resultado.remanente)

    pago.comprobante_url = f"/api/v1/cobranza/comprobantes/{pago.id}.pdf"
    db.flush()

    if notifier is not None:
        notifier.send(
            to=str(pago.id),
            template="comprobante",
            variables={"pago_id": str(pago.id), "monto": str(pago.monto)},
        )

    # Recibo PDF al tutor por WhatsApp (epic Sucursales/Recibo). Aditivo: el efectivo
    # se confirma una sola vez en este flujo, así que el recibo se envía una vez.
    _enviar_recibo_por_whatsapp(db, pago=pago)
    return pago


# --------------------------------------------------------------------------- #
# QR
# --------------------------------------------------------------------------- #
def crear_pago_qr(
    db: Session,
    *,
    org_id: uuid.UUID,
    cuota_ids: list[uuid.UUID],
    qr_ref: str,
) -> Pago:
    """Crea un pago QR PENDIENTE con `qr_ref` y lo asocia a las cuotas (FIFO) (C3).

    La asociación se hace ya (vía `pago_cuota`) para saber qué cuotas marcar PAGADO
    cuando llegue la confirmación; las cuotas se marcan PAGADO recién al confirmar.
    """
    cuotas = cargar_cuotas_fifo(db, cuota_ids)
    monto = sum((c.monto for c in cuotas), Decimal("0"))

    pago = Pago(
        org_id=org_id,
        metodo="QR",
        estado="PENDIENTE",
        monto=monto,
        qr_ref=qr_ref,
    )
    db.add(pago)
    db.flush()

    # Registrar la intención de aplicación (puente) sin marcar PAGADO todavía.
    for cuota in cuotas:
        db.add(
            PagoCuota(
                org_id=org_id,
                pago_id=pago.id,
                cuota_id=cuota.id,
                monto_aplicado=cuota.monto,
            )
        )
    db.flush()
    return pago


# --------------------------------------------------------------------------- #
# Webhook / conciliación
# --------------------------------------------------------------------------- #
def _encolar_conciliacion(
    db: Session,
    *,
    transaccion_id: str | None,
    referencia: str | None,
    monto: Decimal | None,
    motivo: str,
    payload: dict,
) -> None:
    """Inserta en `conciliacion_pendiente` (sin org_id ni RLS). Nunca pierde el pago."""
    db.add(
        ConciliacionPendiente(
            transaccion_id=transaccion_id,
            referencia=referencia,
            monto=monto,
            payload=json.loads(json.dumps(payload, default=str)),
            motivo=motivo,
            resuelto=False,
        )
    )
    db.flush()


def procesar_webhook(
    db: Session,
    *,
    transaccion_id: str,
    referencia: str,
    monto: Decimal,
    comprobante: ComprobanteService | None = None,
    notifier: NotificationService | None = None,
) -> str:
    """Procesa el webhook OpenBCB de forma idempotente (C3). Devuelve un estado
    textual ("idempotente" | "confirmado" | "conciliacion").

    NO fija `app.current_org` antes de resolver: usa `webhook_resolver` (SECURITY
    DEFINER) que salta RLS para localizar el pago por `qr_ref`. Luego fija el org
    del pago y confirma dentro de la misma transacción.
    """
    payload = {
        "transaccion_id": transaccion_id,
        "referencia": referencia,
        "monto": str(monto),
    }

    # 1) Idempotencia: transaccion_id ya visto -> no reprocesar. La búsqueda usa
    #    webhook_resolver por referencia; pero el transaccion_id puede repetirse
    #    sobre el mismo pago. Chequeamos vía la función + estado.
    resuelto = (
        db.execute(
            text("SELECT pago_id, org_id, monto_esperado, estado FROM webhook_resolver(:ref)"),
            {"ref": referencia},
        )
        .mappings()
        .first()
    )

    if resuelto is None:
        # Referencia inexistente -> a conciliación (nunca se descarta).
        _encolar_conciliacion(
            db,
            transaccion_id=transaccion_id,
            referencia=referencia,
            monto=monto,
            motivo="referencia_inexistente",
            payload=payload,
        )
        return "conciliacion"

    pago_id = resuelto["pago_id"]
    org_id = resuelto["org_id"]
    monto_esperado = Decimal(str(resuelto["monto_esperado"]))
    estado_actual = resuelto["estado"]

    # Fijar el contexto de tenant del pago para operar bajo RLS.
    db.execute(
        text("SELECT set_config('app.current_org', :org, true)"),
        {"org": str(org_id)},
    )

    # 2) Idempotencia por estado: si ya está CONFIRMADO, responder sin reprocesar.
    if estado_actual == "CONFIRMADO":
        return "idempotente"

    # 2b) Idempotencia por transaccion_id: si ESTE transaccion_id ya está en otro
    #     pago confirmado, no reprocesar (evita doble pago).
    ya_tx = db.execute(select(Pago.id).where(Pago.transaccion_id == transaccion_id)).first()
    if ya_tx is not None:
        return "idempotente"

    # 3) Monto: si no cuadra -> conciliación (no se descarta).
    if monto != monto_esperado:
        _encolar_conciliacion(
            db,
            transaccion_id=transaccion_id,
            referencia=referencia,
            monto=monto,
            motivo=f"monto_no_cuadra esperado={monto_esperado} recibido={monto}",
            payload=payload,
        )
        return "conciliacion"

    pago = db.execute(select(Pago).where(Pago.id == pago_id)).scalar_one_or_none()
    if pago is None:
        _encolar_conciliacion(
            db,
            transaccion_id=transaccion_id,
            referencia=referencia,
            monto=monto,
            motivo="pago_no_visible_bajo_rls",
            payload=payload,
        )
        return "conciliacion"

    pago.transaccion_id = transaccion_id
    cuotas = _cuotas_de_pago(db, pago.id)
    _confirmar_y_aplicar(
        db,
        pago=pago,
        cuotas=cuotas,
        org_id=uuid.UUID(str(org_id)),
        comprobante=comprobante,
        notifier=notifier,
    )
    return "confirmado"
