"""Servicio de Avisos (C2) — feed scoped por rol, alta/edición con invariante, soft-delete.

Reglas (con I/O; corre SIEMPRE con `app.current_org` ya fijado por el llamador,
RLS es la barrera real, no `WHERE org_id`):

- **feed scoped por rol** (C2):
  - ADMIN: todos los `activo` de la org; con `incluir_expirados=true` también los
    vencidos (`vigente_hasta < hoy`).
  - ENTRENADOR: `activo` **y no vencidos**, con `alcance=ORG` **o** (`SUCURSAL` y
    `sucursal_id ∈ sucursal_ids`) **o** (`CATEGORIA` cuya sucursal ∈ `sucursal_ids`).
  - Orden `publicado_en` desc. Paginado.
- **crear/editar**: valida la invariante C1 (422 vía `ValueError`); `creado_por` =
  usuario del token (auditoría RNF-03; en editar no se reescribe el autor original).
- **soft-delete**: `activo=false` (no borrado físico); el aviso desaparece del feed
  pero la fila persiste.

`expirado` y el filtro de alcance del entrenador son **funciones puras** (sin I/O)
para poder testearlos sin BD. No se salta el contexto de tenant.
"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import Select, func, or_, select
from sqlalchemy.orm import Session

from app.models.aviso import Aviso
from app.models.categoria import Categoria
from app.models.sucursal import Sucursal
from app.models.usuario import Usuario
from app.schemas.aviso import (
    AvisoCreate,
    AvisoOut,
    AvisosPage,
    AvisoUpdate,
    CategoriaRefAviso,
    SucursalRefAviso,
    validar_invariante,
)


class AvisoError(Exception):
    """Error base de negocio del módulo de avisos."""


class AvisoNoEncontrado(AvisoError):
    """El aviso no existe (activo, en la org del contexto) -> 404."""


# --------------------------------------------------------------------------- #
# Lógica pura (sin I/O) — testeable sin BD
# --------------------------------------------------------------------------- #
def es_expirado(vigente_hasta: date | None, hoy: date) -> bool:
    """`True` si el aviso ya venció (`vigente_hasta < hoy`); `False` si no caduca."""
    if vigente_hasta is None:
        return False
    return vigente_hasta < hoy


def _sucursales_permitidas(role: str, sucursal_ids: list[str]) -> set[uuid.UUID] | None:
    """Conjunto de sucursales que el rol puede ver, o `None` si ve todas (ADMIN).

    ENTRENADOR queda limitado a sus `sucursal_ids` del token (igual criterio que
    asistencia/ficha médica, C5). Cualquier otro rol no-ADMIN: sin sucursales.
    """
    if role == "ADMIN":
        return None
    permitidas: set[uuid.UUID] = set()
    for s in sucursal_ids:
        try:
            permitidas.add(uuid.UUID(s))
        except (ValueError, TypeError):
            continue
    return permitidas


def aviso_visible_para_entrenador(
    *,
    alcance: str,
    sucursal_id: uuid.UUID | None,
    categoria_sucursal_id: uuid.UUID | None,
    permitidas: set[uuid.UUID],
) -> bool:
    """`True` si un entrenador con `permitidas` puede ver el aviso (lógica pura).

    `categoria_sucursal_id` es la sucursal de la categoría del aviso (cuando
    `alcance=CATEGORIA`), o None. Espeja el filtro SQL del feed para poder testear
    la regla de alcance sin BD.
    """
    if alcance == "ORG":
        return True
    if alcance == "SUCURSAL":
        return sucursal_id is not None and sucursal_id in permitidas
    if alcance == "CATEGORIA":
        return categoria_sucursal_id is not None and categoria_sucursal_id in permitidas
    return False


# --------------------------------------------------------------------------- #
# Feed (GET /avisos) — scoped por rol
# --------------------------------------------------------------------------- #
def _base_feed(
    *,
    role: str,
    sucursal_ids: list[str],
    incluir_expirados: bool,
    hoy: date,
) -> Select[tuple[Aviso]]:
    """SELECT de `aviso` filtrado por rol/vigencia (centraliza el WHERE del feed).

    ADMIN: todos los activos (vencidos solo si `incluir_expirados`). ENTRENADOR:
    activos y NO vencidos, con el filtro de alcance (ORG / SUCURSAL∈permitidas /
    CATEGORIA cuya sucursal∈permitidas). Para CATEGORIA se resuelve la sucursal de
    la categoría con un outer join a `categoria` (bajo el mismo contexto RLS).
    """
    stmt = select(Aviso).where(Aviso.activo.is_(True))

    permitidas = _sucursales_permitidas(role, sucursal_ids)
    if permitidas is None:
        # ADMIN: no vencidos salvo que pida incluirlos.
        if not incluir_expirados:
            stmt = stmt.where(or_(Aviso.vigente_hasta.is_(None), Aviso.vigente_hasta >= hoy))
        return stmt

    # ENTRENADOR (o no-ADMIN): siempre solo no vencidos + filtro de alcance.
    stmt = stmt.where(or_(Aviso.vigente_hasta.is_(None), Aviso.vigente_hasta >= hoy))
    if not permitidas:
        # Sin sucursales: solo puede ver avisos de alcance ORG.
        return stmt.where(Aviso.alcance == "ORG")

    # CATEGORIA: el aviso es visible si la sucursal de SU categoría está permitida.
    cat = Categoria.__table__.alias("cat_alcance")
    stmt = stmt.outerjoin(cat, cat.c.id == Aviso.categoria_id)
    return stmt.where(
        or_(
            Aviso.alcance == "ORG",
            (Aviso.alcance == "SUCURSAL") & Aviso.sucursal_id.in_(permitidas),
            (Aviso.alcance == "CATEGORIA") & cat.c.sucursal_id.in_(permitidas),
        )
    )


def _to_out(
    aviso: Aviso,
    *,
    sucursales: dict[uuid.UUID, Sucursal],
    categorias: dict[uuid.UUID, Categoria],
    nombres_usuario: dict[uuid.UUID, str],
    hoy: date,
) -> AvisoOut:
    """Mapea un `Aviso` a `AvisoOut`, resolviendo refs precargadas (evita N+1)."""
    suc = sucursales.get(aviso.sucursal_id) if aviso.sucursal_id is not None else None
    cat = categorias.get(aviso.categoria_id) if aviso.categoria_id is not None else None
    nombre = nombres_usuario.get(aviso.creado_por) if aviso.creado_por is not None else None
    return AvisoOut(
        id=aviso.id,
        titulo=aviso.titulo,
        cuerpo=aviso.cuerpo,
        alcance=aviso.alcance,  # type: ignore[arg-type]
        sucursal=SucursalRefAviso(id=suc.id, nombre=suc.nombre) if suc else None,
        categoria=CategoriaRefAviso(id=cat.id, nombre=cat.nombre) if cat else None,
        publicado_en=aviso.publicado_en,
        vigente_hasta=aviso.vigente_hasta,
        creado_por_nombre=nombre,
        expirado=es_expirado(aviso.vigente_hasta, hoy),
    )


def feed(
    db: Session,
    *,
    role: str,
    sucursal_ids: list[str],
    incluir_expirados: bool = False,
    page: int = 1,
    page_size: int = 20,
    hoy: date | None = None,
) -> AvisosPage:
    """Feed de avisos scoped por rol, paginado y ordenado por `publicado_en` desc (C2).

    `incluir_expirados` solo aplica a ADMIN (el entrenador nunca ve vencidos).
    """
    if hoy is None:
        hoy = date.today()

    base = _base_feed(
        role=role,
        sucursal_ids=sucursal_ids,
        incluir_expirados=incluir_expirados,
        hoy=hoy,
    )

    total_count = int(
        db.execute(select(func.count()).select_from(base.subquery())).scalar_one()
    )

    avisos = list(
        db.execute(
            base.order_by(Aviso.publicado_en.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        .scalars()
        .all()
    )

    # Precarga refs (evita N+1).
    suc_ids = {a.sucursal_id for a in avisos if a.sucursal_id is not None}
    cat_ids = {a.categoria_id for a in avisos if a.categoria_id is not None}
    user_ids = {a.creado_por for a in avisos if a.creado_por is not None}

    sucursales: dict[uuid.UUID, Sucursal] = (
        {
            s.id: s
            for s in db.execute(select(Sucursal).where(Sucursal.id.in_(suc_ids))).scalars().all()
        }
        if suc_ids
        else {}
    )
    categorias: dict[uuid.UUID, Categoria] = (
        {
            c.id: c
            for c in db.execute(select(Categoria).where(Categoria.id.in_(cat_ids))).scalars().all()
        }
        if cat_ids
        else {}
    )
    nombres_usuario: dict[uuid.UUID, str] = (
        {
            u.id: u.nombre
            for u in db.execute(select(Usuario).where(Usuario.id.in_(user_ids))).scalars().all()
        }
        if user_ids
        else {}
    )

    items = [
        _to_out(
            a,
            sucursales=sucursales,
            categorias=categorias,
            nombres_usuario=nombres_usuario,
            hoy=hoy,
        )
        for a in avisos
    ]
    return AvisosPage(items=items, total=total_count, page=page, page_size=page_size)


# --------------------------------------------------------------------------- #
# Alta / edición (ADMIN) — valida la invariante C1
# --------------------------------------------------------------------------- #
def _out_de_aviso(db: Session, aviso: Aviso, *, hoy: date) -> AvisoOut:
    """Construye el `AvisoOut` de un único aviso resolviendo sus refs."""
    suc = (
        db.execute(select(Sucursal).where(Sucursal.id == aviso.sucursal_id)).scalar_one_or_none()
        if aviso.sucursal_id is not None
        else None
    )
    cat = (
        db.execute(select(Categoria).where(Categoria.id == aviso.categoria_id)).scalar_one_or_none()
        if aviso.categoria_id is not None
        else None
    )
    usuario = (
        db.execute(select(Usuario).where(Usuario.id == aviso.creado_por)).scalar_one_or_none()
        if aviso.creado_por is not None
        else None
    )
    return AvisoOut(
        id=aviso.id,
        titulo=aviso.titulo,
        cuerpo=aviso.cuerpo,
        alcance=aviso.alcance,  # type: ignore[arg-type]
        sucursal=SucursalRefAviso(id=suc.id, nombre=suc.nombre) if suc else None,
        categoria=CategoriaRefAviso(id=cat.id, nombre=cat.nombre) if cat else None,
        publicado_en=aviso.publicado_en,
        vigente_hasta=aviso.vigente_hasta,
        creado_por_nombre=usuario.nombre if usuario else None,
        expirado=es_expirado(aviso.vigente_hasta, hoy),
    )


def crear(
    db: Session,
    data: AvisoCreate,
    *,
    org_id: uuid.UUID,
    usuario_id: uuid.UUID,
    hoy: date | None = None,
) -> AvisoOut:
    """Publica un aviso con `creado_por` = usuario del token (C2, RNF-03).

    `data` ya viene validado por Pydantic (no vacíos + invariante). Se re-valida la
    invariante en el servicio (defensa en profundidad). Lanza `ValueError` => 422.
    """
    if hoy is None:
        hoy = date.today()
    validar_invariante(data.alcance, data.sucursal_id, data.categoria_id)

    aviso = Aviso(
        org_id=org_id,
        titulo=data.titulo,
        cuerpo=data.cuerpo,
        alcance=data.alcance,
        sucursal_id=data.sucursal_id,
        categoria_id=data.categoria_id,
        vigente_hasta=data.vigente_hasta,
        creado_por=usuario_id,
        activo=True,
    )
    db.add(aviso)
    db.flush()
    return _out_de_aviso(db, aviso, hoy=hoy)


def _cargar_aviso_activo(db: Session, aviso_id: uuid.UUID) -> Aviso:
    """Carga un aviso activo de la org del contexto. 404 si no existe / inactivo."""
    aviso = db.execute(
        select(Aviso).where(Aviso.id == aviso_id, Aviso.activo.is_(True))
    ).scalar_one_or_none()
    if aviso is None:
        raise AvisoNoEncontrado("Aviso no encontrado")
    return aviso


def editar(
    db: Session,
    aviso_id: uuid.UUID,
    data: AvisoUpdate,
    *,
    hoy: date | None = None,
) -> AvisoOut:
    """Edita un aviso activo (misma validación de invariante que el alta) (C2).

    No reescribe `creado_por` (se conserva el autor original). 404 si no existe.
    """
    if hoy is None:
        hoy = date.today()
    validar_invariante(data.alcance, data.sucursal_id, data.categoria_id)

    aviso = _cargar_aviso_activo(db, aviso_id)
    aviso.titulo = data.titulo
    aviso.cuerpo = data.cuerpo
    aviso.alcance = data.alcance
    aviso.sucursal_id = data.sucursal_id
    aviso.categoria_id = data.categoria_id
    aviso.vigente_hasta = data.vigente_hasta
    db.flush()
    return _out_de_aviso(db, aviso, hoy=hoy)


def eliminar(db: Session, aviso_id: uuid.UUID) -> None:
    """Soft-delete: marca `activo=false` (no borrado físico) (C2). 404 si no existe."""
    aviso = _cargar_aviso_activo(db, aviso_id)
    aviso.activo = False
    db.flush()
