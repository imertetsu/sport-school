"""Servicio del catálogo de disciplinas (epic Disciplinas, S2).

`disciplina` es una tabla **GLOBAL sin RLS** (como `plataforma_admin`/`organizacion`):
estas funciones operan SIN fijar el GUC `app.current_org`. El CRUD lo ejerce el
superadmin desde `/plataforma`; la escuela solo lee el catálogo activo.

Unicidad **case-insensitive**: la garantiza el índice funcional
`uq_disciplina_nombre_lower ON disciplina (lower(nombre))` (migración 0016). Aquí se
pre-chequea con `SELECT ... WHERE lower(nombre) = lower(:n)` para devolver un 409 limpio
ANTES de violar la constraint (mismo patrón que `crear_admin` en `services/plataforma.py`).

Estas funciones lanzan `HTTPException` para que el router las propague tal cual.
"""

from __future__ import annotations

import uuid

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.disciplina import Disciplina


def _colision_nombre(db: Session, *, nombre: str, excluir_id: uuid.UUID | None = None) -> bool:
    """True si ya existe una disciplina con el mismo `lower(nombre)` (otra fila)."""
    stmt = select(Disciplina.id).where(func.lower(Disciplina.nombre) == func.lower(nombre))
    if excluir_id is not None:
        stmt = stmt.where(Disciplina.id != excluir_id)
    return db.execute(stmt).first() is not None


def listar_disciplinas(db: Session, *, solo_activas: bool = False) -> list[Disciplina]:
    """Lista disciplinas ordenadas por nombre. `solo_activas` filtra `activo = true`.

    Tabla global sin RLS → no requiere GUC.
    """
    stmt = select(Disciplina)
    if solo_activas:
        stmt = stmt.where(Disciplina.activo.is_(True))
    stmt = stmt.order_by(Disciplina.nombre)
    return list(db.execute(stmt).scalars().all())


def crear_disciplina(db: Session, *, nombre: str) -> Disciplina:
    """Crea una disciplina ACTIVA. 409 si `lower(nombre)` ya existe (case-insensitive)."""
    nombre = nombre.strip()
    if _colision_nombre(db, nombre=nombre):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ya existe una disciplina con ese nombre",
        )
    disc = Disciplina(nombre=nombre, activo=True)
    db.add(disc)
    db.flush()
    return disc


def _get_disciplina_o_404(db: Session, disciplina_id: uuid.UUID) -> Disciplina:
    disc = db.execute(select(Disciplina).where(Disciplina.id == disciplina_id)).scalar_one_or_none()
    if disc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Disciplina no encontrada",
        )
    return disc


def actualizar_disciplina(
    db: Session,
    *,
    disciplina_id: uuid.UUID,
    nombre: str | None = None,
    activo: bool | None = None,
) -> Disciplina:
    """Renombra y/o (des)activa una disciplina. 404 si no existe; 409 si el nuevo
    nombre colisiona (case-insensitive) con OTRA disciplina.

    El retiro de una disciplina es soft-delete (`activo=False`), nunca hard delete.
    """
    disc = _get_disciplina_o_404(db, disciplina_id)
    if nombre is not None:
        nombre = nombre.strip()
        if _colision_nombre(db, nombre=nombre, excluir_id=disc.id):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Ya existe una disciplina con ese nombre",
            )
        disc.nombre = nombre
    if activo is not None:
        disc.activo = activo
    db.flush()
    return disc


def get_disciplina_activa_o_error(db: Session, disciplina_id: uuid.UUID) -> Disciplina:
    """Carga una disciplina exigiendo que exista y esté activa (para vincular categoría).

    404 si no existe; 422 si existe pero está inactiva (no se puede asignar al crear/
    editar una categoría). Tabla global sin RLS.
    """
    disc = db.execute(select(Disciplina).where(Disciplina.id == disciplina_id)).scalar_one_or_none()
    if disc is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Disciplina no encontrada",
        )
    if not disc.activo:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="La disciplina está inactiva",
        )
    return disc
