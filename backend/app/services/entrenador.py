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
- **editar**: carga el `Entrenador` (+ su `Usuario`) bajo RLS; 404 si no existe.
  Aplica solo los campos provistos (no-None): `nombres/especialidad/disciplinas` en
  el entrenador, `activo` y `password`(hasheada) en el usuario.

No se salta el contexto de tenant; el INSERT corre bajo el `app.current_org` del
admin (sin BYPASSRLS, sin debilitar el fail-closed).
"""

from __future__ import annotations

import uuid

from sqlalchemy import Row, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models.entrenador import Entrenador
from app.models.usuario import Usuario
from app.schemas.entrenador import EntrenadorCreate, EntrenadorUpdate


class EntrenadorError(Exception):
    """Error base de negocio del módulo de entrenadores."""


class EmailEnUso(EntrenadorError):
    """El email ya está en uso (en esta org o en otra) -> 409."""


class EntrenadorNoEncontrado(EntrenadorError):
    """El entrenador no existe (en la org del contexto) -> 404."""


# Fila del join entrenador ⨝ usuario, con el contrato de `EntrenadorOut`.
EntrenadorRow = Row[tuple[Entrenador, Usuario]]


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
    `EmailEnUso` con rollback. Devuelve la fila `(Entrenador, Usuario)` recién creada.
    """
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
        especialidad=body.especialidad,
        disciplinas=body.disciplinas,
    )
    db.add(entrenador)
    db.flush()
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

    `nombres/especialidad/disciplinas` van al perfil; `activo` y `password` al usuario
    (baja/reactivación + reset de clave). El `email` no se edita.
    """
    entrenador, usuario = _cargar_entrenador(db, entrenador_id)

    if body.nombres is not None:
        entrenador.nombres = body.nombres
    if body.especialidad is not None:
        entrenador.especialidad = body.especialidad
    if body.disciplinas is not None:
        entrenador.disciplinas = body.disciplinas
    if body.activo is not None:
        usuario.activo = body.activo
    if body.password is not None:
        usuario.password_hash = hash_password(body.password)

    db.flush()
    # Sin `db.commit()` aquí (lo hace el llamador): commitear borraría el GUC
    # `app.current_org` y el `_row_por_id` correría sin contexto de tenant
    # (RLS -> 0 filas). Ver nota en `crear`.
    return _row_por_id(db, entrenador_id)
