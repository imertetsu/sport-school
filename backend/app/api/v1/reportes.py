"""Router de Reportes (contrato C1). Bearer + contexto de tenant (RLS).

Endpoints (**solo ADMIN**; ENTRENADOR -> 403):
- GET /reportes/ingresos?anio=YYYY
- GET /reportes/asistencia?desde&hasta&sucursal_id&categoria_id

Ambos exigen `Depends(require_role("ADMIN"))`, que se encadena sobre
`set_tenant_context` (fija `app.current_org` en la transacción del request). Las
agregaciones son de **solo lectura** y corren bajo RLS — no se salta el contexto.

`response_model_by_alias=True` en /asistencia para que el campo `global_` salga
como `global` en el JSON (espejo de C1; `global` es reservado en Python).
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

from dateutil.relativedelta import relativedelta
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.tenant import CurrentUser, require_role
from app.schemas.reportes import AsistenciaReporte, IngresosReporte
from app.services import reportes as svc

router = APIRouter(prefix="/reportes", tags=["reportes"])


# --------------------------------------------------------------------------- #
# GET /reportes/ingresos
# --------------------------------------------------------------------------- #
@router.get("/ingresos", response_model=IngresosReporte)
def reporte_ingresos(
    anio: int | None = Query(default=None, ge=2000, le=2100),
    _user: CurrentUser = Depends(require_role("ADMIN")),
    db: Session = Depends(get_db),
) -> IngresosReporte:
    """Ingresos confirmados por mes del año (default: año actual) (C1)."""
    year = anio if anio is not None else datetime.now(UTC).year
    return svc.ingresos_por_mes(db, anio=year)


# --------------------------------------------------------------------------- #
# GET /reportes/asistencia
# --------------------------------------------------------------------------- #
@router.get("/asistencia", response_model=AsistenciaReporte, response_model_by_alias=True)
def reporte_asistencia(
    desde: date | None = Query(default=None),
    hasta: date | None = Query(default=None),
    sucursal_id: uuid.UUID | None = Query(default=None),
    categoria_id: uuid.UUID | None = Query(default=None),
    _user: CurrentUser = Depends(require_role("ADMIN")),
    db: Session = Depends(get_db),
) -> AsistenciaReporte:
    """Asistencia global + por categoría en el rango (default: últimos ~3 meses) (C1).

    `desde`/`hasta` se validan como `YYYY-MM-DD` (Pydantic -> 422 si el formato es
    inválido). Sin `hasta`: hoy; sin `desde`: hace ~3 meses.
    """
    hoy = datetime.now(UTC).date()
    f_hasta = hasta if hasta is not None else hoy
    f_desde = desde if desde is not None else (hoy - relativedelta(months=3))
    return svc.asistencia_reporte(
        db,
        desde=f_desde,
        hasta=f_hasta,
        sucursal_id=sucursal_id,
        categoria_id=categoria_id,
    )
