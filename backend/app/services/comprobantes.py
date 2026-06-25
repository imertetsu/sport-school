"""Servicio de comprobantes "Pagos por verificar" (epic pagos-qr-comprobante, Fase 3).

Conciliación **asistida-manual** (OpenBCB fuera): el tutor responde al número de la
escuela con la captura del pago; el sidecar la reenvía al backend, que:

  1. **procesar_comprobante_inbound** — guarda el comprobante (bytea), corre OCR
     best-effort, e identifica al tutor por su teléfono → su cuota pendiente más
     antigua (FIFO) como sugerencia. **Nunca pierde el pago** (RNF-06): sin match de
     teléfono o sin OCR la fila se crea igual (estado PENDIENTE).
  2. **confirmar_comprobante** — el ADMIN confirma en 1 clic: reusa
     `registrar_pago_efectivo` (efectivo, idempotente, FIFO) y marca CONFIRMADO.
  3. **rechazar_comprobante** — marca RECHAZADO con `motivo?`.

**Invariante anti-fuga (gotcha del repo):** `procesar_comprobante_inbound` corre desde
el webhook entrante (que hoy solo logueaba y NO fijaba contexto). Al pasar a ESCRIBIR
BD DEBE fijar `app.current_org` (`set_config(..., true)` + `set_current_org_id`) dentro
de la MISMA tx, igual que `procesar_webhook` en `pagos.py`. Sin esto, la inserción del
comprobante fugaría/fallaría RLS.

**Idempotencia (RNF-05):**
  - mismo `message_id` (re-entrega del sidecar) ⇒ 1 fila (chequeo + UNIQUE).
  - confirmar 2x ⇒ 1 pago (la guarda `estado != PENDIENTE` corta el 2º).
  - mismo `transaccion_id_ocr` ⇒ bloqueado por el UNIQUE parcial; lo capturamos al
    insertar y guardamos con `transaccion_id_ocr=None` + nota (no se pierde el pago).

Capa de servicios (`app.services`): puede usar SQLAlchemy y otros servicios; el dominio
NO la importa (import-linter).
"""

from __future__ import annotations

import base64
import logging
import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.org_context import set_current_org_id
from app.core.phone import normalize_bo_phone
from app.models.comprobante_pendiente import ComprobantePendiente
from app.models.cuota import Cuota
from app.models.deportista import Deportista
from app.models.deportista_tutor import DeportistaTutor
from app.models.inscripcion import Inscripcion
from app.models.pago import Pago
from app.models.tutor import Tutor
from app.services import ocr
from app.services import pagos as pagos_svc

logger = logging.getLogger(__name__)

# Estados de cuota con saldo pendiente (elegibles para imputar el comprobante, FIFO).
_ESTADOS_CON_SALDO = ("PENDIENTE", "PARCIAL", "VENCIDO")


class ComprobanteError(Exception):
    """Error de negocio al confirmar/rechazar (lo traduce el router a HTTP)."""


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _nombre_completo(a: Deportista) -> str:
    partes = [a.ap_paterno, a.ap_materno, a.nombres]
    return " ".join(p for p in partes if p).strip() or a.nombres


def _set_org_context(db: Session, org_id: str) -> None:
    """Fija `app.current_org` (GUC + ContextVar) en la tx — invariante anti-fuga.

    Idéntico a `procesar_webhook` en pagos.py: el GUC para RLS en BD + el ContextVar
    en-proceso (lo lee el adaptador de WhatsApp si hubiera envío). `SET LOCAL` (3er arg
    `true`): vive solo dentro de esta transacción.
    """
    db.execute(text("SELECT set_config('app.current_org', :o, true)"), {"o": org_id})
    set_current_org_id(org_id)


def _tutor_por_telefono(db: Session, telefono_norm: str) -> Tutor | None:
    """Tutor de la org (RLS) cuyo teléfono normaliza al mismo E.164 que `telefono_norm`.

    Compara NORMALIZADO: los tutores guardan el teléfono "humano" (`+591 7...`, guiones)
    y el remitente llega en E.164. Se normalizan ambos lados con `normalize_bo_phone`.
    """
    tutores = db.execute(select(Tutor).where(Tutor.telefono.is_not(None))).scalars().all()
    for tutor in tutores:
        if normalize_bo_phone(tutor.telefono) == telefono_norm:
            return tutor
    return None


def _cuotas_con_saldo_de_tutor(db: Session, tutor_id: uuid.UUID) -> list[tuple[Cuota, Deportista]]:
    """Cuotas con saldo de los deportistas del tutor, FIFO (vence_el asc).

    tutor → deportista_tutor → deportista → inscripcion → cuota (estados con saldo).
    Ordenadas por `vence_el` asc (la más antigua primero) y `periodo_inicio` como
    desempate. RLS limita todo a la org del contexto.
    """
    rows = db.execute(
        select(Cuota, Deportista)
        .join(Inscripcion, Inscripcion.id == Cuota.inscripcion_id)
        .join(Deportista, Deportista.id == Inscripcion.deportista_id)
        .join(DeportistaTutor, DeportistaTutor.deportista_id == Deportista.id)
        .where(
            DeportistaTutor.tutor_id == tutor_id,
            Cuota.estado.in_(_ESTADOS_CON_SALDO),
            (Cuota.monto - Cuota.monto_pagado) > 0,
        )
        .order_by(Cuota.vence_el.asc(), Cuota.periodo_inicio.asc())
    ).all()
    return [(c, d) for (c, d) in rows]


# --------------------------------------------------------------------------- #
# 1) Procesar comprobante entrante (desde el webhook del sidecar)
# --------------------------------------------------------------------------- #
def procesar_comprobante_inbound(
    db: Session,
    *,
    org_id: str,
    from_telefono: str,
    media_b64: str,
    mime: str,
    caption: str | None,
    message_id: str | None,
) -> ComprobantePendiente | None:
    """Guarda un comprobante entrante (idempotente, anti-fuga). Devuelve la fila.

    Pasos:
      1. **Fija el contexto org** en la tx (RLS) — invariante anti-fuga.
      2. **Idempotencia por `message_id`**: si ya existe una fila con ese `message_id`,
         devuelve la existente sin reinsertar (re-entrega del sidecar).
      3. Normaliza el teléfono; busca tutor por teléfono → cuota FIFO sugerida.
      4. OCR best-effort de la imagen (monto / nº transacción / fecha; `None` si falla).
      5. Inserta la fila (PENDIENTE, imagen=bytes, mime, caption, OCR, sugerencias).
         Si el `transaccion_id_ocr` choca con el UNIQUE parcial (ya usado por otro
         comprobante), reintenta con `transaccion_id_ocr=None` + nota (RNF-06: no se
         pierde el comprobante).

    Devuelve `None` solo si la imagen no se pudo decodificar (media corrupta): no hay
    nada que guardar; el webhook ACK 200 igual (no rompe el sidecar).
    """
    _set_org_context(db, org_id)

    # 2) Idempotencia por message_id (re-entrega del sidecar) ⇒ no reinsertar.
    if message_id:
        existente = db.execute(
            select(ComprobantePendiente).where(ComprobantePendiente.message_id == message_id)
        ).scalar_one_or_none()
        if existente is not None:
            logger.info("comprobante message_id=%s ya existe; idempotente", message_id)
            return existente

    # Decodifica la imagen. Media corrupta ⇒ no hay nada que guardar (best-effort).
    try:
        imagen = base64.b64decode(media_b64)
    except Exception:  # noqa: BLE001 - media inválida: ACK igual, no rompemos el sidecar.
        logger.warning("comprobante con media_b64 no decodificable; se descarta esta entrega")
        return None
    if not imagen:
        return None

    # 3) Match por teléfono → tutor → cuota FIFO sugerida.
    telefono_norm = normalize_bo_phone(from_telefono) or from_telefono
    tutor = _tutor_por_telefono(db, telefono_norm) if telefono_norm else None
    cuota_sugerida_id: uuid.UUID | None = None
    if tutor is not None:
        cuotas = _cuotas_con_saldo_de_tutor(db, tutor.id)
        if cuotas:
            cuota_sugerida_id = cuotas[0][0].id  # la más antigua (FIFO)

    # 4) OCR best-effort (nunca lanza).
    campos = ocr.extraer_campos(imagen)

    # 5) Inserta. Reintento si choca el UNIQUE parcial de transaccion_id_ocr.
    return _insertar_comprobante(
        db,
        org_id=org_id,
        from_telefono=telefono_norm,
        message_id=message_id,
        imagen=imagen,
        mime=mime,
        caption=caption,
        tutor_id=tutor.id if tutor is not None else None,
        cuota_sugerida_id=cuota_sugerida_id,
        campos=campos,
    )


def _insertar_comprobante(
    db: Session,
    *,
    org_id: str,
    from_telefono: str,
    message_id: str | None,
    imagen: bytes,
    mime: str,
    caption: str | None,
    tutor_id: uuid.UUID | None,
    cuota_sugerida_id: uuid.UUID | None,
    campos: dict,
) -> ComprobantePendiente:
    """Inserta la fila; si el `transaccion_id_ocr` choca, reintenta sin él (RNF-06).

    El UNIQUE parcial `(transaccion_id_ocr) WHERE NOT NULL` evita que el MISMO nº de
    transacción se registre dos veces (anti-fraude). Si choca, NO descartamos el
    comprobante: hacemos savepoint, lo guardamos con `transaccion_id_ocr=None` y una
    nota en el caption para que el ADMIN lo vea ("transacción ya registrada").
    """
    transaccion_id_ocr = campos.get("transaccion_id")

    fila = ComprobantePendiente(
        org_id=uuid.UUID(org_id),
        estado="PENDIENTE",
        from_telefono=from_telefono,
        message_id=message_id,
        imagen=imagen,
        mime=mime,
        caption=caption,
        tutor_id=tutor_id,
        cuota_sugerida_id=cuota_sugerida_id,
        monto_ocr=campos.get("monto"),
        transaccion_id_ocr=transaccion_id_ocr,
        fecha_ocr=campos.get("fecha"),
        ocr_texto_crudo=campos.get("texto_crudo") or None,
    )

    # Savepoint: si el flush viola el UNIQUE parcial, lo deshacemos y reintentamos sin
    # el transaccion_id_ocr (no se pierde el comprobante).
    nested = db.begin_nested()
    try:
        db.add(fila)
        db.flush()
        nested.commit()
        return fila
    except IntegrityError:
        nested.rollback()

    nota = "[transacción OCR ya registrada en otro comprobante; revisar]"
    caption_con_nota = f"{caption} {nota}".strip() if caption else nota
    logger.warning(
        "comprobante con transaccion_id_ocr=%s duplicado; se guarda sin él (RNF-06)",
        transaccion_id_ocr,
    )
    fila_retry = ComprobantePendiente(
        org_id=uuid.UUID(org_id),
        estado="PENDIENTE",
        from_telefono=from_telefono,
        message_id=message_id,
        imagen=imagen,
        mime=mime,
        caption=caption_con_nota,
        tutor_id=tutor_id,
        cuota_sugerida_id=cuota_sugerida_id,
        monto_ocr=campos.get("monto"),
        transaccion_id_ocr=None,
        fecha_ocr=campos.get("fecha"),
        ocr_texto_crudo=campos.get("texto_crudo") or None,
    )
    db.add(fila_retry)
    db.flush()
    return fila_retry


# --------------------------------------------------------------------------- #
# 2) Confirmar (reusa registrar_pago_efectivo, idempotente)
# --------------------------------------------------------------------------- #
def confirmar_comprobante(
    db: Session,
    *,
    comprobante_id: uuid.UUID,
    cuota_id: uuid.UUID,
    monto: Decimal,
    admin_id: uuid.UUID,
) -> Pago:
    """Confirma el comprobante: registra el pago (efectivo) y marca CONFIRMADO.

    - Valida que el comprobante esté PENDIENTE. Si ya está CONFIRMADO/RECHAZADO ⇒
      `ComprobanteError` (el router lo traduce a 409): idempotencia anti-doble-pago.
    - Reusa `registrar_pago_efectivo` (NO abre un 2º camino de pago; idempotente, FIFO).
    - Marca el comprobante CONFIRMADO con `pago_id`, `resuelto_por`, `resuelto_en`.

    Corre bajo el `app.current_org` ya fijado por el router (RLS). El comprobante,
    la cuota y el admin son de la org del token.
    """
    comprobante = db.execute(
        select(ComprobantePendiente).where(ComprobantePendiente.id == comprobante_id)
    ).scalar_one_or_none()
    if comprobante is None:
        raise ComprobanteError("Comprobante no encontrado")
    if comprobante.estado != "PENDIENTE":
        raise ComprobanteError(f"El comprobante ya está {comprobante.estado}")

    try:
        pago = pagos_svc.registrar_pago_efectivo(
            db,
            org_id=comprobante.org_id,
            cuota_ids=[cuota_id],
            registrado_por=admin_id,
            monto_recibido=monto,
        )
    except pagos_svc.PagoError as exc:
        raise ComprobanteError(str(exc)) from exc

    comprobante.estado = "CONFIRMADO"
    comprobante.pago_id = pago.id
    comprobante.resuelto_por = admin_id
    comprobante.resuelto_en = datetime.now(UTC)
    db.flush()
    return pago


# --------------------------------------------------------------------------- #
# 3) Rechazar
# --------------------------------------------------------------------------- #
def rechazar_comprobante(
    db: Session,
    *,
    comprobante_id: uuid.UUID,
    admin_id: uuid.UUID,
    motivo: str | None = None,
) -> ComprobantePendiente:
    """Marca el comprobante RECHAZADO (auditando quién/cuándo y, opcional, el motivo).

    Idempotente: si ya está RECHAZADO devuelve la fila sin cambios. Si está CONFIRMADO
    ⇒ `ComprobanteError` (no se rechaza un pago ya registrado).
    """
    comprobante = db.execute(
        select(ComprobantePendiente).where(ComprobantePendiente.id == comprobante_id)
    ).scalar_one_or_none()
    if comprobante is None:
        raise ComprobanteError("Comprobante no encontrado")
    if comprobante.estado == "CONFIRMADO":
        raise ComprobanteError("El comprobante ya fue confirmado; no se puede rechazar")
    if comprobante.estado == "RECHAZADO":
        return comprobante

    comprobante.estado = "RECHAZADO"
    comprobante.resuelto_por = admin_id
    comprobante.resuelto_en = datetime.now(UTC)
    if motivo:
        nota = f"[rechazado: {motivo}]"
        comprobante.caption = (
            f"{comprobante.caption} {nota}".strip() if comprobante.caption else nota
        )
    db.flush()
    return comprobante


# --------------------------------------------------------------------------- #
# 4) Listados
# --------------------------------------------------------------------------- #
def listar_pendientes(
    db: Session,
    *,
    estado: str,
    page: int,
    page_size: int,
) -> tuple[list[ComprobantePendiente], int]:
    """Página de comprobantes por `estado` (más recientes primero). Devuelve (items, total).

    RLS limita a la org del contexto. El enriquecimiento (tutor/cuota_sugerida/url) lo
    hace el router con los helpers públicos de abajo.
    """
    base = select(ComprobantePendiente).where(ComprobantePendiente.estado == estado)
    total = db.execute(select(func.count()).select_from(base.subquery())).scalar_one()
    items = (
        db.execute(
            base.order_by(ComprobantePendiente.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        .scalars()
        .all()
    )
    return list(items), int(total)


def cuotas_elegibles(
    db: Session,
    *,
    comprobante_id: uuid.UUID,
) -> list[tuple[Cuota, Deportista]]:
    """Cuotas con saldo del tutor identificado del comprobante, FIFO.

    Si el comprobante NO tiene tutor identificado, devuelve lista vacía: el router (o
    una variante) puede ofrecer cualquier cuota con saldo de la escuela. Aquí nos
    ceñimos al tutor del comprobante (caso identificado).
    """
    comprobante = db.execute(
        select(ComprobantePendiente).where(ComprobantePendiente.id == comprobante_id)
    ).scalar_one_or_none()
    if comprobante is None:
        raise ComprobanteError("Comprobante no encontrado")
    if comprobante.tutor_id is None:
        return _cuotas_con_saldo_de_org(db)
    return _cuotas_con_saldo_de_tutor(db, comprobante.tutor_id)


def _cuotas_con_saldo_de_org(db: Session) -> list[tuple[Cuota, Deportista]]:
    """Todas las cuotas con saldo de la org (RLS), FIFO — para "sin identificar".

    Un comprobante sin tutor (teléfono no matcheó) se puede imputar a CUALQUIER cuota
    con saldo de la escuela (decisión de producto). Limitamos a 100 para no devolver un
    desplegable gigante.
    """
    rows = db.execute(
        select(Cuota, Deportista)
        .join(Inscripcion, Inscripcion.id == Cuota.inscripcion_id)
        .join(Deportista, Deportista.id == Inscripcion.deportista_id)
        .where(
            Cuota.estado.in_(_ESTADOS_CON_SALDO),
            (Cuota.monto - Cuota.monto_pagado) > 0,
        )
        .order_by(Cuota.vence_el.asc(), Cuota.periodo_inicio.asc())
        .limit(100)
    ).all()
    return [(c, d) for (c, d) in rows]


def cuota_a_elegible(cuota: Cuota, deportista: Deportista) -> dict:
    """Forma `CuotaElegible`/`cuota_sugerida` a partir de una cuota + su deportista."""
    return {
        "cuota_id": cuota.id,
        "deportista_nombre": _nombre_completo(deportista),
        "vence_el": cuota.vence_el,
        "saldo": cuota.monto - cuota.monto_pagado,
        "estado": cuota.estado,
    }
