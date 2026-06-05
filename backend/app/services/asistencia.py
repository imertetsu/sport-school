"""Servicio de Asistencia (C2) — roster, guardado idempotente, historial, scoping.

Reglas de dominio (con I/O; corre SIEMPRE con `app.current_org` ya fijado por el
llamador, RLS):
- **Scoping por rol** (igual criterio que ficha médica, C5): ADMIN ve todas las
  categorías de la org; ENTRENADOR solo las de sus `sucursal_ids` (del token).
  Si un ENTRENADOR pide una categoría fuera de sus sucursales → `CategoriaFuera`
  (el router lo traduce a 403). Categoría inexistente → `CategoriaNoEncontrada`
  (404).
- **get-or-create roster**: NO crea sesión hasta guardar. Si no hay sesión para
  (categoria, fecha), `sesion_id=null` y `estado=null` por alumno.
- **guardar idempotente**: crea la sesión si no existe (por categoria+fecha+hora,
  garantizado por `UNIQUE(categoria_id, fecha, hora)`) y hace **upsert** de
  `asistencia` por `(sesion_id, alumno_id)` con `registrado_por=<user>` y
  `updated_at` refrescado. Re-guardar no duplica filas (UNIQUE).
- **historial**: sesiones de una categoría con contadores presentes/ausentes.

No se salta el contexto de tenant (RLS es la barrera real).
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.alumno import Alumno
from app.models.asistencia import Asistencia
from app.models.categoria import Categoria
from app.models.sesion import Sesion


class AsistenciaError(Exception):
    """Error base de negocio del módulo de asistencia."""


class CategoriaNoEncontrada(AsistenciaError):
    """La categoría no existe (en la org del contexto) -> 404."""


class CategoriaFuera(AsistenciaError):
    """La categoría está fuera del alcance del rol (sucursal) -> 403."""


def nombre_completo(a: Alumno) -> str:
    """Nombre completo del alumno (apellidos + nombres), sin huecos."""
    partes = [a.ap_paterno, a.ap_materno, a.nombres]
    return " ".join(p for p in partes if p).strip() or a.nombres


# --------------------------------------------------------------------------- #
# Scoping por rol
# --------------------------------------------------------------------------- #
def _sucursales_permitidas(role: str, sucursal_ids: list[str]) -> set[uuid.UUID] | None:
    """Conjunto de sucursales que el rol puede ver, o `None` si ve todas (ADMIN).

    ENTRENADOR queda limitado a sus `sucursal_ids` del token (igual que la ficha
    médica, C5). Cualquier otro rol no-ADMIN: sin sucursales permitidas.
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


def listar_categorias(
    db: Session, *, role: str, sucursal_ids: list[str]
) -> list[tuple[Categoria, int]]:
    """Categorías visibles por rol con su `total_alumnos` (C2).

    ADMIN: todas las de la org (RLS); ENTRENADOR: solo las de sus sucursales.
    Devuelve `[(Categoria, total_alumnos)]` ordenado por nombre.
    """
    permitidas = _sucursales_permitidas(role, sucursal_ids)

    stmt = (
        select(Categoria, func.count(Alumno.id))
        .outerjoin(Alumno, Alumno.categoria_id == Categoria.id)
        .group_by(Categoria.id)
        .order_by(Categoria.nombre)
    )
    if permitidas is not None:
        if not permitidas:
            return []
        stmt = stmt.where(Categoria.sucursal_id.in_(permitidas))

    rows = db.execute(stmt).all()
    return [(cat, int(total)) for (cat, total) in rows]


def _cargar_categoria_con_scope(
    db: Session, *, categoria_id: uuid.UUID, role: str, sucursal_ids: list[str]
) -> Categoria:
    """Carga la categoría aplicando el scoping por rol.

    404 si no existe (en la org del contexto); 403 si está fuera de las
    sucursales permitidas del entrenador.
    """
    cat = db.execute(
        select(Categoria).where(Categoria.id == categoria_id)
    ).scalar_one_or_none()
    if cat is None:
        raise CategoriaNoEncontrada("Categoría no encontrada")

    permitidas = _sucursales_permitidas(role, sucursal_ids)
    if permitidas is not None and cat.sucursal_id not in permitidas:
        raise CategoriaFuera("Categoría fuera del alcance del rol")
    return cat


# --------------------------------------------------------------------------- #
# Roster (get-or-create lógico: no crea sesión)
# --------------------------------------------------------------------------- #
def _buscar_sesion(
    db: Session, *, categoria_id: uuid.UUID, fecha: date, hora: time | None
) -> Sesion | None:
    """Busca la sesión por (categoria, fecha, hora). `hora` None = la del día."""
    stmt = select(Sesion).where(
        Sesion.categoria_id == categoria_id, Sesion.fecha == fecha
    )
    if hora is None:
        stmt = stmt.where(Sesion.hora.is_(None))
    else:
        stmt = stmt.where(Sesion.hora == hora)
    return db.execute(stmt).scalars().first()


def _alumnos_de_categoria(db: Session, categoria_id: uuid.UUID) -> list[Alumno]:
    return list(
        db.execute(
            select(Alumno)
            .where(Alumno.categoria_id == categoria_id)
            .order_by(Alumno.ap_paterno, Alumno.ap_materno, Alumno.nombres)
        )
        .scalars()
        .all()
    )


def obtener_roster(
    db: Session,
    *,
    categoria_id: uuid.UUID,
    fecha: date,
    role: str,
    sucursal_ids: list[str],
) -> tuple[Categoria, Sesion | None, list[Alumno], dict[uuid.UUID, str]]:
    """Devuelve datos crudos del roster (get-or-create lógico, NO crea sesión).

    Retorna `(categoria, sesion|None, alumnos, estados_por_alumno)`. Si no hay
    sesión para (categoria, fecha) -> `sesion=None` y el dict de estados vacío.
    """
    cat = _cargar_categoria_con_scope(
        db, categoria_id=categoria_id, role=role, sucursal_ids=sucursal_ids
    )
    alumnos = _alumnos_de_categoria(db, categoria_id)

    # Para el roster usamos la sesión "del día" (hora NULL es la canónica); si
    # existe alguna sesión ese día tomamos la primera por hora para reflejar lo
    # ya guardado.
    sesion = db.execute(
        select(Sesion)
        .where(Sesion.categoria_id == categoria_id, Sesion.fecha == fecha)
        .order_by(Sesion.hora.is_(None).desc(), Sesion.hora)
    ).scalars().first()

    estados: dict[uuid.UUID, str] = {}
    if sesion is not None:
        rows = db.execute(
            select(Asistencia.alumno_id, Asistencia.estado).where(
                Asistencia.sesion_id == sesion.id
            )
        ).all()
        for al_id, est in rows:
            estados[al_id] = est

    return cat, sesion, alumnos, estados


# --------------------------------------------------------------------------- #
# Guardar (idempotente: crea sesión si falta + upsert de marcas)
# --------------------------------------------------------------------------- #
def _get_or_create_sesion(
    db: Session,
    *,
    org_id: uuid.UUID,
    categoria_id: uuid.UUID,
    fecha: date,
    hora: time | None,
) -> Sesion:
    """Devuelve la sesión (categoria, fecha, hora), creándola si no existe.

    La idempotencia descansa en `UNIQUE(categoria_id, fecha, hora)`.
    """
    sesion = _buscar_sesion(db, categoria_id=categoria_id, fecha=fecha, hora=hora)
    if sesion is not None:
        return sesion
    sesion = Sesion(org_id=org_id, categoria_id=categoria_id, fecha=fecha, hora=hora)
    db.add(sesion)
    db.flush()
    return sesion


def guardar_asistencia(
    db: Session,
    *,
    org_id: uuid.UUID,
    categoria_id: uuid.UUID,
    fecha: date,
    hora: time | None,
    marcas: list[tuple[uuid.UUID, str]],
    registrado_por: uuid.UUID,
    role: str,
    sucursal_ids: list[str],
) -> tuple[Categoria, Sesion]:
    """Crea/recupera la sesión y hace upsert de las marcas (idempotente) (C2).

    Solo se aplican marcas de alumnos que pertenecen a la categoría (defensa en
    profundidad sobre los ids del body). `registrado_por`/`updated_at` quedan como
    auditoría (RNF-03). Devuelve `(categoria, sesion)`.
    """
    cat = _cargar_categoria_con_scope(
        db, categoria_id=categoria_id, role=role, sucursal_ids=sucursal_ids
    )

    sesion = _get_or_create_sesion(
        db, org_id=org_id, categoria_id=categoria_id, fecha=fecha, hora=hora
    )

    # Alumnos válidos de la categoría (ignora ids ajenos / de otra categoría).
    alumnos_validos = {
        a.id for a in _alumnos_de_categoria(db, categoria_id)
    }

    # Asistencias ya existentes para esta sesión (upsert por alumno_id).
    existentes = {
        a.alumno_id: a
        for a in db.execute(
            select(Asistencia).where(Asistencia.sesion_id == sesion.id)
        )
        .scalars()
        .all()
    }

    ahora = datetime.now(UTC)
    for alumno_id, estado in marcas:
        if alumno_id not in alumnos_validos:
            continue
        existente = existentes.get(alumno_id)
        if existente is None:
            db.add(
                Asistencia(
                    org_id=org_id,
                    sesion_id=sesion.id,
                    alumno_id=alumno_id,
                    estado=estado,
                    registrado_por=registrado_por,
                )
            )
        else:
            existente.estado = estado
            existente.registrado_por = registrado_por
            existente.updated_at = ahora
    db.flush()
    return cat, sesion


# --------------------------------------------------------------------------- #
# Historial (GET /asistencia/sesiones)
# --------------------------------------------------------------------------- #
def listar_sesiones(
    db: Session,
    *,
    categoria_id: uuid.UUID,
    role: str,
    sucursal_ids: list[str],
    page: int,
    page_size: int,
) -> tuple[list[tuple[Sesion, int, int, int]], int]:
    """Historial de sesiones de una categoría con contadores (C2).

    Aplica scoping por rol sobre la categoría (403/404). Devuelve
    `([(sesion, presentes, ausentes, total)], total_sesiones)`.
    """
    _cargar_categoria_con_scope(
        db, categoria_id=categoria_id, role=role, sucursal_ids=sucursal_ids
    )

    base = select(Sesion).where(Sesion.categoria_id == categoria_id)
    total = db.execute(select(func.count()).select_from(base.subquery())).scalar_one()

    sesiones = (
        db.execute(
            base.order_by(Sesion.fecha.desc(), Sesion.hora.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        .scalars()
        .all()
    )

    items: list[tuple[Sesion, int, int, int]] = []
    if sesiones:
        sesion_ids = [s.id for s in sesiones]
        conteos = db.execute(
            select(Asistencia.sesion_id, Asistencia.estado, func.count())
            .where(Asistencia.sesion_id.in_(sesion_ids))
            .group_by(Asistencia.sesion_id, Asistencia.estado)
        ).all()
        presentes_por: dict[uuid.UUID, int] = {}
        ausentes_por: dict[uuid.UUID, int] = {}
        for ses_id, estado, n in conteos:
            if estado == "PRESENTE":
                presentes_por[ses_id] = int(n)
            elif estado == "AUSENTE":
                ausentes_por[ses_id] = int(n)
        for s in sesiones:
            p = presentes_por.get(s.id, 0)
            a = ausentes_por.get(s.id, 0)
            items.append((s, p, a, p + a))

    return items, total


# --------------------------------------------------------------------------- #
# Helpers de presentación (lógica pura, sin I/O)
# --------------------------------------------------------------------------- #
def contar_resumen(estados: list[str | None]) -> tuple[int, int, int]:
    """Cuenta `(presentes, ausentes, total)` de una lista de estados.

    `total` es la cantidad de alumnos (filas), no solo los marcados — refleja el
    contador "Total" de la pantalla. Función pura (sin I/O), fácil de testear.
    """
    presentes = sum(1 for e in estados if e == "PRESENTE")
    ausentes = sum(1 for e in estados if e == "AUSENTE")
    return presentes, ausentes, len(estados)
