"""Router de Egresos (contrato C2). Bearer + contexto de tenant (RLS).

Endpoints (todos **SOLO ADMIN / financiero**; ENTRENADOR -> 403, sin token -> 401):
- GET    /egresos          -> listar con filtros + total monetario del filtro
- POST   /egresos          -> registrar (auditado: registrado_por = usuario del token)
- DELETE /egresos/{id}     -> borrar uno mal cargado (no hay edición)
- GET    /egresos/resumen  -> gasto por categoría (opcional)

Todos exigen rol vía `Depends(require_role("ADMIN"))`, que se encadena sobre
`set_tenant_context` (fija `app.current_org` en la transacción del request, RLS).
El literal del rol ADMIN es `"ADMIN"`, el mismo usado en cobranza, el seed y los
tests (`usuario.role`), confirmado contra `core/security.py`/`seed.py`/`cobranza.py`.
"""

from __future__ import annotations

import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.tenant import CurrentUser, require_role
from app.models.egreso import Egreso
from app.schemas.egreso import EgresoCreate, EgresoItem, EgresosPage, ResumenCategoria
from app.services import egreso as svc

router = APIRouter(prefix="/egresos", tags=["egresos"])


# --------------------------------------------------------------------------- #
# GET /egresos
# --------------------------------------------------------------------------- #
@router.get("", response_model=EgresosPage)
def listar_egresos(
    sucursal_id: uuid.UUID | None = Query(default=None),
    categoria: str | None = Query(default=None),
    desde: date | None = Query(default=None),
    hasta: date | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    _user: CurrentUser = Depends(require_role("ADMIN")),
    db: Session = Depends(get_db),
) -> EgresosPage:
    """Lista egresos de la org con filtros combinables + total monetario (C2).

    `total_monto` es la suma de TODOS los egresos que matchean el filtro (no solo
    la página); `total` es el conteo de filas que matchean.
    """
    items, total, total_monto = svc.listar(
        db,
        sucursal_id=sucursal_id,
        categoria=categoria,
        desde=desde,
        hasta=hasta,
        page=page,
        page_size=page_size,
    )
    return EgresosPage(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_monto=total_monto,
    )


# --------------------------------------------------------------------------- #
# POST /egresos
# --------------------------------------------------------------------------- #
@router.post("", response_model=EgresoItem)
def crear_egreso(
    body: EgresoCreate,
    user: CurrentUser = Depends(require_role("ADMIN")),
    db: Session = Depends(get_db),
) -> EgresoItem:
    """Registra un egreso; `registrado_por` = usuario del token (auditoría) (C2).

    El cuerpo se valida con Pydantic (monto > 0, categoría no vacía -> 422).
    Devuelve el egreso creado con la `sucursal` resuelta (o null si es a nivel org).
    """
    return svc.crear(
        db,
        body,
        org_id=uuid.UUID(user.org_id),
        usuario_id=uuid.UUID(user.user_id),
    )


# --------------------------------------------------------------------------- #
# DELETE /egresos/{egreso_id}
# --------------------------------------------------------------------------- #
@router.delete("/{egreso_id}", status_code=status.HTTP_204_NO_CONTENT)
def eliminar_egreso(
    egreso_id: uuid.UUID,
    _user: CurrentUser = Depends(require_role("ADMIN")),
    db: Session = Depends(get_db),
) -> Response:
    """Elimina un egreso mal cargado (admin).

    El alta de egresos no tiene edición: si se elige mal la sucursal (o la categoría,
    o el monto) el único arreglo era volver a cargarlo bien y quedarse con el
    equivocado adentro, inflando el total del mes y el desglose por sucursal del
    panel. Este borrado es la salida.

    Es un DELETE real, no un anulado con rastro como el de `pago`: un egreso no mueve
    saldos de nadie ni tiene comprobante emitido, así que no hay nada que reversar —
    solo una fila de caja que no debió existir. RLS limita el egreso al tenant; 404 si
    no existe.
    """
    egreso = db.execute(select(Egreso).where(Egreso.id == egreso_id)).scalar_one_or_none()
    if egreso is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Egreso no encontrado")

    db.delete(egreso)
    db.commit()  # `get_db` commitea tras la respuesta; aquí ya devolvemos 204
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --------------------------------------------------------------------------- #
# GET /egresos/resumen  (opcional)
# --------------------------------------------------------------------------- #
@router.get("/resumen", response_model=list[ResumenCategoria])
def resumen_egresos(
    desde: date | None = Query(default=None),
    hasta: date | None = Query(default=None),
    _user: CurrentUser = Depends(require_role("ADMIN")),
    db: Session = Depends(get_db),
) -> list[ResumenCategoria]:
    """Gasto agrupado por `categoria_gasto`, ordenado por total desc (C2)."""
    return svc.resumen(db, desde=desde, hasta=hasta)
