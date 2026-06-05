"""Servicio de Egresos (C2) — listar con filtros + total monetario, y alta auditada.

Reglas (con I/O; corre SIEMPRE con `app.current_org` ya fijado por el llamador,
RLS es la barrera real, no `WHERE org_id`):
- **listar**: filtros `sucursal_id` / `categoria` (match exacto de `categoria_gasto`)
  / `desde` / `hasta`, todos combinables. Devuelve `(items, total, total_monto)`:
  - `total` = conteo de filas que matchean el filtro,
  - `total_monto` = **SUM(monto) sobre TODO el filtro** (no solo la página),
  - `items` = la página (orden `fecha` desc, luego `created_at` desc).
- **crear**: `registrado_por` = usuario del token (no del body, auditoría RNF-03);
  resuelve la sucursal (null si el egreso es a nivel org). RLS garantiza que una
  `sucursal_id` de otra org no exista en el contexto.
- **resumen** (opcional): SUM(monto) agrupado por `categoria_gasto`, respeta el
  rango de fechas, ordenado por total desc.

No se salta el contexto de tenant.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from app.models.egreso import Egreso
from app.models.sucursal import Sucursal
from app.models.usuario import Usuario
from app.schemas.egreso import (
    EgresoCreate,
    EgresoItem,
    ResumenCategoria,
    SucursalRefEgreso,
)


def _base_filtrado(
    *,
    sucursal_id: uuid.UUID | None,
    categoria: str | None,
    desde: date | None,
    hasta: date | None,
) -> Select[tuple[Egreso]]:
    """Construye el SELECT de `egreso` aplicando los filtros (combinables).

    Centraliza el `WHERE` para que el conteo, la suma y la página usen EXACTAMENTE
    el mismo filtro (así `total_monto` corresponde a `total`, no a la página).
    """
    stmt = select(Egreso)
    if sucursal_id is not None:
        stmt = stmt.where(Egreso.sucursal_id == sucursal_id)
    if categoria:
        stmt = stmt.where(Egreso.categoria_gasto == categoria)
    if desde is not None:
        stmt = stmt.where(Egreso.fecha >= desde)
    if hasta is not None:
        stmt = stmt.where(Egreso.fecha <= hasta)
    return stmt


def _to_item(
    egreso: Egreso,
    *,
    sucursales: dict[uuid.UUID, Sucursal],
    nombres_usuario: dict[uuid.UUID, str],
) -> EgresoItem:
    """Mapea un `Egreso` a `EgresoItem`, resolviendo sucursal/usuario precargados."""
    suc = sucursales.get(egreso.sucursal_id) if egreso.sucursal_id is not None else None
    nombre = (
        nombres_usuario.get(egreso.registrado_por) if egreso.registrado_por is not None else None
    )
    return EgresoItem(
        id=egreso.id,
        fecha=egreso.fecha,
        categoria_gasto=egreso.categoria_gasto,
        monto=egreso.monto,
        sucursal=SucursalRefEgreso(id=suc.id, nombre=suc.nombre) if suc else None,
        descripcion=egreso.descripcion,
        registrado_por_nombre=nombre,
    )


def listar(
    db: Session,
    *,
    sucursal_id: uuid.UUID | None = None,
    categoria: str | None = None,
    desde: date | None = None,
    hasta: date | None = None,
    page: int = 1,
    page_size: int = 20,
) -> tuple[list[EgresoItem], int, Decimal]:
    """Lista egresos con filtros + total monetario del filtro (C2).

    Devuelve `(items, total, total_monto)` donde `total` es el conteo de filas que
    matchean y `total_monto` la SUM(monto) sobre TODO el filtro (no solo la página).
    """
    base = _base_filtrado(sucursal_id=sucursal_id, categoria=categoria, desde=desde, hasta=hasta)

    # total (conteo) y total_monto (SUM) sobre TODO el filtro, no la página.
    # Ambos agregan sobre el MISMO subquery `sub`. La SUM debe usar `sub.c.monto`
    # (la columna del subquery), NO `Egreso.monto`: referenciar la tabla mientras
    # se hace FROM del subquery genera un producto cartesiano egreso×subquery que
    # multiplicaría la suma por el nº de filas.
    sub = base.subquery()
    total = db.execute(select(func.count()).select_from(sub)).scalar_one()
    total_monto: Decimal = db.execute(select(func.coalesce(func.sum(sub.c.monto), 0))).scalar_one()

    egresos = list(
        db.execute(
            base.order_by(Egreso.fecha.desc(), Egreso.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        .scalars()
        .all()
    )

    # Precarga sucursales + nombres de usuario referenciados (evita N+1).
    suc_ids = {e.sucursal_id for e in egresos if e.sucursal_id is not None}
    sucursales: dict[uuid.UUID, Sucursal] = (
        {
            s.id: s
            for s in db.execute(select(Sucursal).where(Sucursal.id.in_(suc_ids))).scalars().all()
        }
        if suc_ids
        else {}
    )
    user_ids = {e.registrado_por for e in egresos if e.registrado_por is not None}
    nombres_usuario: dict[uuid.UUID, str] = (
        {
            u.id: u.nombre
            for u in db.execute(select(Usuario).where(Usuario.id.in_(user_ids))).scalars().all()
        }
        if user_ids
        else {}
    )

    items = [_to_item(e, sucursales=sucursales, nombres_usuario=nombres_usuario) for e in egresos]
    return items, int(total), Decimal(total_monto)


def crear(
    db: Session, data: EgresoCreate, *, org_id: uuid.UUID, usuario_id: uuid.UUID
) -> EgresoItem:
    """Registra un egreso con `registrado_por` = usuario del token (C2, RNF-03).

    `data` ya viene validado por Pydantic (monto > 0, categoría no vacía). La
    `sucursal_id`, si viene, debe existir en el contexto (RLS): si no existe, el
    item devuelto tendrá `sucursal: null` (la FK con ON DELETE SET NULL no rompe).
    Devuelve el egreso creado con la sucursal resuelta.
    """
    egreso = Egreso(
        org_id=org_id,
        sucursal_id=data.sucursal_id,
        categoria_gasto=data.categoria_gasto,
        monto=data.monto,
        fecha=data.fecha,
        descripcion=data.descripcion,
        registrado_por=usuario_id,
    )
    db.add(egreso)
    db.flush()

    suc = (
        db.execute(select(Sucursal).where(Sucursal.id == data.sucursal_id)).scalar_one_or_none()
        if data.sucursal_id is not None
        else None
    )
    usuario = db.execute(select(Usuario).where(Usuario.id == usuario_id)).scalar_one_or_none()

    return EgresoItem(
        id=egreso.id,
        fecha=egreso.fecha,
        categoria_gasto=egreso.categoria_gasto,
        monto=egreso.monto,
        sucursal=SucursalRefEgreso(id=suc.id, nombre=suc.nombre) if suc else None,
        descripcion=egreso.descripcion,
        registrado_por_nombre=usuario.nombre if usuario else None,
    )


def resumen(
    db: Session,
    *,
    desde: date | None = None,
    hasta: date | None = None,
) -> list[ResumenCategoria]:
    """Gasto agrupado por `categoria_gasto` (C2, opcional). Respeta rango y RLS."""
    stmt = select(Egreso.categoria_gasto, func.coalesce(func.sum(Egreso.monto), 0))
    if desde is not None:
        stmt = stmt.where(Egreso.fecha >= desde)
    if hasta is not None:
        stmt = stmt.where(Egreso.fecha <= hasta)
    stmt = stmt.group_by(Egreso.categoria_gasto).order_by(
        func.coalesce(func.sum(Egreso.monto), 0).desc()
    )
    rows = db.execute(stmt).all()
    return [
        ResumenCategoria(categoria_gasto=categoria, total=Decimal(total))
        for (categoria, total) in rows
    ]
