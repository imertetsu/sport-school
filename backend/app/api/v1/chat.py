"""Routers del chat de WhatsApp (epic chat-whatsapp) — escuela y plataforma.

DOS routers sobre el MISMO servicio (`services/chat_whatsapp`), porque la diferencia
entre las dos consolas no está en la lógica sino en el alcance, y el alcance lo impone
la BD:

- `/whatsapp/...` (escuela, **solo ADMIN**) se encadena a `set_tenant_context`, que fija
  `app.current_org`. La policy de 0028 le deja ver solo los hilos de SU escuela; los
  números aún sin clasificar (`org_id IS NULL`) le son invisibles sin que ningún
  `WHERE` de este módulo intervenga.
- `/plataforma/whatsapp/...` (superadmin) fija `app.whatsapp_inbox = 'ALL'`, el GUC
  exclusivo de las dos tablas del chat. El superadmin NUNCA tiene `app.current_org`
  (ver `require_superadmin`), así que sin esa segunda vía no vería ni su propia
  bandeja; y como el GUC solo lo mira la policy del chat, abrirla NO le abre `pago`,
  `deportista` ni ninguna otra tabla tenant.

Solo la consola de plataforma puede **asignar** un hilo a una escuela: es el paso
manual del epic (una persona conversa con el número nuevo, deduce de qué escuela es y
lo categoriza). La escuela no puede reclamar hilos por su cuenta.

El binario de las imágenes va por endpoint aparte (`/mensajes/{id}/media`) y no
embebido en el JSON del hilo: 200 mensajes con fotos en base64 serían varios MB por
cada refresco de la bandeja.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.org_context import set_current_org_id
from app.core.phone import normalize_bo_phone
from app.core.tenant import CurrentUser, require_role, require_superadmin
from app.models.conversacion_whatsapp import ConversacionWhatsApp
from app.models.mensaje_whatsapp import MensajeWhatsApp
from app.models.organizacion import Organizacion
from app.models.plataforma_admin import PlataformaAdmin
from app.models.usuario import Usuario
from app.schemas.chat import (
    AbrirConversacionIn,
    AsignarEscuelaIn,
    ConversacionItem,
    ConversacionesPage,
    EnviarMensajeIn,
    EnviarMensajeOut,
    HiloOut,
    MensajeItem,
    TutorContactableItem,
)
from app.services import chat_whatsapp as svc
from app.services.deps import get_whatsapp_port

router = APIRouter(prefix="/whatsapp", tags=["chat"])
plataforma_router = APIRouter(prefix="/plataforma/whatsapp", tags=["chat"])


# --------------------------------------------------------------------------- #
# Dependencias de contexto
# --------------------------------------------------------------------------- #
def contexto_bandeja(
    user: CurrentUser = Depends(require_superadmin),
    db: Session = Depends(get_db),
) -> CurrentUser:
    """Superadmin + bandeja COMPLETA abierta en la transacción del request.

    `require_superadmin` a propósito no fija `app.current_org`; aquí se añade el GUC
    del chat (transaction-local, muere con la tx) para que la consola vea todos los
    hilos, incluidos los que aún no tienen escuela.
    """
    svc.fijar_contexto_bandeja(db)
    return user


# --------------------------------------------------------------------------- #
# Mapeo a schemas
# --------------------------------------------------------------------------- #
def _item(conv: ConversacionWhatsApp, org_nombre: str | None) -> ConversacionItem:
    return ConversacionItem(
        id=conv.id,
        telefono=conv.telefono,
        nombre_contacto=conv.nombre_contacto,
        org_id=conv.org_id,
        org_nombre=org_nombre,
        ultimo_mensaje_at=conv.ultimo_mensaje_at,
        ultimo_mensaje_texto=conv.ultimo_mensaje_texto,
        no_leidos=conv.no_leidos or 0,
        ventana_abierta=svc.ventana_abierta(conv),
        # Con escuela detrás siempre se puede escribir: fuera de las 24 h el mensaje
        # sale como plantilla `contacto_escuela` en vez de como texto libre.
        puede_iniciar=conv.org_id is not None,
    )


def _mensaje(msg: MensajeWhatsApp) -> MensajeItem:
    return MensajeItem(
        id=msg.id,
        direccion=msg.direccion,
        tipo=msg.tipo,
        texto=msg.texto,
        # Da igual si la imagen son bytes propios o una referencia por resolver: para la
        # UI la burbuja tiene imagen y la pide al mismo endpoint.
        tiene_media=msg.media is not None or msg.media_ref is not None,
        media_mime=msg.media_mime,
        estado=msg.estado,
        error_detalle=msg.error_detalle,
        enviado_por_nombre=msg.enviado_por_nombre,
        ocurrido_en=msg.ocurrido_en,
    )


def _bandeja(
    db: Session,
    *,
    solo_sin_asignar: bool,
    buscar: str | None,
    org_id: uuid.UUID | None = None,
    cursor_at: datetime | None = None,
    cursor_id: uuid.UUID | None = None,
) -> ConversacionesPage:
    """Una página de la bandeja, ya scopeada por el GUC que fijó el llamador.

    El cursor que se devuelve son los valores del último item; el cliente los manda de
    vuelta para pedir la página siguiente (ver `listar_conversaciones`).
    """
    pagina = svc.listar_conversaciones(
        db,
        solo_sin_asignar=solo_sin_asignar,
        buscar=buscar,
        org_id=org_id,
        cursor_at=cursor_at,
        cursor_id=cursor_id,
    )
    ultimo = pagina.items[-1].conversacion if pagina.items else None
    return ConversacionesPage(
        items=[_item(f.conversacion, f.org_nombre) for f in pagina.items],
        no_leidos_total=svc.total_no_leidos(db),
        hay_mas=pagina.hay_mas,
        cursor_at=ultimo.ultimo_mensaje_at if (ultimo and pagina.hay_mas) else None,
        cursor_id=ultimo.id if (ultimo and pagina.hay_mas) else None,
    )


def _hilo(db: Session, conversacion_id: uuid.UUID) -> HiloOut:
    """Hilo abierto y marcado como leído. 404 si no existe o RLS lo oculta.

    Abrir el chat es lo que limpia el badge, igual que en WhatsApp.
    """
    conv = svc.obtener_conversacion(db, conversacion_id)
    if conv is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Conversación no encontrada"
        )
    org_nombre = _org_nombre(db, conv.org_id)
    mensajes = svc.listar_mensajes(db, conversacion_id=conv.id)
    svc.marcar_leido(db, conv.id)
    conv.no_leidos = 0
    return HiloOut(
        conversacion=_item(conv, org_nombre), mensajes=[_mensaje(m) for m in mensajes]
    )


def _org_nombre(db: Session, org_id: uuid.UUID | None) -> str | None:
    """Nombre de la escuela del hilo (`organizacion` no tiene RLS)."""
    if org_id is None:
        return None
    return db.execute(
        select(Organizacion.nombre).where(Organizacion.id == org_id)
    ).scalar_one_or_none()


def _media(db: Session, mensaje_id: uuid.UUID) -> Response:
    """Devuelve el binario de la imagen del mensaje. 404 si no existe o no tiene.

    Dos vías: los bytes PROPIOS (imágenes entrantes, recibo del comprobante) o una
    REFERENCIA que se resuelve al vuelo (el QR de cobro, que es el mismo en todos los
    recordatorios de la escuela y por eso no se copia en cada uno).

    Se cachea en el navegador: la imagen de un mensaje ya enviado no cambia, y el chat
    la vuelve a pedir en cada refresco de la bandeja. `private` porque es contenido de
    un tenant y no debe quedar en ninguna caché compartida.
    """
    msg = db.execute(
        select(MensajeWhatsApp).where(MensajeWhatsApp.id == mensaje_id)
    ).scalar_one_or_none()
    if msg is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Adjunto no encontrado")

    if msg.media is not None:
        contenido, mime = msg.media, msg.media_mime or "application/octet-stream"
    else:
        resuelto = svc.resolver_media_ref(db, media_ref=msg.media_ref, org_id=msg.org_id)
        if resuelto is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Adjunto no encontrado"
            )
        contenido, mime = resuelto

    return Response(
        content=contenido,
        media_type=mime,
        headers={"Cache-Control": "private, max-age=86400"},
    )


def _responder(
    db: Session, *, conversacion_id: uuid.UUID, texto: str, autor: str | None
) -> EnviarMensajeOut:
    """Escribe en el hilo y devuelve la burbuja registrada. 404 si no existe.

    El nombre de la escuela viaja al servicio porque es un parámetro de la plantilla
    `contacto_escuela`, la vía por la que sale el mensaje cuando la ventana de 24 h está
    cerrada. Sin escuela (hilo sin clasificar en la consola) solo se puede responder
    dentro de la ventana.
    """
    conv = svc.obtener_conversacion(db, conversacion_id)
    if conv is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Conversación no encontrada"
        )
    resultado = svc.enviar_texto(
        db,
        conv=conv,
        texto=texto,
        port=get_whatsapp_port(),
        autor=autor,
        escuela=_org_nombre(db, conv.org_id),
    )
    # `get_db` commitea DESPUÉS de la respuesta; el mensaje ya salió por la red, así
    # que su fila se persiste ahora — incluida la del envío fallido, que es el único
    # rastro de que se intentó.
    db.commit()
    return EnviarMensajeOut(
        enviado=resultado.enviado,
        motivo=resultado.motivo,
        detalle=resultado.detalle,
        mensaje=_mensaje(resultado.mensaje) if resultado.mensaje else None,
    )


# --------------------------------------------------------------------------- #
# Consola de ESCUELA (solo ADMIN) — ve únicamente los hilos de sus tutores
# --------------------------------------------------------------------------- #
@router.get("/conversaciones", response_model=ConversacionesPage)
def listar_conversaciones_escuela(
    buscar: str | None = Query(default=None),
    cursor_at: datetime | None = Query(default=None),
    cursor_id: uuid.UUID | None = Query(default=None),
    _user: CurrentUser = Depends(require_role("ADMIN")),
    db: Session = Depends(get_db),
) -> ConversacionesPage:
    """Bandeja de la escuela, paginada. El alcance lo impone RLS, no un filtro de aquí."""
    return _bandeja(
        db, solo_sin_asignar=False, buscar=buscar, cursor_at=cursor_at, cursor_id=cursor_id
    )


@router.get("/conversaciones/{conversacion_id}", response_model=HiloOut)
def abrir_hilo_escuela(
    conversacion_id: uuid.UUID,
    _user: CurrentUser = Depends(require_role("ADMIN")),
    db: Session = Depends(get_db),
) -> HiloOut:
    """Abre un hilo de la escuela y lo marca como leído. 404 si no es suyo."""
    return _hilo(db, conversacion_id)


@router.post("/conversaciones/{conversacion_id}/mensajes", response_model=EnviarMensajeOut)
def responder_escuela(
    conversacion_id: uuid.UUID,
    body: EnviarMensajeIn,
    user: CurrentUser = Depends(require_role("ADMIN")),
    db: Session = Depends(get_db),
) -> EnviarMensajeOut:
    """Responde al tutor con texto libre (dentro de la ventana de 24 h)."""
    # El adaptador del gateway resuelve la org por ContextVar y las dependencias
    # corren en otro hilo del threadpool que el endpoint sync, así que el ContextVar
    # que fija `set_tenant_context` no llega hasta aquí: se refija en el mismo
    # contexto que llama al puerto (el GUC de RLS sí viaja, va en la sesión de BD).
    set_current_org_id(user.org_id)
    autor = db.execute(
        select(Usuario.nombre).where(Usuario.id == uuid.UUID(user.user_id))
    ).scalar_one_or_none()
    return _responder(db, conversacion_id=conversacion_id, texto=body.texto, autor=autor)


@router.get("/tutores", response_model=list[TutorContactableItem])
def listar_tutores_escuela(
    buscar: str | None = Query(default=None),
    _user: CurrentUser = Depends(require_role("ADMIN")),
    db: Session = Depends(get_db),
) -> list[TutorContactableItem]:
    """Agenda: tutores de la escuela a los que se les puede escribir.

    Existe porque la bandeja solo muestra hilos YA abiertos, y un hilo solo nace cuando
    el tutor escribe primero. Sin esta lista la escuela no tiene forma de iniciar el
    contacto con la mayoría de sus familias.

    El alcance lo pone RLS sobre `tutor`; se omiten los teléfonos que no normalizan a
    E.164 porque no se les podría enviar.
    """
    return [
        TutorContactableItem(
            tutor_id=t.tutor_id,
            nombres=t.nombres,
            telefono=t.telefono,
            deportistas=t.deportistas,
            conversacion_id=t.conversacion_id,
        )
        for t in svc.listar_tutores_contactables(db, buscar=buscar)
    ]


@router.post("/conversaciones/abrir", response_model=HiloOut)
def abrir_conversacion_escuela(
    body: AbrirConversacionIn,
    user: CurrentUser = Depends(require_role("ADMIN")),
    db: Session = Depends(get_db),
) -> HiloOut:
    """Abre (o crea) el hilo con un tutor de la escuela y lo devuelve listo para escribir.

    403 si el número NO es de un tutor de esta escuela: es el límite que pediste — una
    escuela solo puede escribirle a sus propios contactos, nunca a un número suelto.
    409 si ese número ya está en conversación con OTRA escuela (pasa con un tutor dado
    de alta en dos), porque WhatsApp tiene un único hilo por número y no se puede
    partir en dos sin mezclar mensajes ajenos.
    """
    telefono = normalize_bo_phone(body.telefono)
    if telefono is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="El teléfono no tiene un formato válido",
        )
    if not svc.es_tutor_de_la_escuela(db, telefono):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Ese número no está registrado como tutor de tu escuela",
        )

    conv = svc.abrir_conversacion(db, telefono=telefono, org_id=uuid.UUID(user.org_id))
    if conv is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Ese número ya tiene una conversación asignada a otra escuela",
        )
    db.commit()  # `get_db` commitea tras la respuesta; el hilo ya debe existir
    return _hilo(db, conv.id)


@router.get("/mensajes/{mensaje_id}/media")
def media_escuela(
    mensaje_id: uuid.UUID,
    _user: CurrentUser = Depends(require_role("ADMIN")),
    db: Session = Depends(get_db),
) -> Response:
    """Imagen adjunta de un mensaje de la escuela. 404 si no es suyo o no tiene."""
    return _media(db, mensaje_id)


# --------------------------------------------------------------------------- #
# Consola de PLATAFORMA (superadmin) — ve TODO, incluidos los sin clasificar
# --------------------------------------------------------------------------- #
@plataforma_router.get("/conversaciones", response_model=ConversacionesPage)
def listar_conversaciones_plataforma(
    sin_asignar: bool = Query(default=False),
    org_id: uuid.UUID | None = Query(default=None),
    buscar: str | None = Query(default=None),
    cursor_at: datetime | None = Query(default=None),
    cursor_id: uuid.UUID | None = Query(default=None),
    _user: CurrentUser = Depends(contexto_bandeja),
    db: Session = Depends(get_db),
) -> ConversacionesPage:
    """Bandeja completa, paginada y acotable.

    La consola ve los hilos de TODAS las escuelas, así que sin filtros la lista crece
    sin techo: `sin_asignar=true` deja solo la cola por clasificar y `org_id` acota a
    una escuela. Ninguno de los dos amplía lo que se puede ver — eso lo fija el GUC.
    """
    return _bandeja(
        db,
        solo_sin_asignar=sin_asignar,
        buscar=buscar,
        org_id=org_id,
        cursor_at=cursor_at,
        cursor_id=cursor_id,
    )


@plataforma_router.get("/conversaciones/{conversacion_id}", response_model=HiloOut)
def abrir_hilo_plataforma(
    conversacion_id: uuid.UUID,
    _user: CurrentUser = Depends(contexto_bandeja),
    db: Session = Depends(get_db),
) -> HiloOut:
    """Abre cualquier hilo (de una escuela o sin clasificar) y lo marca como leído."""
    return _hilo(db, conversacion_id)


@plataforma_router.post(
    "/conversaciones/{conversacion_id}/mensajes", response_model=EnviarMensajeOut
)
def responder_plataforma(
    conversacion_id: uuid.UUID,
    body: EnviarMensajeIn,
    user: CurrentUser = Depends(contexto_bandeja),
    db: Session = Depends(get_db),
) -> EnviarMensajeOut:
    """Responde desde la consola — así se averigua de qué escuela es un número nuevo."""
    autor = db.execute(
        select(PlataformaAdmin.nombre).where(PlataformaAdmin.id == uuid.UUID(user.user_id))
    ).scalar_one_or_none()
    return _responder(db, conversacion_id=conversacion_id, texto=body.texto, autor=autor)


@plataforma_router.post(
    "/conversaciones/{conversacion_id}/asignar", response_model=ConversacionItem
)
def asignar_escuela(
    conversacion_id: uuid.UUID,
    body: AsignarEscuelaIn,
    _user: CurrentUser = Depends(contexto_bandeja),
    db: Session = Depends(get_db),
) -> ConversacionItem:
    """Categoriza el hilo: lo asigna a una escuela (o lo devuelve a la cola con `null`).

    A partir de aquí la escuela lo ve en SU chat con todo el historial, porque el
    servicio propaga el `org_id` a los mensajes además de a la conversación.
    404 si el hilo no existe; 404 también si la escuela indicada no existe (la FK lo
    rechazaría con un 500 mucho menos claro).
    """
    if body.org_id is not None:
        existe = db.execute(
            select(Organizacion.id).where(Organizacion.id == body.org_id)
        ).scalar_one_or_none()
        if existe is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Escuela no encontrada"
            )

    conv = svc.asignar_org(db, conversacion_id=conversacion_id, org_id=body.org_id)
    if conv is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Conversación no encontrada"
        )
    db.commit()  # `get_db` commitea tras la respuesta; aquí ya devolvemos el estado nuevo
    return _item(conv, _org_nombre(db, conv.org_id))


@plataforma_router.get("/mensajes/{mensaje_id}/media")
def media_plataforma(
    mensaje_id: uuid.UUID,
    _user: CurrentUser = Depends(contexto_bandeja),
    db: Session = Depends(get_db),
) -> Response:
    """Imagen adjunta de cualquier mensaje. 404 si no existe o no tiene."""
    return _media(db, mensaje_id)
