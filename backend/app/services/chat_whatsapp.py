"""Bandeja de conversaciones de WhatsApp (epic chat-whatsapp).

Servicio COMPARTIDO por las dos consolas: la de la escuela (`/whatsapp/...`, ve solo
sus tutores por RLS) y la de plataforma (`/plataforma/whatsapp/...`, ve todo). La
diferencia entre ambas NO está aquí: está en qué GUC fija cada router antes de llamar
(`app.current_org` vs `app.whatsapp_inbox`), y la policy de la migración 0028 hace el
resto. Este módulo nunca filtra por `org_id` a mano.

El número oficial es **uno solo para todas las escuelas** (un WABA, un
`phone_number_id`), así que los tutores de todas escriben al mismo buzón. De ahí el
flujo del epic:

  1. Llega un mensaje de un número → se busca ese teléfono entre TODOS los tutores
     (`whatsapp_tutores_telefonos()`, SECURITY DEFINER: `tutor` está bajo RLS y aquí
     todavía no se sabe en qué escuela mirar).
  2. Si casa con tutores de **una sola** escuela → la conversación nace asignada a ella
     y la escuela la ve en su chat desde el primer mensaje.
  3. Si no casa con nadie —o casa con **varias** escuelas, que es igual de ambiguo—
     queda con `org_id IS NULL`: invisible para toda escuela, visible solo en la
     consola de plataforma, donde una persona conversa y luego la asigna a mano.

**Ventana de 24 h**: Meta solo deja responder texto libre dentro de las 24 h desde el
último mensaje DEL contacto; fuera de ella hace falta una plantilla aprobada (error
131047). El chat es reactivo por naturaleza, así que aquí se comprueba antes de enviar
y se rechaza con un motivo claro en vez de dejar que Meta acepte un mensaje que nunca
llegará.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import NamedTuple

from sqlalchemy import func, select, text, tuple_, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.core.phone import normalize_bo_phone
from app.domain.ports.whatsapp import (
    WhatsAppPort,
    WhatsAppTemplateMessage,
    WhatsAppTextMessage,
)
from app.models.conversacion_whatsapp import ConversacionWhatsApp
from app.models.deportista import Deportista
from app.models.deportista_tutor import DeportistaTutor
from app.models.mensaje_whatsapp import MensajeWhatsApp
from app.models.organizacion import Organizacion
from app.models.tutor import Tutor

logger = logging.getLogger(__name__)

# Ventana de servicio al cliente de Meta: 24 h desde el último mensaje del contacto.
VENTANA_HORAS = 24

# Plantilla con la que la escuela INICIA la conversación (fuera de la ventana de 24 h).
# Params: {{1}} tutor · {{2}} escuela · {{3}} el mensaje que escribió la secretaria.
# La crea `infra/crear-plantilla-contacto.py`; el nombre vive aquí porque es el dominio
# quien decide con qué plantilla se abre un chat.
TEMPLATE_CONTACTO = "contacto_escuela"
TEMPLATE_CONTACTO_LANG = "es"

# Avance MONÓTONO del estado de un saliente: un webhook fuera de orden (Meta no
# garantiza el orden) no debe hacer retroceder un mensaje ya leído a "entregado".
_RANGO_ESTADO: dict[str, int] = {"ENVIADO": 1, "ENTREGADO": 2, "LEIDO": 3, "FALLIDO": 4}

# Estados de Meta → los nuestros.
ESTADO_META: dict[str, str] = {
    "sent": "ENVIADO",
    "delivered": "ENTREGADO",
    "read": "LEIDO",
    "failed": "FALLIDO",
}


def fijar_contexto_bandeja(db: Session) -> None:
    """Abre la bandeja COMPLETA en esta transacción (`app.whatsapp_inbox = 'ALL'`).

    La usan la consola de plataforma (el superadmin no tiene `app.current_org`) y el
    webhook (escribe mensajes de números que aún no tienen escuela). `is_local=true`:
    el GUC muere con la transacción, así que no se filtra a la siguiente request que
    reuse la conexión del pool.

    Este GUC solo lo mira la policy de `conversacion_whatsapp`/`mensaje_whatsapp`;
    abrir la bandeja NO abre ninguna otra tabla tenant.
    """
    db.execute(text("SELECT set_config('app.whatsapp_inbox', 'ALL', true)"))


# --------------------------------------------------------------------------- #
# Resolución de escuela por teléfono
# --------------------------------------------------------------------------- #
def resolver_org_por_telefono(db: Session, telefono_norm: str) -> uuid.UUID | None:
    """Escuela dueña de ese teléfono, o `None` si es desconocido o ambiguo.

    Compara ya NORMALIZADO (`normalize_bo_phone`) contra el teléfono de cada tutor,
    porque en la BD están tal como los tecleó la secretaria (`+591 7...`, `7...`, con
    guiones) y el webhook los trae en E.164. Es la misma comparación que hace
    `comprobantes._tutor_por_telefono`, solo que a través de todas las escuelas.

    Si el número aparece en DOS escuelas, devuelve `None` a propósito: adivinar sería
    peor que dejar que una persona lo clasifique.
    """
    filas = db.execute(text("SELECT org_id, telefono FROM public.whatsapp_tutores_telefonos()")).all()
    orgs = {org_id for org_id, tel in filas if normalize_bo_phone(tel) == telefono_norm}
    if len(orgs) == 1:
        return next(iter(orgs))
    if len(orgs) > 1:
        logger.info(
            "chat whatsapp: teléfono %s aparece en %d escuelas; queda sin asignar",
            telefono_norm,
            len(orgs),
        )
    return None


def nombre_tutor_por_telefono(db: Session, telefono_norm: str) -> str | None:
    """Nombre del tutor con ese teléfono (para etiquetar el hilo), o `None`."""
    filas = db.execute(
        text("SELECT telefono, nombres FROM public.whatsapp_tutores_telefonos()")
    ).all()
    for tel, nombres in filas:
        if normalize_bo_phone(tel) == telefono_norm:
            return nombres
    return None


# --------------------------------------------------------------------------- #
# Conversaciones
# --------------------------------------------------------------------------- #
def _obtener_o_crear_conversacion(
    db: Session, *, telefono_norm: str, ocurrido_en: datetime
) -> ConversacionWhatsApp:
    """Hilo de ese número; lo crea (resolviendo la escuela) si es la primera vez.

    El INSERT va con `ON CONFLICT DO NOTHING` sobre el UNIQUE del teléfono y relee: dos
    mensajes del mismo número entrando a la vez no pueden crear dos hilos.
    """
    conv = db.execute(
        select(ConversacionWhatsApp).where(ConversacionWhatsApp.telefono == telefono_norm)
    ).scalar_one_or_none()
    if conv is not None:
        return conv

    org_id = resolver_org_por_telefono(db, telefono_norm)
    nombre = nombre_tutor_por_telefono(db, telefono_norm) if org_id else None
    db.execute(
        pg_insert(ConversacionWhatsApp)
        .values(
            id=uuid.uuid4(),
            org_id=org_id,
            telefono=telefono_norm,
            nombre_contacto=nombre,
            ultimo_mensaje_at=ocurrido_en,
            no_leidos=0,
        )
        .on_conflict_do_nothing(index_elements=["telefono"])
    )
    conv = db.execute(
        select(ConversacionWhatsApp).where(ConversacionWhatsApp.telefono == telefono_norm)
    ).scalar_one()
    logger.info(
        "chat whatsapp: hilo nuevo %s org=%s", telefono_norm, org_id or "SIN ASIGNAR"
    )
    return conv


def ventana_abierta(conv: ConversacionWhatsApp, *, ahora: datetime | None = None) -> bool:
    """¿Se puede responder con texto libre? (24 h desde el último mensaje del contacto)."""
    if conv.ultimo_entrante_at is None:
        return False
    ref = ahora or datetime.now(UTC)
    return conv.ultimo_entrante_at + timedelta(hours=VENTANA_HORAS) > ref


class ConversacionItem(NamedTuple):
    """Fila de la bandeja: el hilo + el nombre de su escuela (o `None` si sin asignar)."""

    conversacion: ConversacionWhatsApp
    org_nombre: str | None


class TutorContactable(NamedTuple):
    """Tutor de la escuela al que se le puede escribir, con contexto para reconocerlo.

    `deportistas` es lo que hace usable la agenda: la secretaria no busca "Roxana
    Villca", busca "la mamá de Alexia".
    """

    tutor_id: uuid.UUID
    nombres: str
    telefono: str
    deportistas: list[str]
    conversacion_id: uuid.UUID | None


def listar_tutores_contactables(db: Session, *, buscar: str | None = None) -> list[TutorContactable]:
    """Tutores de la escuela con teléfono utilizable, con sus deportistas y su hilo si ya existe.

    El alcance lo pone RLS sobre `tutor` (contexto de la escuela ya fijado), así que esta
    lista NUNCA puede incluir un tutor de otra escuela. Se descartan los teléfonos que no
    normalizan a E.164: no se les podría enviar, y ofrecerlos sería mentir.
    """
    filas = db.execute(
        select(Tutor.id, Tutor.nombres, Tutor.telefono).where(Tutor.telefono.is_not(None))
    ).all()

    # Deportistas por tutor, en una sola consulta (la agenda es una pantalla, no N+1).
    vinculos = db.execute(
        select(
            DeportistaTutor.tutor_id,
            Deportista.ap_paterno,
            Deportista.ap_materno,
            Deportista.nombres,
        )
        .join(Deportista, Deportista.id == DeportistaTutor.deportista_id)
        .where(Deportista.activo.is_(True))
    ).all()
    por_tutor: dict[uuid.UUID, list[str]] = {}
    for tutor_id, ap_paterno, ap_materno, nombres in vinculos:
        # Mismo orden que el resto del sistema (apellidos primero), para que la agenda
        # se lea igual que las listas de deportistas.
        etiqueta = " ".join(p for p in (ap_paterno, ap_materno, nombres) if p) or nombres
        por_tutor.setdefault(tutor_id, []).append(etiqueta)

    # Hilos ya existentes VISIBLES para esta escuela, indexados por teléfono.
    hilos = {
        c.telefono: c.id
        for c in db.execute(select(ConversacionWhatsApp)).scalars().all()
    }

    patron = (buscar or "").strip().lower()
    salida: list[TutorContactable] = []
    for tutor_id, nombres, telefono in filas:
        norm = normalize_bo_phone(telefono)
        if norm is None:
            continue
        deportistas = sorted(por_tutor.get(tutor_id, []))
        if patron:
            heno = " ".join([nombres or "", telefono or "", norm, *deportistas]).lower()
            if patron not in heno:
                continue
        salida.append(
            TutorContactable(
                tutor_id=tutor_id,
                nombres=nombres,
                telefono=norm,
                deportistas=deportistas,
                conversacion_id=hilos.get(norm),
            )
        )
    salida.sort(key=lambda t: t.nombres.lower())
    return salida


def nombre_tutor_local(db: Session, telefono_norm: str) -> str | None:
    """Nombre del tutor con ese teléfono DENTRO de la escuela del contexto actual.

    Distinto de `nombre_tutor_por_telefono`, que busca en todas las escuelas: aquí la
    consulta va bajo RLS, así que un número dado de alta en dos escuelas devuelve el
    nombre de la que está mirando, no el de la otra.
    """
    filas = db.execute(
        select(Tutor.telefono, Tutor.nombres).where(Tutor.telefono.is_not(None))
    ).all()
    for tel, nombres in filas:
        if normalize_bo_phone(tel) == telefono_norm:
            return nombres
    return None


def es_tutor_de_la_escuela(db: Session, telefono_norm: str) -> bool:
    """¿Ese número está registrado como tutor de la escuela del contexto actual?

    La consulta corre bajo el `app.current_org` del request, así que RLS ya limita
    `tutor` a la escuela: si devuelve algo, el número es suyo. Es la verificación que
    hace legítimo el salto de RLS de `abrir_conversacion`.
    """
    filas = db.execute(select(Tutor.telefono).where(Tutor.telefono.is_not(None))).scalars().all()
    return any(normalize_bo_phone(t) == telefono_norm for t in filas)


def abrir_conversacion(
    db: Session, *, telefono: str, org_id: uuid.UUID
) -> ConversacionWhatsApp | None:
    """Hilo de ese teléfono para esa escuela, creándolo o adoptándolo. `None` si es de otra.

    Delega en `whatsapp_abrir_conversacion` (SECURITY DEFINER, migración 0029) porque la
    escuela NO ve los hilos sin clasificar ni los ajenos: sin ese salto controlado de RLS,
    "busca y si no está, inserta" chocaría con el UNIQUE del teléfono. El llamador debe
    haber verificado ANTES —bajo RLS— que el número es de un tutor suyo.
    """
    telefono_norm = normalize_bo_phone(telefono)
    if telefono_norm is None:
        return None
    nuevo_id = db.execute(
        text("SELECT public.whatsapp_abrir_conversacion(:tel, :org)"),
        {"tel": telefono_norm, "org": str(org_id)},
    ).scalar_one_or_none()
    if nuevo_id is None:
        return None
    # Se relee bajo RLS: si por lo que fuera no fuera visible para esta escuela, que
    # devuelva None en vez de un objeto que no le corresponde.
    conv = obtener_conversacion(db, nuevo_id)
    # La función SQL crea el hilo solo con el teléfono. Sin esto la bandeja mostraría
    # "+59171446922" en vez de "María Pérez", que es ilegible con decenas de hilos.
    if conv is not None and not conv.nombre_contacto:
        nombre = nombre_tutor_local(db, telefono_norm)
        if nombre:
            conv.nombre_contacto = nombre
            db.flush()
    return conv


# Cuántos hilos trae una página de la bandeja. La consola de plataforma ve los de TODAS
# las escuelas, así que sin corte la lista crece sin techo (y el JSON con ella).
PAGINA_BANDEJA = 30


class BandejaPagina(NamedTuple):
    """Una página de la bandeja + el cursor para pedir la siguiente."""

    items: list[ConversacionItem]
    hay_mas: bool


def listar_conversaciones(
    db: Session,
    *,
    solo_sin_asignar: bool = False,
    buscar: str | None = None,
    org_id: uuid.UUID | None = None,
    limite: int = PAGINA_BANDEJA,
    cursor_at: datetime | None = None,
    cursor_id: uuid.UUID | None = None,
) -> BandejaPagina:
    """Página de la bandeja, ordenada por actividad reciente.

    El ALCANCE lo pone RLS, no estos filtros: la escuela ve lo suyo y la consola lo ve
    todo por su GUC. `solo_sin_asignar` y `org_id` son comodidades de la consola para
    acotar lo que ya podía ver — en la escuela no cambian nada.

    Paginación por CURSOR `(ultimo_mensaje_at, id)`, no por offset: una bandeja se
    reordena sola cada vez que llega un mensaje, y con `OFFSET` la segunda página se
    saltaría hilos o repetiría otros. El `id` desempata los que comparten instante (el
    cron manda toda una corrida con el mismo `now()`).
    """
    stmt = (
        select(ConversacionWhatsApp, Organizacion.nombre)
        .join(Organizacion, Organizacion.id == ConversacionWhatsApp.org_id, isouter=True)
        .order_by(ConversacionWhatsApp.ultimo_mensaje_at.desc(), ConversacionWhatsApp.id.desc())
        # Se pide UNO de más para saber si hay página siguiente sin contar el total.
        .limit(limite + 1)
    )
    if solo_sin_asignar:
        stmt = stmt.where(ConversacionWhatsApp.org_id.is_(None))
    elif org_id is not None:
        stmt = stmt.where(ConversacionWhatsApp.org_id == org_id)
    if buscar:
        patron = f"%{buscar.strip()}%"
        stmt = stmt.where(
            ConversacionWhatsApp.telefono.ilike(patron)
            | ConversacionWhatsApp.nombre_contacto.ilike(patron)
        )
    if cursor_at is not None and cursor_id is not None:
        stmt = stmt.where(
            tuple_(ConversacionWhatsApp.ultimo_mensaje_at, ConversacionWhatsApp.id)
            < tuple_(cursor_at, cursor_id)
        )

    filas = db.execute(stmt).all()
    hay_mas = len(filas) > limite
    return BandejaPagina(
        items=[ConversacionItem(conversacion=c, org_nombre=n) for c, n in filas[:limite]],
        hay_mas=hay_mas,
    )


def obtener_conversacion(db: Session, conversacion_id: uuid.UUID) -> ConversacionWhatsApp | None:
    """Hilo por id, o `None` (también si RLS lo oculta: para el llamador es un 404)."""
    return db.execute(
        select(ConversacionWhatsApp).where(ConversacionWhatsApp.id == conversacion_id)
    ).scalar_one_or_none()


def listar_mensajes(
    db: Session, *, conversacion_id: uuid.UUID, limite: int = 200
) -> list[MensajeWhatsApp]:
    """Últimos `limite` mensajes del hilo, devueltos en orden cronológico.

    Se piden los más NUEVOS (`desc` + `limit`) y se invierten en memoria: al abrir un
    chat interesa el final de la conversación, no su principio.
    """
    filas = (
        db.execute(
            select(MensajeWhatsApp)
            .where(MensajeWhatsApp.conversacion_id == conversacion_id)
            .order_by(MensajeWhatsApp.ocurrido_en.desc(), MensajeWhatsApp.created_at.desc())
            .limit(limite)
        )
        .scalars()
        .all()
    )
    return list(reversed(filas))


def marcar_leido(db: Session, conversacion_id: uuid.UUID) -> None:
    """Pone el contador de no leídos a 0 (idempotente)."""
    db.execute(
        update(ConversacionWhatsApp)
        .where(ConversacionWhatsApp.id == conversacion_id)
        .values(no_leidos=0)
    )


def asignar_org(
    db: Session, *, conversacion_id: uuid.UUID, org_id: uuid.UUID | None
) -> ConversacionWhatsApp | None:
    """Asigna (o desasigna, con `None`) la escuela del hilo. `None` si no existe.

    Propaga el `org_id` a TODOS los mensajes en la misma transacción: es la columna de
    RLS de `mensaje_whatsapp`, así que sin esto la escuela vería el hilo en su bandeja
    pero abierto y vacío.
    """
    conv = obtener_conversacion(db, conversacion_id)
    if conv is None:
        return None
    conv.org_id = org_id
    db.execute(
        update(MensajeWhatsApp)
        .where(MensajeWhatsApp.conversacion_id == conversacion_id)
        .values(org_id=org_id)
    )
    db.flush()
    logger.info(
        "chat whatsapp: hilo %s asignado a org=%s", conv.telefono, org_id or "SIN ASIGNAR"
    )
    return conv


# --------------------------------------------------------------------------- #
# Mensajes
# --------------------------------------------------------------------------- #
def _actualizar_cabecera(
    conv: ConversacionWhatsApp, *, ocurrido_en: datetime, preview: str, entrante: bool
) -> None:
    """Refresca el preview/orden de la bandeja (y el no-leídos si es entrante)."""
    if conv.ultimo_mensaje_at is None or ocurrido_en >= conv.ultimo_mensaje_at:
        conv.ultimo_mensaje_at = ocurrido_en
        conv.ultimo_mensaje_texto = preview[:200]
    if entrante:
        conv.ultimo_entrante_at = ocurrido_en
        conv.no_leidos = (conv.no_leidos or 0) + 1


def registrar_entrante(
    db: Session,
    *,
    telefono: str,
    provider_message_id: str | None,
    tipo: str,
    texto: str | None = None,
    media: bytes | None = None,
    media_mime: str | None = None,
    media_nombre: str | None = None,
    nombre_perfil: str | None = None,
    ocurrido_en: datetime | None = None,
) -> MensajeWhatsApp | None:
    """Guarda un mensaje del contacto. `None` si es re-entrega (ya estaba) o teléfono inválido.

    Idempotente por `provider_message_id` (UNIQUE): Meta reintenta el webhook si no
    recibe 200, y el hilo no puede duplicar burbujas.
    """
    telefono_norm = normalize_bo_phone(telefono)
    if telefono_norm is None:
        logger.warning("chat whatsapp: teléfono entrante no normalizable (%s); se ignora", telefono)
        return None

    momento = ocurrido_en or datetime.now(UTC)
    conv = _obtener_o_crear_conversacion(db, telefono_norm=telefono_norm, ocurrido_en=momento)

    if provider_message_id:
        ya = db.execute(
            select(MensajeWhatsApp.id).where(
                MensajeWhatsApp.provider_message_id == provider_message_id
            )
        ).scalar_one_or_none()
        if ya is not None:
            return None

    if nombre_perfil and not conv.nombre_contacto:
        conv.nombre_contacto = nombre_perfil

    msg = MensajeWhatsApp(
        org_id=conv.org_id,
        conversacion_id=conv.id,
        direccion="IN",
        tipo=tipo,
        texto=texto,
        media=media,
        media_mime=media_mime,
        media_nombre=media_nombre,
        provider_message_id=provider_message_id,
        ocurrido_en=momento,
    )
    db.add(msg)
    _actualizar_cabecera(
        conv, ocurrido_en=momento, preview=_preview(tipo, texto, media_nombre), entrante=True
    )
    db.flush()
    return msg


# Lo que se muestra en la bandeja cuando el mensaje no trae texto propio.
_PREVIEW_POR_TIPO = {
    "IMAGEN": "📷 Imagen",
    "DOCUMENTO": "📄 Documento",
    "AUDIO": "🎤 Nota de voz",
    "PLANTILLA": "Plantilla",
}


def _preview(tipo: str, texto: str | None, nombre: str | None = None) -> str:
    """Texto corto para la bandeja; los adjuntos no tienen cuerpo que mostrar.

    En un documento el NOMBRE del archivo es lo más informativo que hay
    (`comprobante-agosto.pdf` dice mucho más que "Documento").
    """
    if texto:
        return texto
    if tipo == "DOCUMENTO" and nombre:
        return f"📄 {nombre}"
    return _PREVIEW_POR_TIPO.get(tipo, "Adjunto")


def registrar_saliente(
    db: Session,
    *,
    conv: ConversacionWhatsApp,
    tipo: str,
    texto: str | None,
    provider_message_id: str | None,
    estado: str,
    error_detalle: str | None = None,
    autor: str | None = None,
    ocurrido_en: datetime | None = None,
    media: bytes | None = None,
    media_mime: str | None = None,
    media_ref: str | None = None,
) -> MensajeWhatsApp:
    """Guarda un mensaje que mandamos nosotros (escuela, consola o el sistema).

    `ocurrido_en` solo se pasa al reconstruir historial (backfill); en el envío normal
    es "ahora". Para la imagen hay DOS vías: `media` guarda los bytes (recibo del
    comprobante, único por pago) y `media_ref` apunta a una imagen que ya vive en otro
    lado (el QR de cobro, idéntico en todos los recordatorios de la escuela).
    """
    momento = ocurrido_en or datetime.now(UTC)
    msg = MensajeWhatsApp(
        org_id=conv.org_id,
        conversacion_id=conv.id,
        direccion="OUT",
        tipo=tipo,
        texto=texto,
        media=media,
        media_mime=media_mime,
        media_ref=media_ref,
        provider_message_id=provider_message_id,
        estado=estado,
        error_detalle=error_detalle,
        enviado_por_nombre=autor,
        ocurrido_en=momento,
    )
    db.add(msg)
    _actualizar_cabecera(conv, ocurrido_en=momento, preview=_preview(tipo, texto), entrante=False)
    db.flush()
    return msg


# Etiquetas de quién mandó cada automático. Se ven en la burbuja, así que la
# secretaria distingue de un vistazo lo que salió solo de lo que escribió alguien.
AUTOR_RECORDATORIO = "Recordatorio automático"
AUTOR_COMPROBANTE = "Comprobante de pago"
AUTOR_RECIBO = "Recibo de pago"
AUTOR_AVISO = "Aviso del muro"
AUTOR_DEUDORES = "Resumen de morosos"


def registrar_automatico(
    db: Session,
    *,
    org_id: uuid.UUID,
    telefono: str,
    tipo: str,
    texto: str | None,
    estado: str,
    provider_message_id: str | None = None,
    error_detalle: str | None = None,
    autor: str,
    ocurrido_en: datetime | None = None,
    media: bytes | None = None,
    media_mime: str | None = None,
    media_ref: str | None = None,
) -> MensajeWhatsApp | None:
    """Deja en el chat la burbuja de un mensaje que mandó el SISTEMA. Nunca lanza.

    Es el punto único por el que los cinco emisores automáticos (recordatorio de cuota,
    comprobante, reenvío de recibo, aviso del muro y digest de morosos) aparecen en la
    conversación. Sin esto el chat miente por omisión: el tutor responde "ya pagué" a un
    recordatorio que en la pantalla no existe, y la secretaria no entiende de qué le
    hablan ni sabe si el aviso llegó a salir.

    Abre el hilo si hacía falta (`abrir_conversacion`, que crea o adopta vía la función
    SECURITY DEFINER de 0029), porque a la mayoría de los tutores se les escribe sin que
    hayan escrito nunca.

    **No propaga errores**: si el registro falla, el mensaje YA salió por WhatsApp y
    hacer fallar al emisor sería mucho peor que quedarse sin la burbuja. Devuelve `None`
    y lo loguea.
    """
    try:
        if provider_message_id:
            ya = db.execute(
                select(MensajeWhatsApp.id).where(
                    MensajeWhatsApp.provider_message_id == provider_message_id
                )
            ).scalar_one_or_none()
            if ya is not None:
                return None

        conv = abrir_conversacion(db, telefono=telefono, org_id=org_id)
        if conv is None:
            # Teléfono no normalizable, o hilo que ya pertenece a OTRA escuela (un tutor
            # dado de alta en dos). El envío no se toca; solo no hay dónde pintarlo.
            logger.info(
                "chat whatsapp: sin hilo para %s (org %s); el automático no se registra",
                telefono,
                org_id,
            )
            return None

        return registrar_saliente(
            db,
            conv=conv,
            tipo=tipo,
            texto=texto,
            provider_message_id=provider_message_id,
            estado=estado,
            error_detalle=error_detalle,
            autor=autor,
            ocurrido_en=ocurrido_en,
            media=media,
            media_mime=media_mime,
            media_ref=media_ref,
        )
    except Exception:  # noqa: BLE001 - el mensaje ya salió; la burbuja es lo secundario
        logger.exception("chat whatsapp: no se pudo registrar el automático para %s", telefono)
        return None


def actualizar_estado(
    db: Session, *, provider_message_id: str, estado_meta: str, error_detalle: str | None = None
) -> bool:
    """Avanza el estado de un saliente por su id de Meta. `False` si no es nuestro.

    Solo AVANZA (`ENVIADO < ENTREGADO < LEIDO < FALLIDO`): los eventos de Meta pueden
    llegar desordenados y un `delivered` tardío no debe borrar un `read` ya registrado.
    """
    estado = ESTADO_META.get(estado_meta)
    if estado is None:
        return False
    msg = db.execute(
        select(MensajeWhatsApp).where(MensajeWhatsApp.provider_message_id == provider_message_id)
    ).scalar_one_or_none()
    if msg is None:
        return False
    if _RANGO_ESTADO.get(estado, 0) <= _RANGO_ESTADO.get(msg.estado or "", 0):
        return True
    msg.estado = estado
    if error_detalle:
        msg.error_detalle = error_detalle
    db.flush()
    return True


@dataclass(frozen=True)
class EnvioResult:
    """Resultado de escribir en el chat.

    `motivo` ∈ {ok, ventana_expirada, texto_largo_para_plantilla, error_envio}.
    Los dos del medio NO son fallos del sistema, son límites de WhatsApp:
    - `ventana_expirada`: pasaron 24 h desde el último mensaje del contacto y no hay
      escuela con la que abrir por plantilla (caso del superadmin en un hilo sin asignar).
    - `texto_largo_para_plantilla`: el mensaje no entra como parámetro de plantilla.
    """

    enviado: bool
    motivo: str
    mensaje: MensajeWhatsApp | None = None
    detalle: str | None = None


# Tope del texto que puede viajar DENTRO de una plantilla. Meta corta los parámetros
# bastante antes que el cuerpo de un mensaje libre; se deja margen para el saludo fijo.
MAX_PARAM_PLANTILLA = 900


def _param_plantilla(texto: str) -> str:
    """Aplana un texto para que Meta lo acepte como parámetro de plantilla.

    Meta RECHAZA los parámetros con saltos de línea, tabulaciones o más de 4 espacios
    seguidos (error "param contains new-line characters"). El mensaje que escribe la
    secretaria sí puede tener saltos, así que se colapsan a espacios: se pierde el
    formato, no el contenido — y solo en el mensaje de apertura, porque a partir de la
    respuesta del tutor todo va como texto libre.
    """
    return " ".join(texto.split())


def enviar_texto(
    db: Session,
    *,
    conv: ConversacionWhatsApp,
    texto: str,
    port: WhatsAppPort,
    autor: str | None = None,
    escuela: str | None = None,
) -> EnvioResult:
    """Escribe en el hilo y deja la burbuja registrada, eligiendo sola la vía.

    - Ventana ABIERTA (o canal libre) ⇒ texto libre tal cual.
    - Ventana CERRADA + hay escuela ⇒ plantilla `contacto_escuela` con el mismo mensaje.
      Es el único modo de escribirle a un tutor que nunca escribió — el caso normal, no
      la excepción: en Águilas hay 62 tutores y solo un puñado ha escrito alguna vez.
    - Ventana CERRADA + sin escuela ⇒ `ventana_expirada`. Se corta ANTES de llamar a
      Meta, que aceptaría el mensaje y luego lo marcaría `failed` (131047) dejando en el
      chat una burbuja que el tutor nunca vio.

    Quien llama no decide la vía: pasa el texto y, si la conversación pertenece a una
    escuela, su nombre. La regla de las 24 h no debería tener que entenderla una
    secretaria.
    """
    abre_con_plantilla = port.requiere_plantilla() and not ventana_abierta(conv)

    if abre_con_plantilla:
        if not escuela:
            return EnvioResult(enviado=False, motivo="ventana_expirada")
        cuerpo = _param_plantilla(texto)
        if len(cuerpo) > MAX_PARAM_PLANTILLA:
            return EnvioResult(enviado=False, motivo="texto_largo_para_plantilla")
        resultado = port.send_template(
            WhatsAppTemplateMessage(
                to=conv.telefono,
                template_name=TEMPLATE_CONTACTO,
                lang_code=TEMPLATE_CONTACTO_LANG,
                body_params=[conv.nombre_contacto or "familia", escuela, cuerpo],
            )
        )
    else:
        resultado = port.send_text(WhatsAppTextMessage(to=conv.telefono, body=texto))

    msg = registrar_saliente(
        db,
        conv=conv,
        # Se guarda el texto ORIGINAL (con sus saltos) aunque haya salido aplanado: en el
        # chat interesa lo que la persona quiso decir.
        tipo="PLANTILLA" if abre_con_plantilla else "TEXTO",
        texto=texto,
        provider_message_id=resultado.provider_message_id,
        estado="ENVIADO" if resultado.ok else "FALLIDO",
        error_detalle=None if resultado.ok else resultado.error,
        autor=autor,
    )
    if not resultado.ok:
        return EnvioResult(
            enviado=False, motivo="error_envio", mensaje=msg, detalle=resultado.error
        )
    return EnvioResult(enviado=True, motivo="ok", mensaje=msg)


# Valor de `mensaje_whatsapp.media_ref` para "la imagen es el QR de cobro de la escuela
# de este mensaje". Se referencia en vez de copiarse porque es LA MISMA en todos los
# recordatorios de esa escuela (ver migración 0030).
MEDIA_REF_QR = "qr"


def resolver_media_ref(
    db: Session, *, media_ref: str | None, org_id: uuid.UUID | None
) -> tuple[bytes, str] | None:
    """Resuelve una referencia a los bytes reales. `None` si no se puede.

    Va por `whatsapp_qr_de_org` (SECURITY DEFINER) y no por un `SELECT` normal porque
    `qr_cobro` tiene RLS por `app.current_org`, y la consola de plataforma no fija ese
    GUC: sin el salto controlado, la burbuja del QR se vería rota justo en la consola.
    """
    if media_ref != MEDIA_REF_QR or org_id is None:
        return None
    fila = db.execute(
        text("SELECT imagen, mime FROM public.whatsapp_qr_de_org(:o)"), {"o": str(org_id)}
    ).first()
    if fila is None or fila.imagen is None:
        return None
    return bytes(fila.imagen), fila.mime or "image/png"


def total_no_leidos(db: Session) -> int:
    """Suma de no leídos visibles en el alcance actual (badge del menú)."""
    return int(
        db.execute(
            select(func.coalesce(func.sum(ConversacionWhatsApp.no_leidos), 0))
        ).scalar_one()
    )
