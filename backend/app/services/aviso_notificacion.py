"""Notificación de avisos por WhatsApp (epic avisos-whatsapp, C2/C3).

Cuando un ADMIN publica un aviso con `notificar_entrenadores`/`notificar_tutores`, este
módulo resuelve los destinatarios según el **alcance** del aviso y envía la plantilla
pre-aprobada `nuevo_aviso` por WhatsApp (`WhatsAppPort.send_template`, RNF-07: en frío
SOLO plantilla, nunca texto libre).

Resolución de destinatarios (decisión LOCKED 2 de la spec):
- **ORG**: entrenadores = todos los de la org; tutores = todos los tutores con ≥1
  deportista en la org.
- **SUCURSAL**: entrenadores = `entrenador_sucursal` de la sucursal; tutores = tutores de
  deportistas de la sucursal (`Deportista.sucursal_id = sucursal_id`).
- **CATEGORIA**: entrenadores = `entrenador_disciplina` con
  `disciplina_id = categoria.disciplina_id` (categoría sin `disciplina_id` ⇒ 0
  entrenadores); tutores = tutores de deportistas de la categoría
  (`Deportista.categoria_id = categoria_id`).
- **Dedupe por id** (un destinatario una sola vez aunque tenga varios deportistas).
- Solo se envía a quien tenga `telefono` no nulo; los demás se registran `SIN_TELEFONO`
  (no se llama al puerto por ellos).

**Idempotencia (C1):** una fila `aviso_notificacion` por
`(aviso_id, tipo_destinatario, destinatario_id)` (UNIQUE). El INSERT usa
`ON CONFLICT DO NOTHING` (patrón `recordatorio_deudores`): reencolar/reejecutar el envío
del mismo aviso NO produce doble envío ni doble fila. Solo se llama al puerto cuando el
INSERT efectivamente inserta (no había fila previa) y el destinatario tiene teléfono.

Corre bajo el `app.current_org` ya fijado por el caller (RLS); **NO commitea** (sigue la
tx del caller: la task del worker).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.domain.ports.whatsapp import WhatsAppPort, WhatsAppTemplateMessage
from app.models.aviso import Aviso
from app.models.aviso_notificacion import AvisoNotificacion
from app.models.categoria import Categoria
from app.models.deportista import Deportista
from app.models.deportista_tutor import DeportistaTutor
from app.models.entrenador import Entrenador
from app.models.entrenador_disciplina import EntrenadorDisciplina
from app.models.entrenador_sucursal import EntrenadorSucursal
from app.models.organizacion import Organizacion
from app.models.tutor import Tutor

logger = logging.getLogger(__name__)

# Plantilla pre-aprobada (RNF-07) del aviso nuevo. Pendiente de aprobar en Meta para prod.
_TEMPLATE_NUEVO_AVISO = "nuevo_aviso"
_LANG_CODE = "es"
# Límite técnico del cuerpo recortado en el body_param (decisión técnica de backend-dev,
# §decisiones pendientes 2). El cuerpo se trunca con elipsis a este largo.
_CUERPO_MAX = 200

TipoDestinatario = Literal["ENTRENADOR", "TUTOR"]


@dataclass(frozen=True)
class Destinatario:
    """Un destinatario resuelto del aviso (entrenador o tutor), con dedupe por id."""

    destinatario_id: uuid.UUID
    tipo: TipoDestinatario
    telefono: str | None


@dataclass(frozen=True)
class PreviewConteo:
    """Conteo del preview: con/sin teléfono por grupo marcado (sin insertar ni enviar)."""

    entrenadores: int
    tutores: int
    sin_telefono: int

    @property
    def total(self) -> int:
        return self.entrenadores + self.tutores


def _recortar_cuerpo(cuerpo: str, *, limite: int = _CUERPO_MAX) -> str:
    """Recorta el cuerpo a `limite` chars con elipsis (cabe en `body_params`)."""
    cuerpo = cuerpo.strip()
    if len(cuerpo) <= limite:
        return cuerpo
    return cuerpo[: limite - 1].rstrip() + "…"


# --------------------------------------------------------------------------- #
# Resolución de destinatarios (con I/O bajo RLS; sin WHERE org_id)
# --------------------------------------------------------------------------- #
def _entrenadores(
    db: Session,
    *,
    alcance: str,
    sucursal_id: uuid.UUID | None,
    categoria_id: uuid.UUID | None,
) -> list[Destinatario]:
    """Entrenadores destinatarios según el alcance (dedupe por id)."""
    if alcance == "ORG":
        stmt = select(Entrenador.id, Entrenador.telefono)
    elif alcance == "SUCURSAL":
        if sucursal_id is None:
            return []
        stmt = (
            select(Entrenador.id, Entrenador.telefono)
            .join(EntrenadorSucursal, EntrenadorSucursal.entrenador_id == Entrenador.id)
            .where(EntrenadorSucursal.sucursal_id == sucursal_id)
        )
    elif alcance == "CATEGORIA":
        if categoria_id is None:
            return []
        # La disciplina de la categoría define los entrenadores; sin disciplina ⇒ 0.
        disciplina_id = db.execute(
            select(Categoria.disciplina_id).where(Categoria.id == categoria_id)
        ).scalar_one_or_none()
        if disciplina_id is None:
            return []
        stmt = (
            select(Entrenador.id, Entrenador.telefono)
            .join(EntrenadorDisciplina, EntrenadorDisciplina.entrenador_id == Entrenador.id)
            .where(EntrenadorDisciplina.disciplina_id == disciplina_id)
        )
    else:
        return []

    vistos: dict[uuid.UUID, Destinatario] = {}
    for row in db.execute(stmt).all():
        if row.id not in vistos:
            vistos[row.id] = Destinatario(
                destinatario_id=row.id, tipo="ENTRENADOR", telefono=row.telefono or None
            )
    return list(vistos.values())


def _tutores(
    db: Session,
    *,
    alcance: str,
    sucursal_id: uuid.UUID | None,
    categoria_id: uuid.UUID | None,
) -> list[Destinatario]:
    """Tutores destinatarios según el alcance (dedupe por id de tutor)."""
    stmt = (
        select(Tutor.id, Tutor.telefono)
        .join(DeportistaTutor, DeportistaTutor.tutor_id == Tutor.id)
        .join(Deportista, Deportista.id == DeportistaTutor.deportista_id)
    )
    if alcance == "SUCURSAL":
        if sucursal_id is None:
            return []
        stmt = stmt.where(Deportista.sucursal_id == sucursal_id)
    elif alcance == "CATEGORIA":
        if categoria_id is None:
            return []
        stmt = stmt.where(Deportista.categoria_id == categoria_id)
    elif alcance != "ORG":
        return []

    vistos: dict[uuid.UUID, Destinatario] = {}
    for row in db.execute(stmt).all():
        if row.id not in vistos:
            vistos[row.id] = Destinatario(
                destinatario_id=row.id, tipo="TUTOR", telefono=row.telefono or None
            )
    return list(vistos.values())


def resolver_destinatarios(
    db: Session,
    *,
    alcance: str,
    sucursal_id: uuid.UUID | None,
    categoria_id: uuid.UUID | None,
    notificar_entrenadores: bool,
    notificar_tutores: bool,
) -> list[Destinatario]:
    """Destinatarios de los grupos marcados, con dedupe por id (C2).

    Corre bajo el `app.current_org` del caller (RLS): sin `WHERE org_id`. Solo incluye
    los grupos cuyo flag está en `True`. El teléfono puede ser `None` (sin teléfono).
    """
    destinatarios: list[Destinatario] = []
    if notificar_entrenadores:
        destinatarios.extend(
            _entrenadores(db, alcance=alcance, sucursal_id=sucursal_id, categoria_id=categoria_id)
        )
    if notificar_tutores:
        destinatarios.extend(
            _tutores(db, alcance=alcance, sucursal_id=sucursal_id, categoria_id=categoria_id)
        )
    return destinatarios


# --------------------------------------------------------------------------- #
# Preview (cuenta sin enviar ni insertar)
# --------------------------------------------------------------------------- #
def preview_notificacion(
    db: Session,
    *,
    alcance: str,
    sucursal_id: uuid.UUID | None,
    categoria_id: uuid.UUID | None,
    notificar_entrenadores: bool,
    notificar_tutores: bool,
) -> PreviewConteo:
    """Cuenta destinatarios CON teléfono por grupo (los sin teléfono van a `sin_telefono`).

    No inserta en `aviso_notificacion` ni llama al puerto. Reusa el mismo resolver que el
    envío, así los números coinciden con lo que luego materializa el servicio.
    """
    entrenadores = (
        _entrenadores(db, alcance=alcance, sucursal_id=sucursal_id, categoria_id=categoria_id)
        if notificar_entrenadores
        else []
    )
    tutores = (
        _tutores(db, alcance=alcance, sucursal_id=sucursal_id, categoria_id=categoria_id)
        if notificar_tutores
        else []
    )
    con_tel_entrenadores = sum(1 for d in entrenadores if d.telefono is not None)
    con_tel_tutores = sum(1 for d in tutores if d.telefono is not None)
    sin_telefono = sum(1 for d in (*entrenadores, *tutores) if d.telefono is None)
    return PreviewConteo(
        entrenadores=con_tel_entrenadores,
        tutores=con_tel_tutores,
        sin_telefono=sin_telefono,
    )


# --------------------------------------------------------------------------- #
# Envío idempotente
# --------------------------------------------------------------------------- #
def _insert_idempotente(
    db: Session,
    *,
    org_id: uuid.UUID,
    aviso_id: uuid.UUID,
    destinatario: Destinatario,
    estado: str,
) -> uuid.UUID | None:
    """INSERT ON CONFLICT DO NOTHING en `aviso_notificacion` (patrón idempotente).

    Devuelve el `id` insertado, o `None` si ya existía la fila
    `(aviso_id, tipo_destinatario, destinatario_id)`.
    """
    stmt = (
        pg_insert(AvisoNotificacion)
        .values(
            org_id=org_id,
            aviso_id=aviso_id,
            tipo_destinatario=destinatario.tipo,
            destinatario_id=destinatario.destinatario_id,
            canal="WHATSAPP",
            destino=destinatario.telefono,
            estado=estado,
        )
        .on_conflict_do_nothing(index_elements=["aviso_id", "tipo_destinatario", "destinatario_id"])
        .returning(AvisoNotificacion.id)
    )
    inserted = db.execute(stmt).scalar_one_or_none()
    db.flush()
    return inserted


def _nombre_escuela(db: Session, org_id: uuid.UUID) -> str:
    """Nombre de la escuela/org para el body_param (patrón `recordatorios.py`)."""
    org = db.execute(select(Organizacion).where(Organizacion.id == org_id)).scalar_one_or_none()
    return org.nombre if org is not None else "Escuela"


def enviar_aviso_whatsapp(
    db: Session,
    *,
    aviso: Aviso,
    port: WhatsAppPort,
    notificar_entrenadores: bool,
    notificar_tutores: bool,
) -> int:
    """Envía (idempotentemente) el aviso por WhatsApp a los grupos marcados.

    Flujo por destinatario resuelto (dedupe por id):
    1. `estado` de negocio: sin teléfono → `SIN_TELEFONO`; con teléfono → `ENVIADO`.
    2. INSERT idempotente de la fila. Ya existía (mismo aviso/destinatario) ⇒ no reenvía.
    3. Solo si se insertó (era nuevo) y tiene teléfono, llama al puerto: plantilla
       `nuevo_aviso` con `[escuela, titulo, cuerpo_corto]`. Marca `ENVIADO` (con
       `provider_message_id`/`enviado_en`) o `FALLIDO` (con `error`) según el resultado.

    Devuelve cuántos envíos efectivos (`ENVIADO`) se hicieron **en esta llamada**:
    reejecutar el mismo aviso devuelve 0 (idempotente). Corre bajo el `app.current_org`
    del caller (RLS); **NO commitea** (lo hace la task).
    """
    destinatarios = resolver_destinatarios(
        db,
        alcance=aviso.alcance,
        sucursal_id=aviso.sucursal_id,
        categoria_id=aviso.categoria_id,
        notificar_entrenadores=notificar_entrenadores,
        notificar_tutores=notificar_tutores,
    )
    if not destinatarios:
        return 0

    escuela = _nombre_escuela(db, aviso.org_id)
    cuerpo_corto = _recortar_cuerpo(aviso.cuerpo)
    enviados = 0

    for destinatario in destinatarios:
        estado = "SIN_TELEFONO" if destinatario.telefono is None else "ENVIADO"
        inserted_id = _insert_idempotente(
            db,
            org_id=aviso.org_id,
            aviso_id=aviso.id,
            destinatario=destinatario,
            estado=estado,
        )

        # Ya existía (idempotencia) o sin teléfono: no se llama al puerto.
        if inserted_id is None or destinatario.telefono is None:
            continue

        msg = WhatsAppTemplateMessage(
            to=destinatario.telefono,
            template_name=_TEMPLATE_NUEVO_AVISO,
            lang_code=_LANG_CODE,
            body_params=[escuela, aviso.titulo, cuerpo_corto],
            header_image=None,
        )
        result = port.send_template(msg)

        fila = db.get(AvisoNotificacion, inserted_id)
        if fila is not None:
            if result.ok:
                fila.provider_message_id = result.provider_message_id
                fila.enviado_en = datetime.now(UTC)
                enviados += 1
            else:
                fila.estado = "FALLIDO"
                fila.error = result.error
                logger.warning(
                    "aviso_notificacion envío falló aviso=%s dest=%s: %s",
                    aviso.id,
                    destinatario.destinatario_id,
                    result.error,
                )
            db.flush()

    return enviados
