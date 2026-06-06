"""Servicio de la consola de plataforma (Epic Super Admin).

Opera sobre tablas SIN RLS (`plataforma_admin`, `plataforma_auditoria`,
`organizacion`), por lo que NO necesita el GUC `app.current_org`. La ÚNICA
excepción es el INSERT del primer `Usuario` ADMIN al crear una escuela: `usuario`
tiene RLS, así que ANTES del INSERT se fija el GUC a la org recién creada (patrón
`seed.py`/`workers/tasks.py`/`services/pagos.py`), SIN BYPASSRLS sobre el rol
`latinosport_app`.

El aislamiento por escuela NO se debilita: el super admin nunca fija el GUC fuera
de este punto controlado (un único INSERT a la org que él mismo acaba de crear).

Estas funciones lanzan `HTTPException` para que el router las propague tal cual
(mismo estilo que `api/v1/auth.py`).
"""

from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.core.security import hash_password, verify_password
from app.models.organizacion import Organizacion
from app.models.plataforma_admin import PlataformaAdmin
from app.models.plataforma_auditoria import PlataformaAuditoria
from app.models.usuario import Usuario

# Acciones de auditoría (espejan el CHECK de la migración 0012).
ACCION_CREAR = "CREAR_ESCUELA"
ACCION_SUSPENDER = "SUSPENDER_ESCUELA"
ACCION_REACTIVAR = "REACTIVAR_ESCUELA"


def _audit(
    db: Session, *, admin_id: uuid.UUID, accion: str, org_id: uuid.UUID, detalle: str | None
) -> None:
    """Registra una entrada de auditoría de plataforma (tabla sin RLS)."""
    db.add(
        PlataformaAuditoria(
            admin_id=admin_id,
            accion=accion,
            org_id=org_id,
            detalle=detalle,
        )
    )
    db.flush()


# --------------------------------------------------------------------------- #
# Login de plataforma
# --------------------------------------------------------------------------- #
def login_plataforma(db: Session, *, email: str, password: str) -> PlataformaAdmin:
    """Valida credenciales contra `plataforma_admin` (sin RLS → sin GUC).

    401 si el email no existe, el admin está inactivo, o la clave no coincide.
    Devuelve el `PlataformaAdmin` para que el router emita el token.
    """
    invalid = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Credenciales inválidas",
    )
    admin = db.execute(
        select(PlataformaAdmin).where(PlataformaAdmin.email == email)
    ).scalar_one_or_none()
    if admin is None or not admin.activo:
        raise invalid
    if not verify_password(password, admin.password_hash):
        raise invalid
    return admin


# --------------------------------------------------------------------------- #
# Escuelas (organizaciones)
# --------------------------------------------------------------------------- #
def listar_escuelas(db: Session) -> list[Organizacion]:
    """Lista todas las escuelas (org sin RLS) ordenadas por creación desc."""
    return list(
        db.execute(select(Organizacion).order_by(Organizacion.created_at.desc())).scalars().all()
    )


def crear_escuela(
    db: Session,
    *,
    admin_id: uuid.UUID,
    nombre: str,
    pais: str | None,
    moneda: str | None,
    admin_nombre: str,
    admin_email: str,
    admin_password: str,
) -> tuple[Organizacion, Usuario]:
    """Crea una escuela (org ACTIVA) + su primer `Usuario` ADMIN.

    409 si `admin_email` ya existe (email es UNIQUE global en `usuario`). El INSERT
    del usuario se hace fijando el GUC a la org recién creada (la tabla `usuario`
    tiene RLS). Registra auditoría CREAR_ESCUELA. SIN BYPASSRLS.
    """
    # Pre-chequeo de email duplicado. `usuario` tiene RLS y aún no hay contexto, pero
    # `email` es UNIQUE GLOBAL: el INSERT fallaría por la constraint igualmente; este
    # chequeo da el 409 limpio. Se hace tras fijar el contexto de la nueva org (abajo).
    org = Organizacion(
        nombre=nombre,
        pais=pais or "BO",
        moneda=moneda or "BOB",
        estado="ACTIVA",
    )
    db.add(org)
    db.flush()  # asigna org.id

    # A partir de aquí insertamos en `usuario` (RLS): fijar el contexto a la org nueva.
    db.execute(
        text("SELECT set_config('app.current_org', :org, true)"),
        {"org": str(org.id)},
    )

    # 409 si el email ya existe en ALGUNA org. Con el contexto fijado a la org nueva
    # (recién creada, vacía) este SELECT no ve otros usuarios por RLS, así que se
    # consulta vía la función SECURITY DEFINER `login_lookup` (salta RLS, igual que
    # el login) para detectar el duplicado global ANTES de violar la UNIQUE.
    existe = db.execute(
        text("SELECT id FROM login_lookup(:email)"),
        {"email": admin_email},
    ).first()
    if existe is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="El email del administrador ya está en uso",
        )

    user = Usuario(
        org_id=org.id,
        email=admin_email,
        password_hash=hash_password(admin_password),
        role="ADMIN",
        nombre=admin_nombre,
        activo=True,
    )
    db.add(user)
    db.flush()

    _audit(
        db,
        admin_id=admin_id,
        accion=ACCION_CREAR,
        org_id=org.id,
        detalle=f"admin={admin_email}",
    )
    return org, user


def _get_org_or_404(db: Session, org_id: uuid.UUID) -> Organizacion:
    org = db.execute(select(Organizacion).where(Organizacion.id == org_id)).scalar_one_or_none()
    if org is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Escuela no encontrada",
        )
    return org


def suspender_escuela(db: Session, *, admin_id: uuid.UUID, org_id: uuid.UUID) -> Organizacion:
    """Marca la escuela como SUSPENDIDA (idempotente). 404 si no existe."""
    org = _get_org_or_404(db, org_id)
    if org.estado != "SUSPENDIDA":
        org.estado = "SUSPENDIDA"
        db.flush()
        _audit(db, admin_id=admin_id, accion=ACCION_SUSPENDER, org_id=org.id, detalle=None)
    return org


def reactivar_escuela(db: Session, *, admin_id: uuid.UUID, org_id: uuid.UUID) -> Organizacion:
    """Marca la escuela como ACTIVA (idempotente). 404 si no existe."""
    org = _get_org_or_404(db, org_id)
    if org.estado != "ACTIVA":
        org.estado = "ACTIVA"
        db.flush()
        _audit(db, admin_id=admin_id, accion=ACCION_REACTIVAR, org_id=org.id, detalle=None)
    return org


# --------------------------------------------------------------------------- #
# CRUD de super admins (tabla `plataforma_admin`, sin RLS)
# --------------------------------------------------------------------------- #
def listar_admins(db: Session) -> list[PlataformaAdmin]:
    """Lista todos los super admins (sin password_hash en la respuesta del router)."""
    return list(
        db.execute(select(PlataformaAdmin).order_by(PlataformaAdmin.created_at.desc()))
        .scalars()
        .all()
    )


def crear_admin(db: Session, *, nombre: str, email: str, password: str) -> PlataformaAdmin:
    """Crea un super admin. 409 si el email ya existe (UNIQUE)."""
    existe = db.execute(select(PlataformaAdmin.id).where(PlataformaAdmin.email == email)).first()
    if existe is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="El email ya está en uso",
        )
    admin = PlataformaAdmin(
        nombre=nombre,
        email=email,
        password_hash=hash_password(password),
        activo=True,
    )
    db.add(admin)
    db.flush()
    return admin


def _get_admin_or_404(db: Session, admin_id: uuid.UUID) -> PlataformaAdmin:
    admin = db.execute(
        select(PlataformaAdmin).where(PlataformaAdmin.id == admin_id)
    ).scalar_one_or_none()
    if admin is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Super admin no encontrado",
        )
    return admin


def activar_admin(db: Session, *, admin_id: uuid.UUID) -> PlataformaAdmin:
    """Activa un super admin (idempotente). 404 si no existe."""
    admin = _get_admin_or_404(db, admin_id)
    if not admin.activo:
        admin.activo = True
        db.flush()
    return admin


def desactivar_admin(db: Session, *, admin_id: uuid.UUID) -> PlataformaAdmin:
    """Desactiva un super admin (idempotente). 404 si no existe.

    Salvaguarda: nunca deja 0 super admins activos. Si el admin objetivo es el ÚLTIMO
    activo, 409 (siempre debe quedar ≥1 activo para poder operar la consola).
    """
    admin = _get_admin_or_404(db, admin_id)
    if not admin.activo:
        return admin  # ya inactivo → idempotente, no toca el conteo

    activos = db.execute(
        select(func.count()).select_from(PlataformaAdmin).where(PlataformaAdmin.activo.is_(True))
    ).scalar_one()
    if activos <= 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Debe quedar al menos un super admin activo",
        )

    admin.activo = False
    db.flush()
    return admin
