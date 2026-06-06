"""Router de Cobranza (contrato C4). Bearer + contexto de tenant (RLS).

Endpoints:
- POST /cobranza/generar            (admin) -> {creadas}
- GET  /cobranza/cuotas             (filtros + paginación)
- GET  /cobranza/panel              (KPIs + morosidad)
- POST /cobranza/pagos/efectivo     (admin) -> PagoOut
- POST /cobranza/pagos/qr           (admin) -> QrOut
- GET  /cobranza/pagos/{id}         (polling) -> PagoOut
- POST /cobranza/pagos/qr/{id}/simular-confirmacion  (admin, gate sandbox)
- GET  /cobranza/comprobantes/{pago_id}.pdf          (PDF on-the-fly)
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.db import get_db
from app.core.tenant import CurrentUser, require_role, set_tenant_context
from app.models.alumno import Alumno
from app.models.categoria import Categoria
from app.models.credito import Credito
from app.models.cuota import Cuota
from app.models.inscripcion import Inscripcion
from app.models.organizacion import Organizacion
from app.models.pago import Pago
from app.models.pago_cuota import PagoCuota
from app.models.sucursal import Sucursal
from app.schemas.cobranza import (
    AlumnoRef,
    AlumnosActivos,
    CategoriaNombre,
    CuotaAplicada,
    CuotaItem,
    CuotasAgg,
    CuotasPage,
    GenerarOut,
    IngresosMes,
    MorosidadItem,
    PagoEfectivoIn,
    PagoOut,
    PagoQrIn,
    PanelOut,
    QrOut,
    SucursalNombre,
)
from app.services import pagos as pagos_svc
from app.services.deps import (
    get_comprobante_service,
    get_notification_service,
    get_payment_provider,
)
from app.services.generacion import generar_cuotas_org

router = APIRouter(prefix="/cobranza", tags=["cobranza"])


def _nombre_completo(a: Alumno) -> str:
    partes = [a.ap_paterno, a.ap_materno, a.nombres]
    return " ".join(p for p in partes if p).strip() or a.nombres


# --------------------------------------------------------------------------- #
# POST /cobranza/generar
# --------------------------------------------------------------------------- #
@router.post("/generar", response_model=GenerarOut)
def generar(
    user: CurrentUser = Depends(require_role("ADMIN")),
    db: Session = Depends(get_db),
) -> GenerarOut:
    """Corre la generación idempotente de cuotas para la org (C4)."""
    creadas = generar_cuotas_org(db, org_id=uuid.UUID(user.org_id))
    return GenerarOut(creadas=creadas)


# --------------------------------------------------------------------------- #
# GET /cobranza/cuotas
# --------------------------------------------------------------------------- #
@router.get("/cuotas", response_model=CuotasPage)
def listar_cuotas(
    estado: str | None = Query(default=None),
    alumno_id: uuid.UUID | None = Query(default=None),
    sucursal_id: uuid.UUID | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    _user: CurrentUser = Depends(set_tenant_context),
    db: Session = Depends(get_db),
) -> CuotasPage:
    """Lista cuotas de la org con datos de alumno/sucursal/categoría (C4)."""
    base = (
        select(Cuota, Alumno, Sucursal, Categoria)
        .join(Inscripcion, Inscripcion.id == Cuota.inscripcion_id)
        .join(Alumno, Alumno.id == Inscripcion.alumno_id)
        .join(Sucursal, Sucursal.id == Alumno.sucursal_id)
        .outerjoin(Categoria, Categoria.id == Alumno.categoria_id)
    )
    if estado:
        base = base.where(Cuota.estado == estado)
    if alumno_id is not None:
        base = base.where(Alumno.id == alumno_id)
    if sucursal_id is not None:
        base = base.where(Alumno.sucursal_id == sucursal_id)

    total = db.execute(select(func.count()).select_from(base.subquery())).scalar_one()

    rows = db.execute(
        base.order_by(Cuota.vence_el.desc()).offset((page - 1) * page_size).limit(page_size)
    ).all()

    # Último método de pago por cuota (vía puente -> pago).
    cuota_ids = [c.id for (c, _a, _s, _cat) in rows]
    metodos: dict[uuid.UUID, str] = {}
    if cuota_ids:
        met_rows = db.execute(
            select(PagoCuota.cuota_id, Pago.metodo, Pago.created_at)
            .join(Pago, Pago.id == PagoCuota.pago_id)
            .where(PagoCuota.cuota_id.in_(cuota_ids))
            .order_by(Pago.created_at.desc())
        ).all()
        for cid, metodo, _created in met_rows:
            metodos.setdefault(cid, metodo)

    items: list[CuotaItem] = []
    for cuota, alumno, sucursal, categoria in rows:
        items.append(
            CuotaItem(
                id=cuota.id,
                alumno=AlumnoRef(id=alumno.id, nombre_completo=_nombre_completo(alumno)),
                sucursal=SucursalNombre(nombre=sucursal.nombre) if sucursal else None,
                categoria=CategoriaNombre(nombre=categoria.nombre) if categoria else None,
                periodo_inicio=cuota.periodo_inicio,
                vence_el=cuota.vence_el,
                monto=cuota.monto,
                monto_pagado=cuota.monto_pagado,
                saldo=cuota.monto - cuota.monto_pagado,
                estado=cuota.estado,
                ultimo_metodo=metodos.get(cuota.id),
            )
        )

    return CuotasPage(items=items, total=total, page=page, page_size=page_size)


# --------------------------------------------------------------------------- #
# GET /cobranza/panel
# --------------------------------------------------------------------------- #
@router.get("/panel", response_model=PanelOut)
def panel(
    _user: CurrentUser = Depends(set_tenant_context),
    db: Session = Depends(get_db),
) -> PanelOut:
    """KPIs + morosidad del Panel de cobranza (C4)."""
    hoy = datetime.now(UTC).date()
    inicio_mes = hoy.replace(day=1)

    # Ingresos del mes: pagos CONFIRMADO con pagado_en en el mes corriente.
    ingresos = db.execute(
        select(func.coalesce(func.sum(Pago.monto), 0)).where(
            Pago.estado == "CONFIRMADO",
            Pago.pagado_en >= datetime(inicio_mes.year, inicio_mes.month, 1, tzinfo=UTC),
        )
    ).scalar_one()

    # Alumnos activos: con inscripción ACTIVA. Sucursales/disciplinas distintas.
    activos = db.execute(
        select(func.count(func.distinct(Inscripcion.alumno_id))).where(
            Inscripcion.estado == "ACTIVA"
        )
    ).scalar_one()
    sucursales_count = db.execute(
        select(func.count(func.distinct(Alumno.sucursal_id)))
        .select_from(Inscripcion)
        .join(Alumno, Alumno.id == Inscripcion.alumno_id)
        .where(Inscripcion.estado == "ACTIVA")
    ).scalar_one()
    disciplinas_count = db.execute(
        select(func.count(func.distinct(Inscripcion.disciplina))).where(
            Inscripcion.estado == "ACTIVA", Inscripcion.disciplina.is_not(None)
        )
    ).scalar_one()

    # Cuotas pendientes / vencidas (count + SALDO, no monto nominal — abonos).
    # Saldo = monto - monto_pagado. PARCIAL cuenta como pendiente (saldo > 0).
    saldo_expr = Cuota.monto - Cuota.monto_pagado
    pend = db.execute(
        select(func.count(), func.coalesce(func.sum(saldo_expr), 0)).where(
            Cuota.estado.in_(("PENDIENTE", "PARCIAL"))
        )
    ).one()
    venc = db.execute(
        select(func.count(), func.coalesce(func.sum(saldo_expr), 0)).where(
            Cuota.estado == "VENCIDO"
        )
    ).one()

    # Crédito a favor: Σ saldos de crédito de la org (KPI nuevo, abonos).
    credito_total = db.execute(select(func.coalesce(func.sum(Credito.saldo), 0))).scalar_one()

    # Morosidad: por alumno, cuotas VENCIDO, con SALDO total adeudado (no monto
    # nominal) y días de mora (desde el vencimiento más antiguo).
    moros_rows = db.execute(
        select(
            Alumno.id,
            Alumno.ap_paterno,
            Alumno.ap_materno,
            Alumno.nombres,
            Categoria.nombre,
            func.sum(saldo_expr),
            func.min(Cuota.vence_el),
        )
        .join(Inscripcion, Inscripcion.id == Cuota.inscripcion_id)
        .join(Alumno, Alumno.id == Inscripcion.alumno_id)
        .outerjoin(Categoria, Categoria.id == Alumno.categoria_id)
        .where(Cuota.estado == "VENCIDO")
        .group_by(
            Alumno.id,
            Alumno.ap_paterno,
            Alumno.ap_materno,
            Alumno.nombres,
            Categoria.nombre,
        )
        .order_by(func.min(Cuota.vence_el).asc())
        .limit(50)
    ).all()

    morosidad: list[MorosidadItem] = []
    for al_id, ap_pat, ap_mat, nombres, cat_nombre, monto, vence_min in moros_rows:
        partes = [ap_pat, ap_mat, nombres]
        nombre = " ".join(p for p in partes if p).strip() or nombres
        dias = (hoy - vence_min).days if vence_min else 0
        morosidad.append(
            MorosidadItem(
                alumno_id=al_id,
                nombre_completo=nombre,
                categoria=cat_nombre,
                monto=monto,
                dias_mora=max(dias, 0),
            )
        )

    return PanelOut(
        ingresos_mes=IngresosMes(monto=ingresos),
        alumnos_activos=AlumnosActivos(
            count=activos, sucursales=sucursales_count, disciplinas=disciplinas_count
        ),
        cuotas_pendientes=CuotasAgg(count=pend[0], monto=pend[1]),
        cuotas_vencidas=CuotasAgg(count=venc[0], monto=venc[1]),
        morosidad=morosidad,
        credito_total=credito_total,
    )


# --------------------------------------------------------------------------- #
# POST /cobranza/pagos/efectivo
# --------------------------------------------------------------------------- #
@router.post("/pagos/efectivo", response_model=PagoOut)
def pagar_efectivo(
    body: PagoEfectivoIn,
    user: CurrentUser = Depends(require_role("ADMIN")),
    db: Session = Depends(get_db),
) -> PagoOut:
    """Registra un pago en efectivo y lo aplica FIFO con abonos parciales (RF-ABO).

    `monto_recibido` opcional (efectivo de caja); `None` ⇒ paga el total (Σ saldos).
    El servicio consume crédito previo, distribuye FIFO y deja el sobrepago como
    crédito. La respuesta enriquece con crédito aplicado/generado y el detalle por
    cuota (saldo restante + estado).
    """
    try:
        pago = pagos_svc.registrar_pago_efectivo(
            db,
            org_id=uuid.UUID(user.org_id),
            cuota_ids=body.cuota_ids,
            registrado_por=uuid.UUID(user.user_id),
            monto_recibido=body.monto_recibido,
            comprobante=get_comprobante_service(),
            notifier=get_notification_service(),
        )
    except pagos_svc.PagoError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _pago_out_enriquecido(db, pago)


def _pago_out_enriquecido(db: Session, pago: Pago) -> PagoOut:
    """`PagoOut` con detalle de abonos: cuotas_aplicadas + crédito generado."""
    filas = db.execute(
        select(
            PagoCuota.cuota_id,
            PagoCuota.monto_aplicado,
            Cuota.monto,
            Cuota.monto_pagado,
            Cuota.estado,
        )
        .join(Cuota, Cuota.id == PagoCuota.cuota_id)
        .where(PagoCuota.pago_id == pago.id)
    ).all()
    cuotas_aplicadas = [
        CuotaAplicada(
            cuota_id=cid,
            monto_aplicado=aplicado,
            saldo_restante=monto - monto_pagado,
            estado=estado,
        )
        for cid, aplicado, monto, monto_pagado, estado in filas
    ]

    credito_generado = Decimal("0")
    insc_row = db.execute(
        select(Cuota.inscripcion_id)
        .join(PagoCuota, PagoCuota.cuota_id == Cuota.id)
        .where(PagoCuota.pago_id == pago.id)
        .limit(1)
    ).first()
    if insc_row is not None:
        credito_generado = pagos_svc.saldo_credito_inscripcion(db, insc_row[0])

    return PagoOut(
        id=pago.id,
        estado=pago.estado,
        metodo=pago.metodo,
        monto=pago.monto,
        comprobante_url=pago.comprobante_url,
        numero_recibo=pago.numero_recibo,
        credito_aplicado=pago.credito_aplicado,
        credito_generado=credito_generado,
        cuotas_aplicadas=cuotas_aplicadas,
    )


# --------------------------------------------------------------------------- #
# POST /cobranza/pagos/qr
# --------------------------------------------------------------------------- #
@router.post("/pagos/qr", response_model=QrOut)
def pagar_qr(
    body: PagoQrIn,
    user: CurrentUser = Depends(require_role("ADMIN")),
    db: Session = Depends(get_db),
) -> QrOut:
    """Crea un cobro QR (PENDIENTE) y devuelve el QR + monto esperado (C3)."""
    org = db.execute(
        select(Organizacion).where(Organizacion.id == uuid.UUID(user.org_id))
    ).scalar_one_or_none()
    moneda = org.moneda if org else "BOB"

    provider = get_payment_provider()
    # Pre-cargamos cuotas para conocer el monto antes de generar el QR.
    try:
        cuotas = pagos_svc.cargar_cuotas_fifo(db, body.cuota_ids)
    except pagos_svc.PagoError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    monto = sum((c.monto for c in cuotas), start=Decimal("0"))

    charge = provider.create_qr_charge(reference="pending", amount=monto, currency=moneda)

    pago = pagos_svc.crear_pago_qr(
        db,
        org_id=uuid.UUID(user.org_id),
        cuota_ids=body.cuota_ids,
        qr_ref=charge.qr_ref,
    )
    return QrOut(
        pago_id=pago.id,
        estado=pago.estado,
        monto=pago.monto,
        qr_ref=charge.qr_ref,
        qr_payload=charge.payload,
        qr_png_data_url=charge.qr_png_data_url,
    )


# --------------------------------------------------------------------------- #
# GET /cobranza/pagos/{id}  (polling)
# --------------------------------------------------------------------------- #
@router.get("/pagos/{pago_id}", response_model=PagoOut)
def get_pago(
    pago_id: uuid.UUID,
    _user: CurrentUser = Depends(set_tenant_context),
    db: Session = Depends(get_db),
) -> PagoOut:
    """Estado de un pago (para polling del flujo QR) (C3)."""
    pago = db.execute(select(Pago).where(Pago.id == pago_id)).scalar_one_or_none()
    if pago is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pago no encontrado")
    return PagoOut.model_validate(pago)


# --------------------------------------------------------------------------- #
# POST /cobranza/pagos/qr/{id}/simular-confirmacion  (gate sandbox)
# --------------------------------------------------------------------------- #
@router.post("/pagos/qr/{pago_id}/simular-confirmacion", response_model=PagoOut)
def simular_confirmacion(
    pago_id: uuid.UUID,
    user: CurrentUser = Depends(require_role("ADMIN")),
    db: Session = Depends(get_db),
) -> PagoOut:
    """Simula la confirmación del QR (solo si OPENBCB_SANDBOX) reentrando al flujo
    del webhook con un transaccion_id generado (C3)."""
    if not settings.openbcb_sandbox:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Simulación deshabilitada (OPENBCB_SANDBOX=false)",
        )
    pago = db.execute(select(Pago).where(Pago.id == pago_id)).scalar_one_or_none()
    if pago is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pago no encontrado")
    if pago.metodo != "QR" or not pago.qr_ref:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="El pago no es un cobro QR pendiente",
        )

    pagos_svc.procesar_webhook(
        db,
        transaccion_id=f"sim_{uuid.uuid4().hex}",
        referencia=pago.qr_ref,
        monto=pago.monto,
        comprobante=get_comprobante_service(),
        notifier=get_notification_service(),
    )
    db.flush()
    pago = db.execute(select(Pago).where(Pago.id == pago_id)).scalar_one()
    return PagoOut.model_validate(pago)


# --------------------------------------------------------------------------- #
# GET /cobranza/comprobantes/{pago_id}.pdf
# --------------------------------------------------------------------------- #
@router.get("/comprobantes/{pago_id}.pdf")
def comprobante_pdf(
    pago_id: uuid.UUID,
    _user: CurrentUser = Depends(set_tenant_context),
    db: Session = Depends(get_db),
) -> Response:
    """Genera y descarga el comprobante PDF on-the-fly (C5)."""
    pago = db.execute(select(Pago).where(Pago.id == pago_id)).scalar_one_or_none()
    if pago is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pago no encontrado")
    if pago.estado != "CONFIRMADO":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="El pago no está confirmado; no hay comprobante",
        )
    org = db.execute(select(Organizacion).where(Organizacion.id == pago.org_id)).scalar_one()
    data = pagos_svc.construir_comprobante_data(db, pago=pago, org=org)
    pdf_bytes = get_comprobante_service().render_pdf(data)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="comprobante_{pago_id}.pdf"',
        },
    )
