"""Servicio de Asistencia (C2) — roster, guardado idempotente, historial, scoping.

Reglas de dominio (con I/O; corre SIEMPRE con `app.current_org` ya fijado por el
llamador, RLS):
- **Scoping por rol** (igual criterio que ficha médica, C5): ADMIN ve todas las
  categorías de la org; ENTRENADOR solo las de sus `sucursal_ids` (del token).
  Si un ENTRENADOR pide una categoría fuera de sus sucursales → `CategoriaFuera`
  (el router lo traduce a 403). Categoría inexistente → `CategoriaNoEncontrada`
  (404).
- **get-or-create roster**: NO crea sesión hasta guardar. Si no hay sesión para
  (categoria, fecha), `sesion_id=null` y `estado=null` por deportista.
- **guardar idempotente**: crea la sesión si no existe (por categoria+fecha+hora,
  garantizado por `UNIQUE(categoria_id, fecha, hora)`) y hace **upsert** de
  `asistencia` por `(sesion_id, deportista_id)` con `registrado_por=<user>` y
  `updated_at` refrescado. Re-guardar no duplica filas (UNIQUE).
- **historial**: sesiones de una categoría con contadores presentes/ausentes.

No se salta el contexto de tenant (RLS es la barrera real).
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models.asistencia import Asistencia
from app.models.categoria import Categoria
from app.models.deportista import Deportista
from app.models.sesion import Sesion


class AsistenciaError(Exception):
    """Error base de negocio del módulo de asistencia."""


class CategoriaNoEncontrada(AsistenciaError):
    """La categoría no existe (en la org del contexto) -> 404."""


class CategoriaFuera(AsistenciaError):
    """La categoría está fuera del alcance del rol (sucursal) -> 403."""


def nombre_completo(a: Deportista) -> str:
    """Nombre completo del deportista (apellidos + nombres), sin huecos."""
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
    db: Session,
    *,
    role: str,
    sucursal_ids: list[str],
    disciplina_ids: set[uuid.UUID] | None = None,
) -> list[tuple[Categoria, int]]:
    """Categorías visibles por rol con su `total_deportistas` (C2).

    ADMIN: todas las de la org (RLS); ENTRENADOR: solo las de sus sucursales **y** de
    las disciplinas que tiene asignadas. Devuelve `[(Categoria, total_deportistas)]`
    ordenado por nombre.

    `disciplina_ids` (red de seguridad): `None` = ve todas (ADMIN); set **vacío** = NO
    se filtra por disciplina (cae al comportamiento por sucursal); set con ids = solo
    categorías de esas disciplinas, pero las de disciplina **NULL siempre son visibles**
    (aditivo sobre el filtro de sucursal).
    """
    permitidas = _sucursales_permitidas(role, sucursal_ids)

    stmt = (
        select(Categoria, func.count(Deportista.id))
        .outerjoin(Deportista, Deportista.categoria_id == Categoria.id)
        .group_by(Categoria.id)
        .order_by(Categoria.nombre)
    )
    if permitidas is not None:
        if not permitidas:
            return []
        stmt = stmt.where(Categoria.sucursal_id.in_(permitidas))

    if disciplina_ids:  # no None y no vacío -> filtra; NULL siempre visible
        stmt = stmt.where(
            or_(Categoria.disciplina_id.is_(None), Categoria.disciplina_id.in_(disciplina_ids))
        )

    rows = db.execute(stmt).all()
    return [(cat, int(total)) for (cat, total) in rows]


def _cargar_categoria_con_scope(
    db: Session,
    *,
    categoria_id: uuid.UUID,
    role: str,
    sucursal_ids: list[str],
    disciplina_ids: set[uuid.UUID] | None = None,
) -> Categoria:
    """Carga la categoría aplicando el scoping por rol.

    404 si no existe (en la org del contexto); 403 (`CategoriaFuera`) si está fuera de
    las sucursales permitidas del entrenador. Red de seguridad por disciplina: 403 SOLO
    si `disciplina_ids` NO está vacío Y la categoría tiene una disciplina que no es del
    entrenador; categoría con disciplina NULL siempre pasa. `disciplina_ids` None =
    ADMIN (ve todas); set vacío = sin filtro de disciplina. Protege
    roster/guardar/sesiones, que pasan todos por aquí.
    """
    cat = db.execute(select(Categoria).where(Categoria.id == categoria_id)).scalar_one_or_none()
    if cat is None:
        raise CategoriaNoEncontrada("Categoría no encontrada")

    permitidas = _sucursales_permitidas(role, sucursal_ids)
    if permitidas is not None and cat.sucursal_id not in permitidas:
        raise CategoriaFuera("Categoría fuera del alcance del rol")
    if disciplina_ids and cat.disciplina_id is not None and cat.disciplina_id not in disciplina_ids:
        raise CategoriaFuera("Categoría fuera del alcance del rol")
    return cat


# --------------------------------------------------------------------------- #
# Roster (get-or-create lógico: no crea sesión)
# --------------------------------------------------------------------------- #
def _buscar_sesion(
    db: Session, *, categoria_id: uuid.UUID, fecha: date, hora: time | None
) -> Sesion | None:
    """Busca la sesión por (categoria, fecha, hora). `hora` None = la del día."""
    stmt = select(Sesion).where(Sesion.categoria_id == categoria_id, Sesion.fecha == fecha)
    if hora is None:
        stmt = stmt.where(Sesion.hora.is_(None))
    else:
        stmt = stmt.where(Sesion.hora == hora)
    return db.execute(stmt).scalars().first()


def _deportistas_de_categoria(
    db: Session, categoria_id: uuid.UUID, *, disciplina_id: uuid.UUID | None = None
) -> list[Deportista]:
    stmt = select(Deportista).where(Deportista.categoria_id == categoria_id)
    # Filtro opcional por disciplina del deportista (misma convención que la lista
    # de deportistas): una categoría puede mezclar futsal y voleibol; esto acota a
    # una sola disciplina para tomar lista de esa clase.
    if disciplina_id is not None:
        stmt = stmt.where(Deportista.disciplina_id == disciplina_id)
    return list(
        db.execute(
            stmt.order_by(
                Deportista.ap_paterno, Deportista.ap_materno, Deportista.nombres
            )
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
    disciplina_ids: set[uuid.UUID] | None = None,
    disciplina_filtro: uuid.UUID | None = None,
) -> tuple[Categoria, Sesion | None, list[Deportista], dict[uuid.UUID, str]]:
    """Devuelve datos crudos del roster (get-or-create lógico, NO crea sesión).

    Retorna `(categoria, sesion|None, deportistas, estados_por_deportista)`. Si no hay
    sesión para (categoria, fecha) -> `sesion=None` y el dict de estados vacío.

    `disciplina_filtro` (opcional, elegido por el usuario): acota el roster a los
    deportistas de esa disciplina. Es distinto de `disciplina_ids` (red de seguridad
    del scope del ENTRENADOR, a nivel de categoría).
    """
    cat = _cargar_categoria_con_scope(
        db,
        categoria_id=categoria_id,
        role=role,
        sucursal_ids=sucursal_ids,
        disciplina_ids=disciplina_ids,
    )
    deportistas = _deportistas_de_categoria(
        db, categoria_id, disciplina_id=disciplina_filtro
    )

    # Para el roster usamos la sesión "del día" (hora NULL es la canónica); si
    # existe alguna sesión ese día tomamos la primera por hora para reflejar lo
    # ya guardado.
    sesion = (
        db.execute(
            select(Sesion)
            .where(Sesion.categoria_id == categoria_id, Sesion.fecha == fecha)
            .order_by(Sesion.hora.is_(None).desc(), Sesion.hora)
        )
        .scalars()
        .first()
    )

    estados: dict[uuid.UUID, str] = {}
    if sesion is not None:
        rows = db.execute(
            select(Asistencia.deportista_id, Asistencia.estado).where(
                Asistencia.sesion_id == sesion.id
            )
        ).all()
        for al_id, est in rows:
            estados[al_id] = est

    return cat, sesion, deportistas, estados


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
    disciplina_ids: set[uuid.UUID] | None = None,
) -> tuple[Categoria, Sesion]:
    """Crea/recupera la sesión y hace upsert de las marcas (idempotente) (C2).

    Solo se aplican marcas de deportistas que pertenecen a la categoría (defensa en
    profundidad sobre los ids del body). `registrado_por`/`updated_at` quedan como
    auditoría (RNF-03). Devuelve `(categoria, sesion)`.
    """
    cat = _cargar_categoria_con_scope(
        db,
        categoria_id=categoria_id,
        role=role,
        sucursal_ids=sucursal_ids,
        disciplina_ids=disciplina_ids,
    )

    sesion = _get_or_create_sesion(
        db, org_id=org_id, categoria_id=categoria_id, fecha=fecha, hora=hora
    )

    # Deportistas válidos de la categoría (ignora ids ajenos / de otra categoría).
    deportistas_validos = {a.id for a in _deportistas_de_categoria(db, categoria_id)}

    # Asistencias ya existentes para esta sesión (upsert por deportista_id).
    existentes = {
        a.deportista_id: a
        for a in db.execute(select(Asistencia).where(Asistencia.sesion_id == sesion.id))
        .scalars()
        .all()
    }

    ahora = datetime.now(UTC)
    for deportista_id, estado in marcas:
        if deportista_id not in deportistas_validos:
            continue
        existente = existentes.get(deportista_id)
        if existente is None:
            db.add(
                Asistencia(
                    org_id=org_id,
                    sesion_id=sesion.id,
                    deportista_id=deportista_id,
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
    disciplina_ids: set[uuid.UUID] | None = None,
) -> tuple[list[tuple[Sesion, int, int, int]], int]:
    """Historial de sesiones de una categoría con contadores (C2).

    Aplica scoping por rol sobre la categoría (403/404). Devuelve
    `([(sesion, presentes, ausentes, total)], total_sesiones)`.
    """
    _cargar_categoria_con_scope(
        db,
        categoria_id=categoria_id,
        role=role,
        sucursal_ids=sucursal_ids,
        disciplina_ids=disciplina_ids,
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

    `total` es la cantidad de deportistas (filas), no solo los marcados — refleja el
    contador "Total" de la pantalla. Función pura (sin I/O), fácil de testear.
    """
    presentes = sum(1 for e in estados if e == "PRESENTE")
    ausentes = sum(1 for e in estados if e == "AUSENTE")
    return presentes, ausentes, len(estados)
