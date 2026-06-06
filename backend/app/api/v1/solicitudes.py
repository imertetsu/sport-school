"""Router de Auto-registro (contratos C2/C3) — versión EN SISTEMA.

TODO autenticado con contexto de tenant fijado (RLS). **NADA público**: no hay
`/registro/{token}` ni cliente sin auth.

Endpoints:
- POST /solicitudes                  -> captura (ADMIN o ENTRENADOR)
- GET  /solicitudes                  -> cola, scoped por rol (ADMIN todas;
                                        ENTRENADOR solo sus sucursales)
- GET  /solicitudes/{id}             -> detalle (scoped)
- POST /solicitudes/{id}/aprobar     -> solo ADMIN; crea el alumno real
- POST /solicitudes/{id}/rechazar    -> solo ADMIN

El gateo a solo-ADMIN (aprobar/rechazar) usa `require_role("ADMIN")` (se encadena
sobre `set_tenant_context`); la captura/cola usan `set_tenant_context` (ADMIN o
ENTRENADOR) y el servicio aplica el scoping por sucursal del entrenador.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.v1.alumnos import get_alumno
from app.core.db import get_db
from app.core.tenant import CurrentUser, require_role, set_tenant_context
from app.schemas.alumno import AlumnoDetailOut
from app.schemas.registro import (
    AprobarBody,
    RechazarBody,
    SolicitudCreate,
    SolicitudesPage,
    SolicitudOut,
)
from app.services import registro as svc

router = APIRouter(prefix="/solicitudes", tags=["solicitudes"])


def _http_error(exc: svc.RegistroError) -> HTTPException:
    """Traduce errores de negocio del servicio a HTTP (403/404/409)."""
    if isinstance(exc, svc.SucursalFuera):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    if isinstance(exc, svc.SolicitudYaResuelta):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))


# --------------------------------------------------------------------------- #
# POST /solicitudes  (captura: ADMIN o ENTRENADOR)
# --------------------------------------------------------------------------- #
@router.post("", response_model=SolicitudOut, status_code=status.HTTP_201_CREATED)
def crear_solicitud(
    body: SolicitudCreate,
    user: CurrentUser = Depends(set_tenant_context),
    db: Session = Depends(get_db),
) -> SolicitudOut:
    """Crea una solicitud PENDIENTE en la org del usuario (C2).

    La validación dura (consentimiento aceptado + tutor mínimo) la garantiza el
    schema (422). Entrenador con `sucursal_sugerida_id` fuera de su alcance -> 403.
    """
    try:
        solicitud = svc.crear(
            db,
            body,
            org_id=uuid.UUID(user.org_id),
            creado_por=uuid.UUID(user.user_id),
            role=user.role,
            sucursal_ids=user.sucursal_ids,
        )
    except svc.RegistroError as exc:
        raise _http_error(exc) from exc

    return svc.to_out(db, [solicitud])[0]


# --------------------------------------------------------------------------- #
# GET /solicitudes  (cola, scoped por rol)
# --------------------------------------------------------------------------- #
@router.get("", response_model=SolicitudesPage)
def listar_solicitudes(
    estado: str | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user: CurrentUser = Depends(set_tenant_context),
    db: Session = Depends(get_db),
) -> SolicitudesPage:
    """Cola de solicitudes scoped por rol (C3).

    ADMIN ve todas las de la org; ENTRENADOR solo las de sus sucursales sugeridas.
    Filtro opcional por `estado`.
    """
    rows, total = svc.listar(
        db,
        role=user.role,
        sucursal_ids=user.sucursal_ids,
        estado=estado,
        page=page,
        page_size=page_size,
    )
    return SolicitudesPage(items=svc.to_out(db, rows), total=total, page=page, page_size=page_size)


# --------------------------------------------------------------------------- #
# GET /solicitudes/{id}  (detalle, scoped)
# --------------------------------------------------------------------------- #
@router.get("/{solicitud_id}", response_model=SolicitudOut)
def get_solicitud(
    solicitud_id: uuid.UUID,
    user: CurrentUser = Depends(set_tenant_context),
    db: Session = Depends(get_db),
) -> SolicitudOut:
    """Detalle de una solicitud (C3). 404 si está fuera del alcance del entrenador."""
    try:
        solicitud = svc.obtener(db, solicitud_id, role=user.role, sucursal_ids=user.sucursal_ids)
    except svc.RegistroError as exc:
        raise _http_error(exc) from exc
    return svc.to_out(db, [solicitud])[0]


# --------------------------------------------------------------------------- #
# POST /solicitudes/{id}/aprobar  (solo ADMIN -> crea el alumno real)
# --------------------------------------------------------------------------- #
@router.post("/{solicitud_id}/aprobar", response_model=AlumnoDetailOut)
def aprobar_solicitud(
    solicitud_id: uuid.UUID,
    body: AprobarBody,
    user: CurrentUser = Depends(require_role("ADMIN")),
    db: Session = Depends(get_db),
) -> AlumnoDetailOut:
    """Aprueba la solicitud y crea el alumno real (C3, solo ADMIN).

    Reutiliza la creación de Alumnos. Marca APROBADA + `alumno_id`. 409 si la
    solicitud ya está resuelta. Devuelve el alumno creado.
    """
    try:
        alumno = svc.aprobar(
            db,
            solicitud_id,
            body,
            org_id=uuid.UUID(user.org_id),
            revisado_por=uuid.UUID(user.user_id),
        )
    except svc.RegistroError as exc:
        raise _http_error(exc) from exc
    return get_alumno(alumno_id=alumno.id, user=user, db=db)


# --------------------------------------------------------------------------- #
# POST /solicitudes/{id}/rechazar  (solo ADMIN)
# --------------------------------------------------------------------------- #
@router.post("/{solicitud_id}/rechazar", response_model=SolicitudOut)
def rechazar_solicitud(
    solicitud_id: uuid.UUID,
    body: RechazarBody,
    user: CurrentUser = Depends(require_role("ADMIN")),
    db: Session = Depends(get_db),
) -> SolicitudOut:
    """Rechaza la solicitud con motivo (C3, solo ADMIN). 409 si ya está resuelta."""
    try:
        solicitud = svc.rechazar(db, solicitud_id, body, revisado_por=uuid.UUID(user.user_id))
    except svc.RegistroError as exc:
        raise _http_error(exc) from exc
    return svc.to_out(db, [solicitud])[0]
