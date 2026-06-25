"""Router de la cola "Pagos por verificar" (C6, epic pagos-qr-comprobante).

El ADMIN revisa los comprobantes que los tutores enviaron por WhatsApp (pre-llenos por
OCR + identificación por teléfono) y confirma (1 clic) o rechaza. Confirmar reusa
`registrar_pago_efectivo` (idempotente, FIFO).

Endpoints ADMIN (Bearer + contexto de tenant, RLS):
  - `GET  /comprobantes/pendientes?estado=&page=&page_size=` → `ComprobantesPendientesPage`
  - `GET  /comprobantes/{id}/cuotas`   → `[CuotaElegible]` (cuotas con saldo del tutor)
  - `POST /comprobantes/{id}/confirmar` → `PagoOut`  (reusa `registrar_pago_efectivo`)
  - `POST /comprobantes/{id}/rechazar`  → `{id, estado:'RECHAZADO'}`

Endpoint binario (SIN Bearer, URL firmada HMAC stateless — el `<img>` del navegador no
manda `Authorization`; mismo mecanismo que el recibo PDF):
  - `GET /comprobantes/{org_id}/{comprobante_id}/{token}.img` → la captura del pago

Cada `ComprobantePendienteItem.imagen_url` es la URL FIRMADA de ese endpoint `.img`.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy import select, text
from sqlalchemy.orm import Session

# El router de cobranza arma el PagoOut enriquecido; reusamos su helper para devolver
# la MISMA forma que `POST /cobranza/pagos/efectivo` al confirmar (contrato consistente).
from app.api.v1.cobranza import _pago_out_enriquecido
from app.core.db import SessionLocal, get_db
from app.core.tenant import CurrentUser, require_role
from app.models.comprobante_pendiente import ComprobantePendiente
from app.models.tutor import Tutor
from app.schemas.cobranza import PagoOut
from app.schemas.comprobantes import (
    ComprobantePendienteItem,
    ComprobantesPendientesPage,
    ConfirmarComprobanteIn,
    CuotaElegible,
    RechazarComprobanteIn,
    RechazarComprobanteOut,
    TutorRef,
)
from app.services import comprobantes as comprobantes_svc
from app.services import imagen_token

router = APIRouter(prefix="/comprobantes", tags=["comprobantes"])

_NO_ENCONTRADO = HTTPException(
    status_code=status.HTTP_404_NOT_FOUND, detail="Comprobante no encontrado"
)


def _item(db: Session, org_id: uuid.UUID, c: ComprobantePendiente) -> ComprobantePendienteItem:
    """Enriquece una fila a `ComprobantePendienteItem` (tutor + cuota_sugerida + url)."""
    tutor_ref: TutorRef | None = None
    if c.tutor_id is not None:
        tutor = db.execute(select(Tutor).where(Tutor.id == c.tutor_id)).scalar_one_or_none()
        if tutor is not None:
            tutor_ref = TutorRef(id=tutor.id, nombres=tutor.nombres)

    cuota_sugerida: CuotaElegible | None = None
    if c.cuota_sugerida_id is not None:
        from app.models.cuota import Cuota
        from app.models.deportista import Deportista
        from app.models.inscripcion import Inscripcion

        row = db.execute(
            select(Cuota, Deportista)
            .join(Inscripcion, Inscripcion.id == Cuota.inscripcion_id)
            .join(Deportista, Deportista.id == Inscripcion.deportista_id)
            .where(Cuota.id == c.cuota_sugerida_id)
        ).first()
        if row is not None:
            cuota_sugerida = CuotaElegible(**comprobantes_svc.cuota_a_elegible(row[0], row[1]))

    return ComprobantePendienteItem(
        id=c.id,
        estado=c.estado,
        from_telefono=c.from_telefono,
        created_at=c.created_at,
        tutor=tutor_ref,
        cuota_sugerida=cuota_sugerida,
        monto_ocr=c.monto_ocr,
        transaccion_id_ocr=c.transaccion_id_ocr,
        fecha_ocr=c.fecha_ocr,
        imagen_url=imagen_token.url_comprobante(org_id, c.id),
    )


# --------------------------------------------------------------------------- #
# GET /comprobantes/pendientes
# --------------------------------------------------------------------------- #
@router.get("/pendientes", response_model=ComprobantesPendientesPage)
def listar_pendientes(
    estado: str = Query(default="PENDIENTE"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user: CurrentUser = Depends(require_role("ADMIN")),
    db: Session = Depends(get_db),
) -> ComprobantesPendientesPage:
    """Cola de comprobantes por `estado` (PENDIENTE por defecto), pre-llenos."""
    org_id = uuid.UUID(user.org_id)
    filas, total = comprobantes_svc.listar_pendientes(
        db, estado=estado, page=page, page_size=page_size
    )
    return ComprobantesPendientesPage(
        items=[_item(db, org_id, c) for c in filas],
        total=total,
        page=page,
        page_size=page_size,
    )


# --------------------------------------------------------------------------- #
# GET /comprobantes/{id}/cuotas
# --------------------------------------------------------------------------- #
@router.get("/{comprobante_id}/cuotas", response_model=list[CuotaElegible])
def cuotas_elegibles(
    comprobante_id: uuid.UUID,
    _user: CurrentUser = Depends(require_role("ADMIN")),
    db: Session = Depends(get_db),
) -> list[CuotaElegible]:
    """Cuotas con saldo del tutor del comprobante (FIFO); todas las de la org si "sin
    identificar" (teléfono no matcheó)."""
    try:
        rows = comprobantes_svc.cuotas_elegibles(db, comprobante_id=comprobante_id)
    except comprobantes_svc.ComprobanteError as exc:
        raise _NO_ENCONTRADO from exc
    return [CuotaElegible(**comprobantes_svc.cuota_a_elegible(c, d)) for c, d in rows]


# --------------------------------------------------------------------------- #
# POST /comprobantes/{id}/confirmar
# --------------------------------------------------------------------------- #
@router.post("/{comprobante_id}/confirmar", response_model=PagoOut)
def confirmar(
    comprobante_id: uuid.UUID,
    body: ConfirmarComprobanteIn,
    user: CurrentUser = Depends(require_role("ADMIN")),
    db: Session = Depends(get_db),
) -> PagoOut:
    """Confirma el comprobante: registra el pago (efectivo, FIFO) y marca CONFIRMADO.

    Reusa `registrar_pago_efectivo` (idempotente). Si el comprobante ya no está
    PENDIENTE ⇒ 409 (anti-doble-pago). Si la cuota no existe (otra org) ⇒ 404.
    """
    try:
        pago = comprobantes_svc.confirmar_comprobante(
            db,
            comprobante_id=comprobante_id,
            cuota_id=body.cuota_id,
            monto=body.monto,
            admin_id=uuid.UUID(user.user_id),
        )
    except comprobantes_svc.ComprobanteError as exc:
        msg = str(exc)
        if "no encontrad" in msg.lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=msg) from exc
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=msg) from exc
    return _pago_out_enriquecido(db, pago)


# --------------------------------------------------------------------------- #
# POST /comprobantes/{id}/rechazar
# --------------------------------------------------------------------------- #
@router.post("/{comprobante_id}/rechazar", response_model=RechazarComprobanteOut)
def rechazar(
    comprobante_id: uuid.UUID,
    body: RechazarComprobanteIn | None = None,
    user: CurrentUser = Depends(require_role("ADMIN")),
    db: Session = Depends(get_db),
) -> RechazarComprobanteOut:
    """Marca el comprobante RECHAZADO (con `motivo?`). Confirmado ⇒ 409."""
    motivo = body.motivo if body is not None else None
    try:
        comprobante = comprobantes_svc.rechazar_comprobante(
            db,
            comprobante_id=comprobante_id,
            admin_id=uuid.UUID(user.user_id),
            motivo=motivo,
        )
    except comprobantes_svc.ComprobanteError as exc:
        msg = str(exc)
        if "no encontrad" in msg.lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=msg) from exc
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=msg) from exc
    return RechazarComprobanteOut(id=comprobante.id, estado=comprobante.estado)


# --------------------------------------------------------------------------- #
# GET /comprobantes/{org_id}/{comprobante_id}/{token}.img  (binario, SIN Bearer)
# --------------------------------------------------------------------------- #
@router.get("/{org_id}/{comprobante_id}/{token}.img", response_class=Response)
def imagen_comprobante(org_id: uuid.UUID, comprobante_id: uuid.UUID, token: str) -> Response:
    """Captura del comprobante por URL firmada (sin Bearer). La consume el `<img>`.

    Valida el token HMAC ANTES de tocar la BD; fija `app.current_org` y lee bajo RLS.
    404 indistinguible si el token no valida o el comprobante no existe/otra org.
    """
    if not imagen_token.token_valido(imagen_token.KIND_COMPROBANTE, org_id, comprobante_id, token):
        raise _NO_ENCONTRADO

    db: Session = SessionLocal()
    try:
        db.execute(text("SELECT set_config('app.current_org', :o, true)"), {"o": str(org_id)})
        c = db.execute(
            select(ComprobantePendiente).where(ComprobantePendiente.id == comprobante_id)
        ).scalar_one_or_none()
        if c is None:
            raise _NO_ENCONTRADO
        imagen, mime = c.imagen, c.mime
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
    return Response(content=imagen, media_type=mime)
