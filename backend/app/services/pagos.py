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
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.domain.ports.invoice import ComprobanteData, ComprobanteService, CuotaLinea
from app.domain.ports.notification import NotificationService
from app.models.alumno import Alumno
from app.models.conciliacion_pendiente import ConciliacionPendiente
from app.models.cuota import Cuota
from app.models.inscripcion import Inscripcion
from app.models.organizacion import Organizacion
from app.models.pago import Pago
from app.models.pago_cuota import PagoCuota


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
    db: Session, *, pago: Pago, cuotas: list[Cuota], org_id: uuid.UUID
) -> None:
    """Aplica el pago a las cuotas (FIFO) vía `pago_cuota` y marca PAGADO.

    Idempotente: si ya existe la fila puente (pago_id, cuota_id), no la duplica.
    El `monto_aplicado` es el monto de cada cuota (multi-cuota = suma).
    """
    for cuota in cuotas:
        ya = db.execute(
            select(PagoCuota.id).where(PagoCuota.pago_id == pago.id, PagoCuota.cuota_id == cuota.id)
        ).first()
        if ya is None:
            db.add(
                PagoCuota(
                    org_id=org_id,
                    pago_id=pago.id,
                    cuota_id=cuota.id,
                    monto_aplicado=cuota.monto,
                )
            )
        cuota.estado = "PAGADO"
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
def _alumno_de_cuotas(db: Session, cuotas: list[Cuota]) -> Alumno | None:
    if not cuotas:
        return None
    insc = db.execute(
        select(Inscripcion).where(Inscripcion.id == cuotas[0].inscripcion_id)
    ).scalar_one_or_none()
    if insc is None:
        return None
    return db.execute(select(Alumno).where(Alumno.id == insc.alumno_id)).scalar_one_or_none()


def _nombre_completo(a: Alumno) -> str:
    partes = [a.ap_paterno, a.ap_materno, a.nombres]
    return " ".join(p for p in partes if p).strip() or a.nombres


def construir_comprobante_data(db: Session, *, pago: Pago, org: Organizacion) -> ComprobanteData:
    """Arma `ComprobanteData` (dominio) a partir del pago y sus cuotas."""
    cuotas = _cuotas_de_pago(db, pago.id)
    alumno = _alumno_de_cuotas(db, cuotas)
    lineas = [
        CuotaLinea(
            periodo_inicio=c.periodo_inicio.isoformat(),
            vence_el=c.vence_el.isoformat(),
            monto=c.monto,
        )
        for c in cuotas
    ]
    return ComprobanteData(
        numero=str(pago.id),
        org_nombre=org.nombre,
        moneda=org.moneda,
        alumno_nombre=_nombre_completo(alumno) if alumno else "—",
        metodo=pago.metodo,
        fecha=pago.pagado_en or datetime.now(UTC),
        monto_total=pago.monto,
        cuotas=lineas,
    )


def _confirmar_y_aplicar(
    db: Session,
    *,
    pago: Pago,
    cuotas: list[Cuota],
    org_id: uuid.UUID,
    comprobante: ComprobanteService | None,
    notifier: NotificationService | None,
) -> None:
    """Marca el pago CONFIRMADO, aplica FIFO, fija comprobante_url y notifica.

    Idempotente: si el pago ya está CONFIRMADO no reaplica ni renotifica.
    """
    if pago.estado == "CONFIRMADO":
        return

    pago.estado = "CONFIRMADO"
    if pago.pagado_en is None:
        pago.pagado_en = datetime.now(UTC)
    _aplicar_pago_a_cuotas(db, pago=pago, cuotas=cuotas, org_id=org_id)

    # comprobante_url apunta al endpoint que genera el PDF on-the-fly (C5).
    pago.comprobante_url = f"/api/v1/cobranza/comprobantes/{pago.id}.pdf"
    db.flush()

    if notifier is not None:
        notifier.send(
            to=str(pago.id),
            template="comprobante",
            variables={"pago_id": str(pago.id), "monto": str(pago.monto)},
        )


# --------------------------------------------------------------------------- #
# Efectivo
# --------------------------------------------------------------------------- #
def registrar_pago_efectivo(
    db: Session,
    *,
    org_id: uuid.UUID,
    cuota_ids: list[uuid.UUID],
    registrado_por: uuid.UUID,
    comprobante: ComprobanteService | None = None,
    notifier: NotificationService | None = None,
) -> Pago:
    """Crea un pago EFECTIVO CONFIRMADO y lo aplica (FIFO) (C3)."""
    cuotas = cargar_cuotas_fifo(db, cuota_ids)
    monto = sum((c.monto for c in cuotas), Decimal("0"))

    pago = Pago(
        org_id=org_id,
        metodo="EFECTIVO",
        estado="PENDIENTE",  # se confirma abajo (mismo flujo que QR/webhook)
        monto=monto,
        registrado_por=registrado_por,
        pagado_en=datetime.now(UTC),
    )
    db.add(pago)
    db.flush()

    _confirmar_y_aplicar(
        db,
        pago=pago,
        cuotas=cuotas,
        org_id=org_id,
        comprobante=comprobante,
        notifier=notifier,
    )
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
