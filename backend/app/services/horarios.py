"""Servicio de Horarios (C2/C3) — CRUD scoped por rol, vista semana, generación y recordatorio.

Reglas de dominio (con I/O; corre SIEMPRE con `app.current_org` ya fijado por el
llamador, RLS es la barrera real, no `WHERE org_id`):

- **Scoping por rol** (mismo criterio que asistencia/ficha médica, C5): ADMIN ve
  todos los horarios activos de la org y puede crear/editar/borrar-soft;
  ENTRENADOR solo LEE los de sus `sucursal_ids` (la sucursal sale de la categoría).
  Pedir/operar una categoría fuera de su alcance -> `CategoriaFuera` (403);
  categoría inexistente -> `CategoriaNoEncontrada` (404).
- **Validación**: `hora_fin > hora_inicio` y `dia_semana` en 0..6 (ya en el schema,
  re-chequeado aquí en defensa en profundidad -> `ValueError` => 422). Unicidad
  `(categoria_id, dia_semana, hora_inicio)` -> `HorarioDuplicado` => 409.
- **Soft-delete**: `activo=false` (no borrado físico); el horario desaparece del
  listado pero la fila persiste (las sesiones ya generadas no se tocan).

Generación y recordatorio (corren en el worker, por org, contexto fijado):
- `generar_sesiones_programadas`: por cada horario activo y cada fecha de la
  ventana cuyo `weekday()==dia_semana`, **reutiliza el get-or-create de Asistencia**
  (`_get_or_create_sesion`, key `(categoria_id, fecha, hora=hora_inicio)`) y setea
  `horario_id`/`entrenador_id`. Idempotente (UNIQUE de `sesion` + chequeo).
- `enviar_recordatorios_clase`: sesiones cuya `fecha+hora_inicio` cae en la ventana
  `[ahora, ahora+horas]` y `recordatorio_enviado_en IS NULL` -> notifica (Noop) a
  los tutores de los alumnos de la categoría y setea `recordatorio_enviado_en=now`.
  Idempotente por esa marca.

No se salta el contexto de tenant. La lógica pura de fechas (`fechas_de_horario`)
no hace I/O y es testeable sin BD.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.alumno import Alumno
from app.models.alumno_tutor import AlumnoTutor
from app.models.categoria import Categoria
from app.models.entrenador import Entrenador
from app.models.horario_clase import HorarioClase
from app.models.sesion import Sesion
from app.models.sucursal import Sucursal
from app.models.tutor import Tutor
from app.schemas.horarios import (
    CategoriaRefHorario,
    ClaseSemana,
    DiaSemana,
    EntrenadorRefHorario,
    HorarioCreate,
    HorarioOut,
    HorarioUpdate,
    SemanaOut,
    SucursalRefHorario,
    dia_label,
)
from app.services.asistencia import _buscar_sesion, _get_or_create_sesion
from app.services.deps import get_notification_service


class HorarioError(Exception):
    """Error base de negocio del módulo de horarios."""


class CategoriaNoEncontrada(HorarioError):
    """La categoría no existe (en la org del contexto) -> 404."""


class CategoriaFuera(HorarioError):
    """La categoría está fuera del alcance del rol (sucursal) -> 403."""


class HorarioNoEncontrado(HorarioError):
    """El horario no existe (activo, en la org del contexto) -> 404."""


class HorarioDuplicado(HorarioError):
    """Ya existe un horario para (categoria, dia_semana, hora_inicio) -> 409."""


# --------------------------------------------------------------------------- #
# Lógica pura (sin I/O) — testeable sin BD
# --------------------------------------------------------------------------- #
def _sucursales_permitidas(role: str, sucursal_ids: list[str]) -> set[uuid.UUID] | None:
    """Conjunto de sucursales que el rol puede ver, o `None` si ve todas (ADMIN).

    ENTRENADOR queda limitado a sus `sucursal_ids` del token (mismo criterio que
    asistencia/avisos, C5). Cualquier otro rol no-ADMIN: sin sucursales permitidas.
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


def fechas_de_horario(dia_semana: int, hoy: date, dias_ventana: int) -> list[date]:
    """Fechas en `[hoy, hoy+dias_ventana]` cuyo `weekday()==dia_semana`.

    Función pura (sin I/O). `dia_semana` 0=Lunes … 6=Domingo (= `date.weekday()`).
    La ventana es **inclusiva** en ambos extremos (`hoy` y `hoy+dias_ventana`).
    """
    return [
        hoy + timedelta(days=offset)
        for offset in range(dias_ventana + 1)
        if (hoy + timedelta(days=offset)).weekday() == dia_semana
    ]


# --------------------------------------------------------------------------- #
# Scoping por rol
# --------------------------------------------------------------------------- #
def _cargar_categoria_con_scope(
    db: Session, *, categoria_id: uuid.UUID, role: str, sucursal_ids: list[str]
) -> Categoria:
    """Carga la categoría aplicando el scoping por rol (404 / 403)."""
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
# Mapeo a OUT (resolviendo refs precargadas, evita N+1)
# --------------------------------------------------------------------------- #
def _to_out(
    horario: HorarioClase,
    *,
    categorias: dict[uuid.UUID, Categoria],
    sucursales: dict[uuid.UUID, Sucursal],
    entrenadores: dict[uuid.UUID, Entrenador],
) -> HorarioOut:
    cat = categorias[horario.categoria_id]
    suc = sucursales.get(cat.sucursal_id)
    ent = entrenadores.get(horario.entrenador_id) if horario.entrenador_id else None
    return HorarioOut(
        id=horario.id,
        categoria=CategoriaRefHorario(id=cat.id, nombre=cat.nombre),
        sucursal=SucursalRefHorario(
            id=cat.sucursal_id, nombre=suc.nombre if suc else ""
        ),
        dia_semana=horario.dia_semana,
        dia_label=dia_label(horario.dia_semana),
        hora_inicio=horario.hora_inicio,
        hora_fin=horario.hora_fin,
        entrenador=(
            EntrenadorRefHorario(id=ent.id, nombres=ent.nombres) if ent else None
        ),
        activo=horario.activo,
    )


def _precargar_refs(
    db: Session, horarios: list[HorarioClase]
) -> tuple[
    dict[uuid.UUID, Categoria],
    dict[uuid.UUID, Sucursal],
    dict[uuid.UUID, Entrenador],
]:
    """Precarga categorías/sucursales/entrenadores referenciados (evita N+1)."""
    cat_ids = {h.categoria_id for h in horarios}
    categorias: dict[uuid.UUID, Categoria] = (
        {
            c.id: c
            for c in db.execute(
                select(Categoria).where(Categoria.id.in_(cat_ids))
            )
            .scalars()
            .all()
        }
        if cat_ids
        else {}
    )
    suc_ids = {c.sucursal_id for c in categorias.values()}
    sucursales: dict[uuid.UUID, Sucursal] = (
        {
            s.id: s
            for s in db.execute(select(Sucursal).where(Sucursal.id.in_(suc_ids)))
            .scalars()
            .all()
        }
        if suc_ids
        else {}
    )
    ent_ids = {h.entrenador_id for h in horarios if h.entrenador_id is not None}
    entrenadores: dict[uuid.UUID, Entrenador] = (
        {
            e.id: e
            for e in db.execute(select(Entrenador).where(Entrenador.id.in_(ent_ids)))
            .scalars()
            .all()
        }
        if ent_ids
        else {}
    )
    return categorias, sucursales, entrenadores


# --------------------------------------------------------------------------- #
# Listado (GET /horarios) — scoped por rol
# --------------------------------------------------------------------------- #
def _horarios_visibles(
    db: Session,
    *,
    role: str,
    sucursal_ids: list[str],
    categoria_id: uuid.UUID | None,
    sucursal_id: uuid.UUID | None,
) -> list[HorarioClase]:
    """Horarios activos visibles por rol, con filtros opcionales (C2).

    Join a `categoria` para filtrar por sucursal (la del horario sale de la
    categoría). Orden estable por (dia_semana, hora_inicio).
    """
    stmt = (
        select(HorarioClase)
        .join(Categoria, Categoria.id == HorarioClase.categoria_id)
        .where(HorarioClase.activo.is_(True))
        .order_by(HorarioClase.dia_semana, HorarioClase.hora_inicio)
    )

    permitidas = _sucursales_permitidas(role, sucursal_ids)
    if permitidas is not None:
        if not permitidas:
            return []
        stmt = stmt.where(Categoria.sucursal_id.in_(permitidas))

    if categoria_id is not None:
        stmt = stmt.where(HorarioClase.categoria_id == categoria_id)
    if sucursal_id is not None:
        stmt = stmt.where(Categoria.sucursal_id == sucursal_id)

    return list(db.execute(stmt).scalars().all())


def listar(
    db: Session,
    *,
    role: str,
    sucursal_ids: list[str],
    categoria_id: uuid.UUID | None = None,
    sucursal_id: uuid.UUID | None = None,
) -> list[HorarioOut]:
    """`GET /horarios` -> lista de horarios activos scoped por rol (C2)."""
    horarios = _horarios_visibles(
        db,
        role=role,
        sucursal_ids=sucursal_ids,
        categoria_id=categoria_id,
        sucursal_id=sucursal_id,
    )
    categorias, sucursales, entrenadores = _precargar_refs(db, horarios)
    return [
        _to_out(
            h,
            categorias=categorias,
            sucursales=sucursales,
            entrenadores=entrenadores,
        )
        for h in horarios
    ]


# --------------------------------------------------------------------------- #
# Vista semanal (GET /horarios/semana) — rejilla 7 días
# --------------------------------------------------------------------------- #
def vista_semana(
    db: Session,
    *,
    role: str,
    sucursal_ids: list[str],
    categoria_id: uuid.UUID | None = None,
    sucursal_id: uuid.UUID | None = None,
) -> SemanaOut:
    """`GET /horarios/semana` -> rejilla con 7 días (0..6) agrupando clases (C2)."""
    horarios = _horarios_visibles(
        db,
        role=role,
        sucursal_ids=sucursal_ids,
        categoria_id=categoria_id,
        sucursal_id=sucursal_id,
    )
    categorias, _sucursales, entrenadores = _precargar_refs(db, horarios)

    dias: list[DiaSemana] = [
        DiaSemana(dia_semana=d, dia_label=dia_label(d), clases=[]) for d in range(7)
    ]
    for h in horarios:
        cat = categorias[h.categoria_id]
        ent = entrenadores.get(h.entrenador_id) if h.entrenador_id else None
        dias[h.dia_semana].clases.append(
            ClaseSemana(
                id=h.id,
                categoria=CategoriaRefHorario(id=cat.id, nombre=cat.nombre),
                hora_inicio=h.hora_inicio,
                hora_fin=h.hora_fin,
                entrenador=(
                    EntrenadorRefHorario(id=ent.id, nombres=ent.nombres) if ent else None
                ),
            )
        )
    # Orden interno por hora_inicio (el WHERE ya ordena, pero el agrupado lo asegura).
    for d in dias:
        d.clases.sort(key=lambda c: c.hora_inicio)
    return SemanaOut(dias=dias)


# --------------------------------------------------------------------------- #
# Alta / edición / soft-delete (ADMIN) — valida y traduce unicidad a 409
# --------------------------------------------------------------------------- #
def _out_de_horario(db: Session, horario: HorarioClase) -> HorarioOut:
    """Construye el `HorarioOut` de un único horario resolviendo sus refs."""
    categorias, sucursales, entrenadores = _precargar_refs(db, [horario])
    return _to_out(
        horario,
        categorias=categorias,
        sucursales=sucursales,
        entrenadores=entrenadores,
    )


def _validar(data: HorarioCreate | HorarioUpdate) -> None:
    """Re-valida la invariante en el servicio (defensa en profundidad) => 422."""
    if not 0 <= data.dia_semana <= 6:
        raise ValueError("dia_semana debe estar entre 0 (Lunes) y 6 (Domingo)")
    if data.hora_fin <= data.hora_inicio:
        raise ValueError("hora_fin debe ser mayor que hora_inicio")


def _existe_duplicado(
    db: Session,
    *,
    categoria_id: uuid.UUID,
    dia_semana: int,
    hora_inicio: time,
    excluir_id: uuid.UUID | None = None,
) -> bool:
    """`True` si ya hay un horario (activo o no) con esa clave única."""
    stmt = select(HorarioClase.id).where(
        HorarioClase.categoria_id == categoria_id,
        HorarioClase.dia_semana == dia_semana,
        HorarioClase.hora_inicio == hora_inicio,
    )
    if excluir_id is not None:
        stmt = stmt.where(HorarioClase.id != excluir_id)
    return db.execute(stmt).first() is not None


def crear(
    db: Session,
    data: HorarioCreate,
    *,
    org_id: uuid.UUID,
    role: str,
    sucursal_ids: list[str],
) -> HorarioOut:
    """Crea un horario (ADMIN) validando alcance, invariante y unicidad (C2).

    `ValueError` => 422; `CategoriaFuera`/`CategoriaNoEncontrada` => 403/404;
    `HorarioDuplicado` => 409 (clave `(categoria, dia_semana, hora_inicio)`).
    """
    _validar(data)
    _cargar_categoria_con_scope(
        db, categoria_id=data.categoria_id, role=role, sucursal_ids=sucursal_ids
    )

    if _existe_duplicado(
        db,
        categoria_id=data.categoria_id,
        dia_semana=data.dia_semana,
        hora_inicio=data.hora_inicio,
    ):
        raise HorarioDuplicado(
            "Ya existe un horario para esa categoría, día y hora de inicio"
        )

    horario = HorarioClase(
        org_id=org_id,
        categoria_id=data.categoria_id,
        dia_semana=data.dia_semana,
        hora_inicio=data.hora_inicio,
        hora_fin=data.hora_fin,
        entrenador_id=data.entrenador_id,
        activo=True,
    )
    db.add(horario)
    try:
        db.flush()
    except IntegrityError as exc:
        # Carrera contra el UNIQUE de BD: traducir a 409.
        db.rollback()
        raise HorarioDuplicado(
            "Ya existe un horario para esa categoría, día y hora de inicio"
        ) from exc
    return _out_de_horario(db, horario)


def _cargar_horario_activo(db: Session, horario_id: uuid.UUID) -> HorarioClase:
    """Carga un horario activo de la org del contexto. 404 si no existe/inactivo."""
    horario = db.execute(
        select(HorarioClase).where(
            HorarioClase.id == horario_id, HorarioClase.activo.is_(True)
        )
    ).scalar_one_or_none()
    if horario is None:
        raise HorarioNoEncontrado("Horario no encontrado")
    return horario


def editar(
    db: Session,
    horario_id: uuid.UUID,
    data: HorarioUpdate,
    *,
    role: str,
    sucursal_ids: list[str],
) -> HorarioOut:
    """Edita un horario activo (ADMIN), misma validación/unicidad que el alta (C2).

    404 si no existe; valida el alcance sobre la categoría destino (403/404);
    `ValueError` => 422; `HorarioDuplicado` => 409.
    """
    _validar(data)
    horario = _cargar_horario_activo(db, horario_id)
    _cargar_categoria_con_scope(
        db, categoria_id=data.categoria_id, role=role, sucursal_ids=sucursal_ids
    )

    if _existe_duplicado(
        db,
        categoria_id=data.categoria_id,
        dia_semana=data.dia_semana,
        hora_inicio=data.hora_inicio,
        excluir_id=horario.id,
    ):
        raise HorarioDuplicado(
            "Ya existe un horario para esa categoría, día y hora de inicio"
        )

    horario.categoria_id = data.categoria_id
    horario.dia_semana = data.dia_semana
    horario.hora_inicio = data.hora_inicio
    horario.hora_fin = data.hora_fin
    horario.entrenador_id = data.entrenador_id
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HorarioDuplicado(
            "Ya existe un horario para esa categoría, día y hora de inicio"
        ) from exc
    return _out_de_horario(db, horario)


def eliminar(db: Session, horario_id: uuid.UUID) -> None:
    """Soft-delete: marca `activo=false` (no borrado físico) (C2). 404 si no existe.

    Las sesiones ya generadas no se tocan (su `horario_id` sigue apuntando).
    """
    horario = _cargar_horario_activo(db, horario_id)
    horario.activo = False
    db.flush()


# --------------------------------------------------------------------------- #
# Generación de sesiones programadas (C3) — reutiliza Asistencia, idempotente
# --------------------------------------------------------------------------- #
def generar_sesiones_programadas(
    db: Session,
    org_id: uuid.UUID,
    *,
    hoy: date | None = None,
    dias_ventana: int,
) -> int:
    """Genera las sesiones de la ventana para cada horario activo (C3).

    Por cada horario activo y cada fecha en `[hoy, hoy+dias_ventana]` cuyo
    `weekday()==dia_semana`, **reutiliza el get-or-create de Asistencia**
    (`_get_or_create_sesion`, key `(categoria_id, fecha, hora=hora_inicio)`) y
    enlaza `horario_id` (y `entrenador_id` si la sesión es nueva). Idempotente:
    re-correr no duplica (UNIQUE de `sesion`). Devuelve cuántas sesiones creó.

    Corre con `app.current_org` ya fijado (lo hace el worker por org).
    """
    if hoy is None:
        hoy = datetime.now(UTC).date()

    horarios = list(
        db.execute(select(HorarioClase).where(HorarioClase.activo.is_(True)))
        .scalars()
        .all()
    )

    creadas = 0
    for h in horarios:
        for fecha in fechas_de_horario(h.dia_semana, hoy, dias_ventana):
            # ¿Ya existía la sesión (categoria, fecha, hora_inicio)? Define si la
            # get-or-create la crea (contador fiable, sin depender del estado FK).
            existia = (
                _buscar_sesion(
                    db,
                    categoria_id=h.categoria_id,
                    fecha=fecha,
                    hora=h.hora_inicio,
                )
                is not None
            )
            sesion = _get_or_create_sesion(
                db,
                org_id=org_id,
                categoria_id=h.categoria_id,
                fecha=fecha,
                hora=h.hora_inicio,
            )
            if not existia:
                creadas += 1
            # Enlaza el horario solo si está libre (no pisa una sesión ya enlazada
            # ni reescribe un entrenador puesto a mano) -> idempotente.
            if sesion.horario_id is None:
                sesion.horario_id = h.id
                if sesion.entrenador_id is None and h.entrenador_id is not None:
                    sesion.entrenador_id = h.entrenador_id
    db.flush()
    return creadas


# --------------------------------------------------------------------------- #
# Recordatorio de clase (C3) — idempotente vía recordatorio_enviado_en
# --------------------------------------------------------------------------- #
def enviar_recordatorios_clase(
    db: Session,
    org_id: uuid.UUID,
    *,
    ahora: datetime | None = None,
    horas: int,
) -> int:
    """Envía el recordatorio de las clases próximas (C3). Idempotente.

    Sesiones (de horario, `hora` no nula) cuyo `fecha+hora` cae en
    `[ahora, ahora+horas]` y `recordatorio_enviado_en IS NULL`: notifica (Noop) a
    los tutores de los alumnos de la categoría y setea `recordatorio_enviado_en`.
    Re-correr no reenvía (la marca ya no es NULL). Devuelve cuántas notificó.

    Corre con `app.current_org` ya fijado (lo hace el worker por org). `ahora` es
    timezone-aware (UTC) por defecto.
    """
    if ahora is None:
        ahora = datetime.now(UTC)
    fin = ahora + timedelta(hours=horas)
    notifier = get_notification_service()

    # Candidatas: sesiones con hora, sin recordatorio, dentro del rango de fechas.
    candidatas = list(
        db.execute(
            select(Sesion).where(
                Sesion.hora.is_not(None),
                Sesion.recordatorio_enviado_en.is_(None),
                Sesion.fecha >= ahora.date(),
                Sesion.fecha <= fin.date(),
            )
        )
        .scalars()
        .all()
    )

    notificadas = 0
    for sesion in candidatas:
        if sesion.hora is None:
            continue
        # Momento exacto de la clase (UTC). Filtro fino dentro de la ventana.
        cuando = datetime.combine(sesion.fecha, sesion.hora, tzinfo=UTC)
        if not (ahora <= cuando <= fin):
            continue

        for tutor in _tutores_de_categoria(db, sesion.categoria_id):
            notifier.send(
                to=str(tutor.id),
                template="recordatorio_clase",
                variables={
                    "sesion_id": str(sesion.id),
                    "fecha": sesion.fecha.isoformat(),
                    "hora": sesion.hora.isoformat(),
                },
            )
        sesion.recordatorio_enviado_en = ahora
        notificadas += 1
    db.flush()
    return notificadas


def _tutores_de_categoria(db: Session, categoria_id: uuid.UUID) -> list[Tutor]:
    """Tutores (distintos) de los alumnos de una categoría (para el recordatorio)."""
    return list(
        db.execute(
            select(Tutor)
            .join(AlumnoTutor, AlumnoTutor.tutor_id == Tutor.id)
            .join(Alumno, Alumno.id == AlumnoTutor.alumno_id)
            .where(Alumno.categoria_id == categoria_id)
            .distinct()
        )
        .scalars()
        .all()
    )
