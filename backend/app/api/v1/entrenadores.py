"""Router de Entrenadores (epic B). Bearer + contexto de tenant (RLS).

Endpoints:
- GET  /entrenadores              -> lista (cualquier rol autenticado; pobla selectores)
- POST /entrenadores              -> alta usuario(ENTRENADOR)+perfil (SOLO ADMIN), 201
- PUT  /entrenadores/{id}         -> editar/baja/reactivar (SOLO ADMIN)

El GET fija `app.current_org` vía `Depends(set_tenant_context)` y devuelve solo los
entrenadores de la org del usuario (RLS). La escritura exige
`Depends(require_role("ADMIN"))` (ENTRENADOR -> 403). Email ya en uso -> 409 (el
servicio caza el `IntegrityError` global del GOTCHA de RLS); inexistente -> 404.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.engine import Row
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.tenant import CurrentUser, require_role, set_tenant_context
from app.models.entrenador import Entrenador
from app.models.usuario import Usuario
from app.schemas.disciplina import DisciplinaRef
from app.schemas.entrenador import (
    EntrenadorCreate,
    EntrenadorOut,
    EntrenadorUpdate,
    RecordatorioDeudoresResult,
    RecordatorioDeudoresSucursalOut,
)
from app.services import entrenador as svc
from app.services import recordatorio_deudores as deudores_svc
from app.services.deps import get_whatsapp_port

router = APIRouter(prefix="/entrenadores", tags=["entrenadores"])


def _to_out(
    row: Row[tuple[Entrenador, Usuario]],
    sucursal_ids: list[uuid.UUID] | None = None,
    disciplinas: list[DisciplinaRef] | None = None,
) -> EntrenadorOut:
    """Mapea una fila `(Entrenador, Usuario)` del join a `EntrenadorOut`.

    `sucursal_ids` y `disciplinas` (refs al catálogo, {id,nombre}) se pasan ya
    resueltos (query agregada, sin N+1) por el caller.
    """
    entrenador, usuario = row
    return EntrenadorOut(
        id=entrenador.id,
        usuario_id=entrenador.usuario_id,
        nombres=entrenador.nombres,
        email=usuario.email,
        ci=entrenador.ci,
        especialidad=entrenador.especialidad,
        telefono=entrenador.telefono,
        disciplinas=disciplinas or [],
        activo=usuario.activo,
        sucursal_ids=sucursal_ids or [],
    )


# --------------------------------------------------------------------------- #
# GET /entrenadores  (cualquier rol autenticado)
# --------------------------------------------------------------------------- #
@router.get("", response_model=list[EntrenadorOut])
def listar_entrenadores(
    solo_activos: bool = Query(default=False),
    _user: CurrentUser = Depends(set_tenant_context),
    db: Session = Depends(get_db),
) -> list[EntrenadorOut]:
    """Lista los entrenadores de la org (RLS), orden por nombres. Pobla selectores.

    `?solo_activos=true` excluye los dados de baja (`usuario.activo=false`).
    """
    filas = svc.listar(db, solo_activos=solo_activos)
    ids = [row[0].id for row in filas]
    # Dos queries agregadas (evitan N+1) para poblar `sucursal_ids` y `disciplinas`.
    mapa_suc = svc.sucursal_ids_por_entrenador(db, ids)
    mapa_disc = svc.disciplinas_por_entrenador(db, ids)
    return [
        _to_out(row, mapa_suc.get(row[0].id, []), mapa_disc.get(row[0].id, [])) for row in filas
    ]


# --------------------------------------------------------------------------- #
# POST /entrenadores  (SOLO ADMIN)
# --------------------------------------------------------------------------- #
@router.post("", response_model=EntrenadorOut, status_code=status.HTTP_201_CREATED)
def crear_entrenador(
    body: EntrenadorCreate,
    user: CurrentUser = Depends(require_role("ADMIN")),
    db: Session = Depends(get_db),
) -> EntrenadorOut:
    """Crea `usuario`(ENTRENADOR, activo) + perfil en una transacción -> 201.

    Email ya en uso (en esta org **o** en otra, vía el GOTCHA de RLS) -> 409.
    CI ya en uso por otro entrenador de la org -> 409 (no se crea el login, D2).
    Disciplina inexistente/inactiva -> 404/422 (propagado por el servicio).
    """
    try:
        row = svc.crear(db, body, org_id=uuid.UUID(user.org_id))
    except svc.EmailEnUso as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except svc.CiEnUso as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _to_out(row, svc.sucursal_ids_de(db, row[0].id), svc.disciplina_refs_de(db, row[0].id))


# --------------------------------------------------------------------------- #
# PUT /entrenadores/{id}  (SOLO ADMIN)
# --------------------------------------------------------------------------- #
@router.put("/{entrenador_id}", response_model=EntrenadorOut)
def editar_entrenador(
    entrenador_id: uuid.UUID,
    body: EntrenadorUpdate,
    _user: CurrentUser = Depends(require_role("ADMIN")),
    db: Session = Depends(get_db),
) -> EntrenadorOut:
    """Edita nombres/ci/especialidad/telefono/disciplina_ids/activo/password (solo lo provisto).

    `activo=false` da de baja, `activo=true` reactiva. Inexistente -> 404. CI en uso por
    otro entrenador -> 409. Disciplina inexistente/inactiva -> 404/422.
    """
    try:
        row = svc.editar(db, entrenador_id, body)
    except svc.EntrenadorNoEncontrado as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except svc.EmailEnUso as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except svc.CiEnUso as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _to_out(row, svc.sucursal_ids_de(db, row[0].id), svc.disciplina_refs_de(db, row[0].id))


# --------------------------------------------------------------------------- #
# POST /entrenadores/{id}/recordatorio-deudores  (SOLO ADMIN, a demanda)
# --------------------------------------------------------------------------- #
@router.post(
    "/{entrenador_id}/recordatorio-deudores",
    response_model=RecordatorioDeudoresResult,
)
def enviar_recordatorio_deudores(
    entrenador_id: uuid.UUID,
    user: CurrentUser = Depends(require_role("ADMIN")),
    db: Session = Depends(get_db),
) -> RecordatorioDeudoresResult:
    """Envía a demanda el digest de deudores del entrenador (todas sus sucursales).

    `origen='MANUAL'`, período único por disparo (`MANUAL-<ts>`): no colisiona con el
    cron y permite reenvío intencional. 404 si el entrenador no existe en la org.
    Entrenador sin teléfono ⇒ **200** con todas las sucursales `estado='FALLIDO'`
    (estado de negocio, no error HTTP). Commitea la transacción (el servicio no).
    """
    entrenador = db.execute(
        select(Entrenador).where(Entrenador.id == entrenador_id)
    ).scalar_one_or_none()
    if entrenador is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Entrenador no encontrado"
        )

    periodo = "MANUAL-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    resultados = deudores_svc.enviar_digest_entrenador(
        db,
        org_id=uuid.UUID(user.org_id),
        entrenador=entrenador,
        periodo=periodo,
        origen="MANUAL",
        port=get_whatsapp_port(),
    )
    db.commit()

    return RecordatorioDeudoresResult(
        entrenador_id=entrenador_id,
        periodo=periodo,
        enviados=sum(1 for r in resultados if r.enviado_ahora),
        sucursales=[
            RecordatorioDeudoresSucursalOut(
                sucursal_id=r.sucursal_id,
                sucursal_nombre=r.sucursal_nombre,
                num_deudores=r.num_deudores,
                monto_total=r.monto_total,
                estado=r.estado,
            )
            for r in resultados
        ],
    )
