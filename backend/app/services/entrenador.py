"""Servicio de Entrenadores (epic B · Gestión de Entrenadores).

Reglas de dominio (con I/O; corre SIEMPRE con `app.current_org` ya fijado por el
llamador — RLS es la barrera real, no `WHERE org_id`):

- **listar**: join `entrenador` ⨝ `usuario` (por `usuario_id`), scoped por RLS (la
  org del contexto), orden por `entrenador.nombres`. `solo_activos` filtra los
  `usuario.activo`. Devuelve filas `(Entrenador, Usuario)` con datos suficientes
  para `EntrenadorOut`.
- **crear**: en UNA transacción crea el `usuario`(ENTRENADOR, activo,
  `password_hash=hash_password(...)`) + el perfil `entrenador`. El `org_id` es el del
  admin (el GUC ya está fijado -> RLS OK). **GOTCHA crítico de RLS:** `usuario.email`
  es UNIQUE **global** (cruza orgs) pero el pre-chequeo corre bajo RLS y NO ve
  usuarios de otras orgs. Por eso (a) se pre-chequea dentro de la org y, **además**,
  (b) se captura el `IntegrityError` del INSERT (violación de la constraint global) y
  se traduce a `EmailEnUso` con rollback. No se confía solo en el pre-chequeo.
  El **CI** es único por org (índice parcial `(org_id, ci) WHERE ci IS NOT NULL`): se
  pre-chequea **ANTES** de crear el usuario (fail-fast D2: NO se crea un segundo login
  si el CI ya existe) y se captura el `IntegrityError` del índice por carreras de
  doble-submit -> `CiEnUso`. El JSONB legacy `disciplinas` YA NO se escribe (D1); las
  disciplinas se enlazan vía la M:N `entrenador_disciplina` (catálogo S2).
- **editar**: carga el `Entrenador` (+ su `Usuario`) bajo RLS; 404 si no existe.
  Aplica solo los campos provistos (no-None): `nombres/especialidad/ci/telefono` en
  el entrenador, `activo` y `password`(hasheada) en el usuario, y `disciplina_ids`
  (replace) en la M:N. Si el `ci` provisto colisiona con OTRO entrenador -> `CiEnUso`.

No se salta el contexto de tenant; el INSERT corre bajo el `app.current_org` del
admin (sin BYPASSRLS, sin debilitar el fail-closed).
"""

from __future__ import annotations

import uuid

from sqlalchemy import Row, delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models.disciplina import Disciplina
from app.models.entrenador import Entrenador
from app.models.entrenador_disciplina import EntrenadorDisciplina
from app.models.entrenador_sucursal import EntrenadorSucursal
from app.models.usuario import Usuario
from app.schemas.disciplina import DisciplinaRef
from app.schemas.entrenador import EntrenadorCreate, EntrenadorUpdate
from app.services import disciplina as disciplina_svc


class EntrenadorError(Exception):
    """Error base de negocio del módulo de entrenadores."""


class EmailEnUso(EntrenadorError):
    """El email ya está en uso (en esta org o en otra) -> 409."""


class CiEnUso(EntrenadorError):
    """El CI ya está en uso por otro entrenador de la org -> 409."""


class EntrenadorNoEncontrado(EntrenadorError):
    """El entrenador no existe (en la org del contexto) -> 404."""


_CI_EN_USO_MSG = "Ya existe un entrenador con ese CI en tu organización"


# Fila del join entrenador ⨝ usuario, con el contrato de `EntrenadorOut`.
EntrenadorRow = Row[tuple[Entrenador, Usuario]]


# --------------------------------------------------------------------------- #
# Asignación M:N a sucursales (epic Recordatorio de deudores, CONTRATO 4)
# --------------------------------------------------------------------------- #
def sucursal_ids_de(db: Session, entrenador_id: uuid.UUID) -> list[uuid.UUID]:
    """`sucursal_id`s asignadas a un entrenador (bajo RLS), orden estable."""
    return list(
        db.execute(
            select(EntrenadorSucursal.sucursal_id)
            .where(EntrenadorSucursal.entrenador_id == entrenador_id)
            .order_by(EntrenadorSucursal.sucursal_id)
        )
        .scalars()
        .all()
    )


def sucursal_ids_por_entrenador(
    db: Session, entrenador_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[uuid.UUID]]:
    """Mapa `entrenador_id -> [sucursal_id]` en UNA query (evita N+1 en el listado).

    Corre bajo el `app.current_org` del caller (RLS). Devuelve solo entrenadores con
    al menos una sucursal; el router rellena `[]` para los ausentes.
    """
    if not entrenador_ids:
        return {}
    filas = db.execute(
        select(EntrenadorSucursal.entrenador_id, EntrenadorSucursal.sucursal_id)
        .where(EntrenadorSucursal.entrenador_id.in_(entrenador_ids))
        .order_by(EntrenadorSucursal.entrenador_id, EntrenadorSucursal.sucursal_id)
    ).all()
    mapa: dict[uuid.UUID, list[uuid.UUID]] = {}
    for ent_id, suc_id in filas:
        mapa.setdefault(ent_id, []).append(suc_id)
    return mapa


def _resolver_sucursales(
    db: Session,
    *,
    org_id: uuid.UUID,
    entrenador_id: uuid.UUID,
    deseadas: list[uuid.UUID],
) -> None:
    """Reconcilia la asignación M:N al set `deseadas` (REEMPLAZA), bajo RLS, sin commit.

    Borra las sobrantes e inserta las nuevas con `ON CONFLICT DO NOTHING` (idempotente,
    absorbe duplicados/carreras). RLS garantiza que solo se toquen filas de la org del
    contexto; un `sucursal_id` de otra org no es visible y el INSERT lo rechaza el
    `WITH CHECK` (capturado arriba como error de integridad si aplica).
    """
    actuales = set(sucursal_ids_de(db, entrenador_id))
    deseadas_set = set(deseadas)

    sobrantes = actuales - deseadas_set
    if sobrantes:
        db.execute(
            delete(EntrenadorSucursal).where(
                EntrenadorSucursal.entrenador_id == entrenador_id,
                EntrenadorSucursal.sucursal_id.in_(sobrantes),
            )
        )

    nuevas = deseadas_set - actuales
    for suc_id in nuevas:
        db.execute(
            pg_insert(EntrenadorSucursal)
            .values(org_id=org_id, entrenador_id=entrenador_id, sucursal_id=suc_id)
            .on_conflict_do_nothing(index_elements=["entrenador_id", "sucursal_id"])
        )
    db.flush()


# --------------------------------------------------------------------------- #
# Asignación M:N a disciplinas (epic S4, CONTRATO 3) — catálogo GLOBAL `disciplina`
# --------------------------------------------------------------------------- #
def disciplina_refs_de(db: Session, entrenador_id: uuid.UUID) -> list[DisciplinaRef]:
    """`DisciplinaRef[]` ({id,nombre}) enlazadas a un entrenador (bajo RLS), orden por nombre.

    Join `entrenador_disciplina ⨝ disciplina`: la puente es tenant (RLS por org); el
    catálogo `disciplina` es global (sin org_id). Para una sola respuesta POST/PUT.
    """
    filas = db.execute(
        select(Disciplina.id, Disciplina.nombre)
        .join(EntrenadorDisciplina, EntrenadorDisciplina.disciplina_id == Disciplina.id)
        .where(EntrenadorDisciplina.entrenador_id == entrenador_id)
        .order_by(Disciplina.nombre)
    ).all()
    return [DisciplinaRef(id=disc_id, nombre=nombre) for disc_id, nombre in filas]


def disciplinas_por_entrenador(
    db: Session, entrenador_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[DisciplinaRef]]:
    """Mapa `entrenador_id -> [DisciplinaRef]` en UNA query (evita N+1 en el listado).

    Join `entrenador_disciplina ⨝ disciplina` bajo el `app.current_org` del caller
    (RLS sobre la puente; el catálogo es global). Devuelve solo entrenadores con al
    menos una disciplina; el router rellena `[]` para los ausentes.
    """
    if not entrenador_ids:
        return {}
    filas = db.execute(
        select(EntrenadorDisciplina.entrenador_id, Disciplina.id, Disciplina.nombre)
        .join(Disciplina, Disciplina.id == EntrenadorDisciplina.disciplina_id)
        .where(EntrenadorDisciplina.entrenador_id.in_(entrenador_ids))
        .order_by(EntrenadorDisciplina.entrenador_id, Disciplina.nombre)
    ).all()
    mapa: dict[uuid.UUID, list[DisciplinaRef]] = {}
    for ent_id, disc_id, nombre in filas:
        mapa.setdefault(ent_id, []).append(DisciplinaRef(id=disc_id, nombre=nombre))
    return mapa


def _disciplina_ids_de(db: Session, entrenador_id: uuid.UUID) -> set[uuid.UUID]:
    """`disciplina_id`s actualmente enlazadas a un entrenador (bajo RLS)."""
    return set(
        db.execute(
            select(EntrenadorDisciplina.disciplina_id).where(
                EntrenadorDisciplina.entrenador_id == entrenador_id
            )
        )
        .scalars()
        .all()
    )


def _resolver_disciplinas(
    db: Session,
    *,
    org_id: uuid.UUID,
    entrenador_id: uuid.UUID,
    deseadas: list[uuid.UUID],
) -> None:
    """Reconcilia la M:N a disciplinas al set `deseadas` (REEMPLAZA), bajo RLS, sin commit.

    Valida que cada disciplina nueva exista y esté ACTIVA en el catálogo global vía
    `disciplina_svc.get_disciplina_activa_o_error` (404/422 propagados al router).
    Borra las sobrantes e inserta las nuevas con `ON CONFLICT DO NOTHING` (idempotente,
    absorbe duplicados/carreras). Gemelo de `_resolver_sucursales`.
    """
    actuales = _disciplina_ids_de(db, entrenador_id)
    deseadas_set = set(deseadas)

    sobrantes = actuales - deseadas_set
    if sobrantes:
        db.execute(
            delete(EntrenadorDisciplina).where(
                EntrenadorDisciplina.entrenador_id == entrenador_id,
                EntrenadorDisciplina.disciplina_id.in_(sobrantes),
            )
        )

    nuevas = deseadas_set - actuales
    for disc_id in nuevas:
        # Solo disciplinas activas del catálogo son enlazables (404 si no existe, 422 si
        # inactiva). Validar ANTES de insertar (el catálogo es global, fuera de RLS).
        disciplina_svc.get_disciplina_activa_o_error(db, disc_id)
        db.execute(
            pg_insert(EntrenadorDisciplina)
            .values(org_id=org_id, entrenador_id=entrenador_id, disciplina_id=disc_id)
            .on_conflict_do_nothing(index_elements=["entrenador_id", "disciplina_id"])
        )
    db.flush()


# --------------------------------------------------------------------------- #
# CI único por org (índice parcial `(org_id, ci) WHERE ci IS NOT NULL`)
# --------------------------------------------------------------------------- #
def _ci_en_uso(db: Session, ci: str, *, excluir_id: uuid.UUID | None = None) -> bool:
    """True si OTRO entrenador de la org (RLS) ya tiene este `ci` (no-nulo)."""
    stmt = select(Entrenador.id).where(Entrenador.ci == ci)
    if excluir_id is not None:
        stmt = stmt.where(Entrenador.id != excluir_id)
    return db.execute(stmt).first() is not None


# --------------------------------------------------------------------------- #
# Listado (GET /entrenadores)
# --------------------------------------------------------------------------- #
def listar(db: Session, *, solo_activos: bool) -> list[EntrenadorRow]:
    """Lista los entrenadores de la org (RLS), join con su `usuario`, orden por nombres.

    `solo_activos=True` excluye los `usuario.activo=false` (dados de baja). Devuelve
    filas `(Entrenador, Usuario)` para que el router construya `EntrenadorOut`.
    """
    stmt = (
        select(Entrenador, Usuario)
        .join(Usuario, Usuario.id == Entrenador.usuario_id)
        .order_by(Entrenador.nombres)
    )
    if solo_activos:
        stmt = stmt.where(Usuario.activo.is_(True))
    return list(db.execute(stmt).all())


# --------------------------------------------------------------------------- #
# Alta (POST /entrenadores) — usuario(ENTRENADOR) + perfil en una transacción
# --------------------------------------------------------------------------- #
def _buscar_usuario_por_email(db: Session, email: str) -> Usuario | None:
    """Busca un usuario por email **bajo RLS** (solo ve los de la org del contexto)."""
    return db.execute(select(Usuario).where(Usuario.email == email)).scalar_one_or_none()


def crear(
    db: Session,
    body: EntrenadorCreate,
    *,
    org_id: uuid.UUID,
) -> EntrenadorRow:
    """Crea `usuario`(ENTRENADOR) + `entrenador` en una transacción (contrato B).

    Defensa del GOTCHA de RLS: pre-chequeo del email en la org **y** captura del
    `IntegrityError` del INSERT (email duplicado en otra org no visible bajo RLS) ->
    `EmailEnUso` con rollback. CI único por org: pre-chequeo **ANTES** de crear el
    usuario (fail-fast D2: si el CI existe, no se crea un segundo login) -> `CiEnUso`.
    Devuelve la fila `(Entrenador, Usuario)` recién creada.
    """
    # (CI) Pre-chequeo del CI único por org ANTES de tocar el usuario (D2: fail-fast,
    # no crear un login si el CI ya existe). El índice parcial + el catch en el flush
    # cubren la carrera de doble-submit.
    if body.ci is not None and _ci_en_uso(db, body.ci):
        raise CiEnUso(_CI_EN_USO_MSG)

    # (a) Pre-chequeo dentro de la org (mejor mensaje; NO es la única barrera).
    if _buscar_usuario_por_email(db, body.email) is not None:
        raise EmailEnUso("El email ya está en uso")

    usuario = Usuario(
        org_id=org_id,
        email=body.email,
        password_hash=hash_password(body.password),
        role="ENTRENADOR",
        nombre=body.nombres,
        activo=True,
    )
    db.add(usuario)
    try:
        # flush fuerza el INSERT del usuario para detectar la violación de unicidad
        # global (otra org) ANTES de continuar — (b) la defensa real del GOTCHA.
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise EmailEnUso("El email ya está en uso") from exc

    entrenador = Entrenador(
        org_id=org_id,
        usuario_id=usuario.id,
        nombres=body.nombres,
        ci=body.ci,
        especialidad=body.especialidad,
        telefono=body.telefono,
        # JSONB legacy `disciplinas` YA NO se escribe (D1): server_default '[]' lo deja
        # vacío; las disciplinas viven en la M:N `entrenador_disciplina`.
    )
    db.add(entrenador)
    try:
        # Flush fuerza el INSERT del entrenador para destapar el índice parcial único
        # `(org_id, ci) WHERE ci IS NOT NULL` ante una carrera de doble-submit (el
        # pre-chequeo bajo RLS no la cubre) -> `CiEnUso` con rollback.
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise CiEnUso(_CI_EN_USO_MSG) from exc

    # Asignación M:N a sucursales (CONTRATO 4) y a disciplinas (S4 CONTRATO 3). En el
    # alta, cada lista (vacía o no) es el set completo a asignar.
    _resolver_sucursales(db, org_id=org_id, entrenador_id=entrenador.id, deseadas=body.sucursal_ids)
    _resolver_disciplinas(
        db, org_id=org_id, entrenador_id=entrenador.id, deseadas=body.disciplina_ids
    )
    # NO se hace `db.commit()` aquí: el commit lo hace el llamador (`get_db` al
    # cerrar el request, o el test). Commitear dentro del servicio cerraría la
    # transacción y BORRARÍA el GUC `app.current_org` (es `SET LOCAL`), con lo que
    # el `_row_por_id` siguiente correría SIN contexto de tenant -> RLS fail-closed
    # -> 0 filas. El `_row_por_id` corre en ESTA misma transacción (GUC vivo) y ve
    # la fila recién flusheada. (Patrón del resto de servicios: flush, no commit.)
    return _row_por_id(db, entrenador.id)


# --------------------------------------------------------------------------- #
# Edición (PUT /entrenadores/{id}) — solo los campos provistos
# --------------------------------------------------------------------------- #
def _cargar_entrenador(db: Session, entrenador_id: uuid.UUID) -> tuple[Entrenador, Usuario]:
    """Carga `(Entrenador, Usuario)` de la org del contexto. 404 si no existe (RLS)."""
    row = db.execute(
        select(Entrenador, Usuario)
        .join(Usuario, Usuario.id == Entrenador.usuario_id)
        .where(Entrenador.id == entrenador_id)
    ).first()
    if row is None:
        raise EntrenadorNoEncontrado("Entrenador no encontrado")
    return row[0], row[1]


def _row_por_id(db: Session, entrenador_id: uuid.UUID) -> EntrenadorRow:
    """Devuelve la fila `(Entrenador, Usuario)` del entrenador (para la respuesta)."""
    row = db.execute(
        select(Entrenador, Usuario)
        .join(Usuario, Usuario.id == Entrenador.usuario_id)
        .where(Entrenador.id == entrenador_id)
    ).first()
    if row is None:  # pragma: no cover - recién creado/cargado, siempre existe
        raise EntrenadorNoEncontrado("Entrenador no encontrado")
    return row


def editar(
    db: Session,
    entrenador_id: uuid.UUID,
    body: EntrenadorUpdate,
) -> EntrenadorRow:
    """Edita un entrenador (solo los campos no-None). 404 si no existe (contrato B).

    `nombres/especialidad/ci/telefono` van al perfil; `activo` y `password` al usuario
    (baja/reactivación + reset de clave). El `email` no se edita. El `ci` provisto que
    colisione con OTRO entrenador de la org -> `CiEnUso`. `disciplina_ids` reemplaza la
    M:N (None = no tocar; [] = limpiar; lista = REEMPLAZA).
    """
    entrenador, usuario = _cargar_entrenador(db, entrenador_id)

    if body.nombres is not None:
        entrenador.nombres = body.nombres
    if body.ci is not None:
        # Unicidad por org excluyendo el propio id (re-set del mismo CI es no-op OK).
        if _ci_en_uso(db, body.ci, excluir_id=entrenador.id):
            raise CiEnUso(_CI_EN_USO_MSG)
        entrenador.ci = body.ci
    if body.especialidad is not None:
        entrenador.especialidad = body.especialidad
    if body.telefono is not None:
        entrenador.telefono = body.telefono
    if body.activo is not None:
        usuario.activo = body.activo
    if body.password is not None:
        usuario.password_hash = hash_password(body.password)

    try:
        db.flush()
    except IntegrityError as exc:
        # Carrera de doble-submit contra el índice parcial único de CI.
        db.rollback()
        raise CiEnUso(_CI_EN_USO_MSG) from exc

    # `sucursal_ids` (CONTRATO 4): None = no tocar; [] = limpiar; lista = REEMPLAZA.
    if body.sucursal_ids is not None:
        _resolver_sucursales(
            db,
            org_id=entrenador.org_id,
            entrenador_id=entrenador.id,
            deseadas=body.sucursal_ids,
        )
    # `disciplina_ids` (S4 CONTRATO 3): None = no tocar; [] = limpiar; lista = REEMPLAZA.
    if body.disciplina_ids is not None:
        _resolver_disciplinas(
            db,
            org_id=entrenador.org_id,
            entrenador_id=entrenador.id,
            deseadas=body.disciplina_ids,
        )
    # Sin `db.commit()` aquí (lo hace el llamador): commitear borraría el GUC
    # `app.current_org` y el `_row_por_id` correría sin contexto de tenant
    # (RLS -> 0 filas). Ver nota en `crear`.
    return _row_por_id(db, entrenador_id)
