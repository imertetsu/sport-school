"""Router de la consola de PLATAFORMA (Epic Super Admin).

Identidad propia (`role="SUPERADMIN"`, sin `org_id`) para el operador de LATINOSPORT.
Todos los endpoints protegidos usan `Depends(require_superadmin)`, que valida el rol
y **NO** fija el GUC `app.current_org` → fail-closed sobre tablas tenant (RLS = 0
filas). Las tablas que toca (`plataforma_admin`, `plataforma_auditoria`,
`organizacion`) no tienen RLS, así que no necesitan contexto; el único INSERT con
contexto es el del primer usuario ADMIN al crear una escuela (en el service).

`POST /plataforma/login` no lleva auth (lee `plataforma_admin` directo, sin RLS).
NUNCA se serializa `password_hash`.
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.security import create_platform_token
from app.core.tenant import CurrentUser, require_superadmin
from app.schemas.plataforma import (
    AdminRef,
    CrearEscuelaIn,
    CrearEscuelaOut,
    CrearSuperAdminIn,
    EscuelaAdminRef,
    EscuelaEstadoOut,
    EscuelaItem,
    PlataformaLoginIn,
    PlataformaLoginOut,
    SuperAdminCreatedOut,
    SuperAdminEstadoOut,
    SuperAdminItem,
)
from app.services import plataforma as svc

router = APIRouter(prefix="/plataforma", tags=["plataforma"])


# --------------------------------------------------------------------------- #
# Login
# --------------------------------------------------------------------------- #
@router.post("/login", response_model=PlataformaLoginOut)
def login(body: PlataformaLoginIn, db: Session = Depends(get_db)) -> PlataformaLoginOut:
    """Autentica un super admin y emite un token SUPERADMIN (sin org_id). 401 si falla."""
    admin = svc.login_plataforma(db, email=body.email, password=body.password)
    token = create_platform_token(str(admin.id))
    return PlataformaLoginOut(
        access_token=token,
        admin=AdminRef(id=admin.id, nombre=admin.nombre, email=admin.email),
    )


# --------------------------------------------------------------------------- #
# Escuelas
# --------------------------------------------------------------------------- #
@router.get("/escuelas", response_model=list[EscuelaItem])
def listar_escuelas(
    _user: CurrentUser = Depends(require_superadmin),
    db: Session = Depends(get_db),
) -> list[EscuelaItem]:
    """Lista todas las escuelas con su estado (org no tiene RLS)."""
    return [EscuelaItem.model_validate(o) for o in svc.listar_escuelas(db)]


@router.post("/escuelas", response_model=CrearEscuelaOut, status_code=status.HTTP_201_CREATED)
def crear_escuela(
    body: CrearEscuelaIn,
    user: CurrentUser = Depends(require_superadmin),
    db: Session = Depends(get_db),
) -> CrearEscuelaOut:
    """Crea una escuela ACTIVA + su primer ADMIN. 409 si el email ya existe."""
    org, admin = svc.crear_escuela(
        db,
        admin_id=uuid.UUID(user.user_id),
        nombre=body.nombre,
        pais=body.pais,
        moneda=body.moneda,
        admin_nombre=body.admin_nombre,
        admin_email=body.admin_email,
        admin_password=body.admin_password,
    )
    return CrearEscuelaOut(
        id=org.id,
        nombre=org.nombre,
        estado=org.estado,
        admin=EscuelaAdminRef(id=admin.id, email=admin.email),
    )


@router.post("/escuelas/{org_id}/suspender", response_model=EscuelaEstadoOut)
def suspender_escuela(
    org_id: uuid.UUID,
    user: CurrentUser = Depends(require_superadmin),
    db: Session = Depends(get_db),
) -> EscuelaEstadoOut:
    """Suspende una escuela (idempotente). 404 si no existe."""
    org = svc.suspender_escuela(db, admin_id=uuid.UUID(user.user_id), org_id=org_id)
    return EscuelaEstadoOut(id=org.id, estado=org.estado)


@router.post("/escuelas/{org_id}/reactivar", response_model=EscuelaEstadoOut)
def reactivar_escuela(
    org_id: uuid.UUID,
    user: CurrentUser = Depends(require_superadmin),
    db: Session = Depends(get_db),
) -> EscuelaEstadoOut:
    """Reactiva una escuela (idempotente). 404 si no existe."""
    org = svc.reactivar_escuela(db, admin_id=uuid.UUID(user.user_id), org_id=org_id)
    return EscuelaEstadoOut(id=org.id, estado=org.estado)


# --------------------------------------------------------------------------- #
# Super admins
# --------------------------------------------------------------------------- #
@router.get("/admins", response_model=list[SuperAdminItem])
def listar_admins(
    _user: CurrentUser = Depends(require_superadmin),
    db: Session = Depends(get_db),
) -> list[SuperAdminItem]:
    """Lista los super admins (nunca expone password_hash)."""
    return [SuperAdminItem.model_validate(a) for a in svc.listar_admins(db)]


@router.post("/admins", response_model=SuperAdminCreatedOut, status_code=status.HTTP_201_CREATED)
def crear_admin(
    body: CrearSuperAdminIn,
    _user: CurrentUser = Depends(require_superadmin),
    db: Session = Depends(get_db),
) -> SuperAdminCreatedOut:
    """Crea un super admin. 409 si el email ya existe."""
    admin = svc.crear_admin(db, nombre=body.nombre, email=body.email, password=body.password)
    return SuperAdminCreatedOut(
        id=admin.id, nombre=admin.nombre, email=admin.email, activo=admin.activo
    )


@router.post("/admins/{admin_id}/activar", response_model=SuperAdminEstadoOut)
def activar_admin(
    admin_id: uuid.UUID,
    _user: CurrentUser = Depends(require_superadmin),
    db: Session = Depends(get_db),
) -> SuperAdminEstadoOut:
    """Activa un super admin (idempotente). 404 si no existe."""
    admin = svc.activar_admin(db, admin_id=admin_id)
    return SuperAdminEstadoOut(id=admin.id, activo=admin.activo)


@router.post("/admins/{admin_id}/desactivar", response_model=SuperAdminEstadoOut)
def desactivar_admin(
    admin_id: uuid.UUID,
    _user: CurrentUser = Depends(require_superadmin),
    db: Session = Depends(get_db),
) -> SuperAdminEstadoOut:
    """Desactiva un super admin (idempotente). 404 si no existe; 409 si dejaría 0 activos."""
    admin = svc.desactivar_admin(db, admin_id=admin_id)
    return SuperAdminEstadoOut(id=admin.id, activo=admin.activo)
