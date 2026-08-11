"""Tests del chat de WhatsApp (epic chat-whatsapp).

Lo que se verifica, en orden de importancia:

1. **Aislamiento** — la escuela A no ve el hilo de la escuela B NI el de un número sin
   clasificar. Es la razón de ser de la migración 0028 y lo único que no se puede
   comprobar leyendo el código: el `org_id IS NULL` invisible sale de que la policy
   exige TRUE y `NULL = uuid` da NULL. Se ejercita contra la BD real con el rol
   `latinosport_app` (NOBYPASSRLS), no con mocks.
2. **Clasificación automática** — un mensaje de un tutor conocido abre el hilo ya
   asignado a su escuela; uno de un número desconocido queda sin asignar (y solo lo ve
   la consola). Un número que aparece en DOS escuelas también queda sin asignar: es
   ambiguo y adivinar sería peor.
3. **Asignación manual** — al categorizar el hilo, el `org_id` se propaga a los
   mensajes; sin eso la escuela vería el chat en su bandeja pero abierto y vacío.
4. **Ventana de 24 h** — fuera de ella el canal oficial no admite texto libre y el
   envío se corta ANTES de llamar a Meta.
5. **Idempotencia y estados** — la re-entrega del webhook no duplica burbujas, y un
   evento tardío no hace retroceder un mensaje ya leído.

Se siembra con `owner_engine` (salta RLS) y se ejercita con Sessions sobre
`app_engine`. Skip si no hay BD (ver conftest).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.domain.ports.whatsapp import (
    WhatsAppImageMessage,
    WhatsAppSendResult,
    WhatsAppTemplateMessage,
    WhatsAppTextMessage,
)
from app.services import chat_whatsapp as svc

pytestmark = pytest.mark.db

# Teléfonos de la siembra. El del tutor de A va en formato "humano" (como lo teclea la
# secretaria) y entra por el webhook en E.164: el match tiene que normalizar los dos
# lados, que es justo lo que se prueba.
TEL_TUTOR_A_HUMANO = "+591 70000001"
TEL_TUTOR_A_E164 = "59170000001"
TEL_TUTOR_B_E164 = "59170000002"
TEL_DESCONOCIDO = "59179999999"
TEL_AMBIGUO = "59170000003"


class _PortFalso:
    """Puerto de WhatsApp de prueba: registra los envíos y responde lo que se le diga.

    `requiere_plantilla` es el interruptor que distingue el canal oficial (Meta, con
    ventana de 24 h) del libre.
    """

    def __init__(self, *, oficial: bool = True, ok: bool = True, error: str | None = None) -> None:
        self._oficial = oficial
        self._ok = ok
        self._error = error
        self.enviados: list[str] = []
        self.plantillas: list[WhatsAppTemplateMessage] = []

    def requiere_plantilla(self) -> bool:
        return self._oficial

    def send_text(self, msg: WhatsAppTextMessage) -> WhatsAppSendResult:
        self.enviados.append(msg.body)
        return WhatsAppSendResult(
            ok=self._ok,
            provider_message_id=f"wamid.{uuid.uuid4().hex}" if self._ok else None,
            error=self._error,
        )

    def send_template(self, msg: WhatsAppTemplateMessage) -> WhatsAppSendResult:
        """El chat SÍ manda plantillas: es como abre conversación fuera de las 24 h."""
        self.plantillas.append(msg)
        return WhatsAppSendResult(
            ok=self._ok,
            provider_message_id=f"wamid.{uuid.uuid4().hex}" if self._ok else None,
            error=self._error,
        )

    def send_image(self, msg: WhatsAppImageMessage) -> WhatsAppSendResult:  # pragma: no cover
        raise AssertionError("el chat no manda imágenes")


@pytest.fixture()
def escuelas(owner_engine: Engine) -> Iterator[dict]:
    """Dos escuelas con un tutor cada una + un tutor con teléfono repetido en ambas."""
    org_a, org_b = uuid.uuid4(), uuid.uuid4()

    with owner_engine.begin() as conn:
        for org_id, nombre in ((org_a, "Escuela A (test)"), (org_b, "Escuela B (test)")):
            conn.execute(
                text(
                    "INSERT INTO organizacion (id, nombre, pais, moneda, modo_cobro_default, "
                    "prorratea_primer_periodo, created_at, updated_at) "
                    "VALUES (:id,:nom,'BO','BOB','ANIVERSARIO',true,now(),now())"
                ),
                {"id": str(org_id), "nom": nombre},
            )
        tutores = (
            (org_a, "Tutor A", TEL_TUTOR_A_HUMANO),
            (org_b, "Tutor B", TEL_TUTOR_B_E164),
            # El MISMO número dado de alta en las dos escuelas: caso ambiguo.
            (org_a, "Ambiguo A", TEL_AMBIGUO),
            (org_b, "Ambiguo B", TEL_AMBIGUO),
        )
        ids_tutor: dict[str, uuid.UUID] = {}
        for org_id, nombres, telefono in tutores:
            tutor_id = uuid.uuid4()
            ids_tutor[nombres] = tutor_id
            conn.execute(
                text(
                    "INSERT INTO tutor (id, org_id, nombres, telefono, created_at, updated_at) "
                    "VALUES (:id,:org,:nom,:tel,now(),now())"
                ),
                {
                    "id": str(tutor_id),
                    "org": str(org_id),
                    "nom": nombres,
                    "tel": telefono,
                },
            )

        # Un deportista a cargo del tutor de A: la agenda se busca por el hijo, no por
        # el nombre del tutor, así que hace falta el vínculo para probarlo.
        sucursal = uuid.uuid4()
        conn.execute(
            text(
                "INSERT INTO sucursal (id, org_id, nombre, created_at, updated_at) "
                "VALUES (:id,:org,'Sucursal',now(),now())"
            ),
            {"id": str(sucursal), "org": str(org_a)},
        )
        deportista = uuid.uuid4()
        conn.execute(
            text(
                "INSERT INTO deportista (id, org_id, sucursal_id, ap_paterno, nombres, "
                "activo, created_at, updated_at) "
                "VALUES (:id,:org,:suc,'COAGUILA','ALEXIA',true,now(),now())"
            ),
            {"id": str(deportista), "org": str(org_a), "suc": str(sucursal)},
        )
        conn.execute(
            text(
                "INSERT INTO deportista_tutor (id, org_id, deportista_id, tutor_id, "
                "parentesco, responsable_pago) "
                "VALUES (:id,:org,:dep,:tut,'MADRE',true)"
            ),
            {
                "id": str(uuid.uuid4()),
                "org": str(org_a),
                "dep": str(deportista),
                "tut": str(ids_tutor["Tutor A"]),
            },
        )

    yield {"org_a": org_a, "org_b": org_b, "tutores": ids_tutor}

    with owner_engine.begin() as conn:
        for tabla in (
            "mensaje_whatsapp",
            "conversacion_whatsapp",
            "deportista_tutor",
            "deportista",
            "sucursal",
            "tutor",
        ):
            conn.execute(
                text(f"DELETE FROM {tabla} WHERE org_id IN (:a,:b)"),
                {"a": str(org_a), "b": str(org_b)},
            )
        # Los hilos SIN escuela no tienen org_id: se limpian por teléfono.
        conn.execute(
            text(
                "DELETE FROM mensaje_whatsapp WHERE conversacion_id IN "
                "(SELECT id FROM conversacion_whatsapp WHERE telefono IN (:d,:m))"
            ),
            {"d": TEL_DESCONOCIDO, "m": TEL_AMBIGUO},
        )
        conn.execute(
            text("DELETE FROM conversacion_whatsapp WHERE telefono IN (:d,:m)"),
            {"d": TEL_DESCONOCIDO, "m": TEL_AMBIGUO},
        )
        for org_id in (org_a, org_b):
            conn.execute(text("DELETE FROM organizacion WHERE id = :o"), {"o": str(org_id)})


def _bandeja(app_engine: Engine) -> Session:
    """Session con la bandeja COMPLETA abierta (lo que hace la consola y el webhook)."""
    db = Session(app_engine)
    svc.fijar_contexto_bandeja(db)
    return db


def _escuela(app_engine: Engine, org_id: uuid.UUID) -> Session:
    """Session con el contexto de una escuela (lo que hace `set_tenant_context`)."""
    db = Session(app_engine)
    db.execute(text("SELECT set_config('app.current_org', :o, true)"), {"o": str(org_id)})
    return db


def _commit(db: Session, org_id: uuid.UUID | None = None) -> None:
    """Commit y **repone el GUC** del contexto.

    `set_config(..., is_local => true)` vive solo dentro de la transacción: al
    commitear desaparece, y la siguiente consulta de la MISMA Session ya no vería nada
    (fail-closed, que es justo lo que queremos en producción). En la app cada request
    trae su propia transacción con su contexto; un test que commitea a mitad tiene que
    reponerlo a mano.
    """
    db.commit()
    if org_id is None:
        svc.fijar_contexto_bandeja(db)
    else:
        db.execute(text("SELECT set_config('app.current_org', :o, true)"), {"o": str(org_id)})


# --------------------------------------------------------------------------- #
# 1) Clasificación automática al entrar el primer mensaje
# --------------------------------------------------------------------------- #
def test_tutor_conocido_abre_hilo_ya_asignado(app_engine: Engine, escuelas: dict) -> None:
    """El teléfono del tutor está en formato humano en BD y llega en E.164: igual casa."""
    with _bandeja(app_engine) as db:
        svc.registrar_entrante(
            db, telefono=TEL_TUTOR_A_E164, provider_message_id="wamid.a1", tipo="TEXTO",
            texto="Hola, consulta por la cuota",
        )
        _commit(db)
        conv = svc.listar_conversaciones(db, buscar=TEL_TUTOR_A_E164).items[0].conversacion

    assert conv.org_id == escuelas["org_a"]
    assert conv.nombre_contacto == "Tutor A"
    assert conv.no_leidos == 1


def test_numero_desconocido_queda_sin_asignar(app_engine: Engine, escuelas: dict) -> None:
    """Nadie lo reconoce ⇒ `org_id IS NULL` y la clasificación la hará una persona."""
    with _bandeja(app_engine) as db:
        svc.registrar_entrante(
            db, telefono=TEL_DESCONOCIDO, provider_message_id="wamid.d1", tipo="TEXTO",
            texto="Buenas, quiero información",
        )
        _commit(db)
        conv = svc.listar_conversaciones(db, buscar=TEL_DESCONOCIDO).items[0].conversacion

    assert conv.org_id is None


def test_numero_en_dos_escuelas_queda_sin_asignar(app_engine: Engine, escuelas: dict) -> None:
    """Ambiguo ⇒ tampoco se adivina: va a la cola de la consola."""
    with _bandeja(app_engine) as db:
        svc.registrar_entrante(
            db, telefono=TEL_AMBIGUO, provider_message_id="wamid.m1", tipo="TEXTO", texto="Hola",
        )
        _commit(db)
        conv = svc.listar_conversaciones(db, buscar=TEL_AMBIGUO).items[0].conversacion

    assert conv.org_id is None


# --------------------------------------------------------------------------- #
# 2) Aislamiento (RLS) — el criterio de aceptación del epic
# --------------------------------------------------------------------------- #
def test_escuela_solo_ve_sus_hilos(app_engine: Engine, escuelas: dict) -> None:
    """A ve el suyo; NO ve el de B ni el del número sin clasificar."""
    with _bandeja(app_engine) as db:
        for tel, mid in (
            (TEL_TUTOR_A_E164, "wamid.a2"),
            (TEL_TUTOR_B_E164, "wamid.b2"),
            (TEL_DESCONOCIDO, "wamid.d2"),
        ):
            svc.registrar_entrante(
                db, telefono=tel, provider_message_id=mid, tipo="TEXTO", texto="hola"
            )
        _commit(db)

    with _escuela(app_engine, escuelas["org_a"]) as db:
        telefonos = {f.conversacion.telefono for f in svc.listar_conversaciones(db).items}

    assert TEL_TUTOR_A_E164 in telefonos
    assert TEL_TUTOR_B_E164 not in telefonos, "la escuela A no puede ver hilos de la B"
    assert TEL_DESCONOCIDO not in telefonos, (
        "un número sin clasificar solo se ve en la consola de plataforma"
    )


def test_consola_ve_todo_y_puede_filtrar_los_sin_asignar(
    app_engine: Engine, escuelas: dict
) -> None:
    """La consola ve los tres hilos, y `solo_sin_asignar` deja su cola de trabajo."""
    with _bandeja(app_engine) as db:
        for tel, mid in (
            (TEL_TUTOR_A_E164, "wamid.a3"),
            (TEL_TUTOR_B_E164, "wamid.b3"),
            (TEL_DESCONOCIDO, "wamid.d3"),
        ):
            svc.registrar_entrante(
                db, telefono=tel, provider_message_id=mid, tipo="TEXTO", texto="hola"
            )
        _commit(db)

        todos = {f.conversacion.telefono for f in svc.listar_conversaciones(db).items}
        pendientes = {
            f.conversacion.telefono for f in svc.listar_conversaciones(db, solo_sin_asignar=True).items
        }

    assert {TEL_TUTOR_A_E164, TEL_TUTOR_B_E164, TEL_DESCONOCIDO} <= todos
    assert TEL_DESCONOCIDO in pendientes
    assert TEL_TUTOR_A_E164 not in pendientes


def test_sin_ningun_contexto_la_bandeja_esta_cerrada(app_engine: Engine, escuelas: dict) -> None:
    """Fail-closed: sin `app.current_org` ni `app.whatsapp_inbox`, 0 filas."""
    with _bandeja(app_engine) as db:
        svc.registrar_entrante(
            db, telefono=TEL_TUTOR_A_E164, provider_message_id="wamid.a4", tipo="TEXTO",
            texto="hola",
        )
        _commit(db)

    with Session(app_engine) as db:  # sin fijar ningún GUC
        total = db.execute(text("SELECT count(*) FROM conversacion_whatsapp")).scalar_one()
    assert total == 0


# --------------------------------------------------------------------------- #
# 3) Asignación manual desde la consola
# --------------------------------------------------------------------------- #
def test_asignar_propaga_el_org_a_los_mensajes(app_engine: Engine, escuelas: dict) -> None:
    """Tras categorizar, la escuela ve el hilo CON su historial, no vacío."""
    with _bandeja(app_engine) as db:
        svc.registrar_entrante(
            db, telefono=TEL_DESCONOCIDO, provider_message_id="wamid.d5", tipo="TEXTO",
            texto="¿Tienen fútbol para niños de 8?",
        )
        _commit(db)
        conv = svc.listar_conversaciones(db, buscar=TEL_DESCONOCIDO).items[0].conversacion
        svc.asignar_org(db, conversacion_id=conv.id, org_id=escuelas["org_a"])
        _commit(db)
        conv_id = conv.id

    with _escuela(app_engine, escuelas["org_a"]) as db:
        visible = svc.obtener_conversacion(db, conv_id)
        assert visible is not None, "tras asignar, la escuela debe ver el hilo"
        mensajes = svc.listar_mensajes(db, conversacion_id=conv_id)

    assert [m.texto for m in mensajes] == ["¿Tienen fútbol para niños de 8?"], (
        "el historial debe viajar con el hilo (org_id propagado a los mensajes)"
    )


def test_desasignar_devuelve_el_hilo_a_la_cola(app_engine: Engine, escuelas: dict) -> None:
    """Categorizar mal tiene arreglo: `org_id=None` lo saca de la escuela."""
    with _bandeja(app_engine) as db:
        svc.registrar_entrante(
            db, telefono=TEL_DESCONOCIDO, provider_message_id="wamid.d6", tipo="TEXTO", texto="hola"
        )
        _commit(db)
        conv_id = svc.listar_conversaciones(db, buscar=TEL_DESCONOCIDO).items[0].conversacion.id
        svc.asignar_org(db, conversacion_id=conv_id, org_id=escuelas["org_a"])
        _commit(db)
        svc.asignar_org(db, conversacion_id=conv_id, org_id=None)
        _commit(db)

    with _escuela(app_engine, escuelas["org_a"]) as db:
        assert svc.obtener_conversacion(db, conv_id) is None


# --------------------------------------------------------------------------- #
# 4) Ventana de 24 h
# --------------------------------------------------------------------------- #
def test_canal_oficial_no_envia_fuera_de_la_ventana(app_engine: Engine, escuelas: dict) -> None:
    """Fuera de 24 h se corta ANTES de llamar a Meta (que lo aceptaría y luego fallaría)."""
    port = _PortFalso(oficial=True)
    with _bandeja(app_engine) as db:
        svc.registrar_entrante(
            db, telefono=TEL_TUTOR_A_E164, provider_message_id="wamid.a7", tipo="TEXTO",
            texto="hola", ocurrido_en=datetime.now(UTC) - timedelta(hours=30),
        )
        _commit(db)
        conv = svc.listar_conversaciones(db, buscar=TEL_TUTOR_A_E164).items[0].conversacion
        resultado = svc.enviar_texto(db, conv=conv, texto="respuesta", port=port)

    assert resultado.enviado is False
    assert resultado.motivo == "ventana_expirada"
    assert port.enviados == [], "no se debe gastar la llamada a Meta"


def test_canal_oficial_envia_dentro_de_la_ventana(app_engine: Engine, escuelas: dict) -> None:
    """Dentro de 24 h el texto libre sale y queda la burbuja en ENVIADO."""
    port = _PortFalso(oficial=True)
    with _bandeja(app_engine) as db:
        svc.registrar_entrante(
            db, telefono=TEL_TUTOR_A_E164, provider_message_id="wamid.a8", tipo="TEXTO",
            texto="hola", ocurrido_en=datetime.now(UTC) - timedelta(hours=2),
        )
        _commit(db)
        conv = svc.listar_conversaciones(db, buscar=TEL_TUTOR_A_E164).items[0].conversacion
        resultado = svc.enviar_texto(db, conv=conv, texto="Hola, ya te paso el detalle", port=port)
        _commit(db)
        assert resultado.mensaje is not None
        direccion, estado = resultado.mensaje.direccion, resultado.mensaje.estado

    assert resultado.enviado is True
    assert port.enviados == ["Hola, ya te paso el detalle"]
    assert direccion == "OUT"
    assert estado == "ENVIADO"


def test_canal_libre_no_mira_la_ventana(app_engine: Engine, escuelas: dict) -> None:
    """Sin plantilla obligatoria (canal no oficial) la ventana no aplica."""
    port = _PortFalso(oficial=False)
    with _bandeja(app_engine) as db:
        svc.registrar_entrante(
            db, telefono=TEL_TUTOR_A_E164, provider_message_id="wamid.a9", tipo="TEXTO",
            texto="hola", ocurrido_en=datetime.now(UTC) - timedelta(days=5),
        )
        _commit(db)
        conv = svc.listar_conversaciones(db, buscar=TEL_TUTOR_A_E164).items[0].conversacion
        resultado = svc.enviar_texto(db, conv=conv, texto="hola de nuevo", port=port)
        _commit(db)

    assert resultado.enviado is True


def test_envio_fallido_deja_rastro(app_engine: Engine, escuelas: dict) -> None:
    """Un fallo del proveedor se ve en el chat como burbuja FALLIDO, no se pierde."""
    port = _PortFalso(oficial=True, ok=False, error="http 400: numero invalido")
    with _bandeja(app_engine) as db:
        svc.registrar_entrante(
            db, telefono=TEL_TUTOR_A_E164, provider_message_id="wamid.a10", tipo="TEXTO",
            texto="hola",
        )
        _commit(db)
        conv = svc.listar_conversaciones(db, buscar=TEL_TUTOR_A_E164).items[0].conversacion
        resultado = svc.enviar_texto(db, conv=conv, texto="respuesta", port=port)
        _commit(db)
        # Los atributos se leen DENTRO de la Session: `_commit` los expira y fuera
        # del `with` la instancia ya está desligada.
        assert resultado.mensaje is not None
        estado, detalle = resultado.mensaje.estado, resultado.mensaje.error_detalle

    assert resultado.enviado is False
    assert resultado.motivo == "error_envio"
    assert estado == "FALLIDO"
    assert detalle == "http 400: numero invalido"


# --------------------------------------------------------------------------- #
# 5) Idempotencia del webhook y avance de estados
# --------------------------------------------------------------------------- #
def test_reentrega_del_webhook_no_duplica(app_engine: Engine, escuelas: dict) -> None:
    """Meta reintenta si no recibe 200: el mismo `message_id` no puede dar dos burbujas."""
    with _bandeja(app_engine) as db:
        primero = svc.registrar_entrante(
            db, telefono=TEL_TUTOR_A_E164, provider_message_id="wamid.rep", tipo="TEXTO",
            texto="hola",
        )
        _commit(db)
        repetido = svc.registrar_entrante(
            db, telefono=TEL_TUTOR_A_E164, provider_message_id="wamid.rep", tipo="TEXTO",
            texto="hola",
        )
        _commit(db)
        conv_id = primero.conversacion_id if primero else None
        mensajes = svc.listar_mensajes(db, conversacion_id=conv_id)  # type: ignore[arg-type]

    assert primero is not None
    assert repetido is None
    assert len(mensajes) == 1


def test_el_estado_solo_avanza(app_engine: Engine, escuelas: dict) -> None:
    """Un `delivered` que llega tarde no puede borrar un `read` ya registrado."""
    port = _PortFalso(oficial=True)
    with _bandeja(app_engine) as db:
        svc.registrar_entrante(
            db, telefono=TEL_TUTOR_A_E164, provider_message_id="wamid.a11", tipo="TEXTO",
            texto="hola",
        )
        _commit(db)
        conv = svc.listar_conversaciones(db, buscar=TEL_TUTOR_A_E164).items[0].conversacion
        enviado = svc.enviar_texto(db, conv=conv, texto="respuesta", port=port).mensaje
        assert enviado is not None and enviado.provider_message_id
        mid = enviado.provider_message_id
        _commit(db)

        svc.actualizar_estado(db, provider_message_id=mid, estado_meta="read")
        svc.actualizar_estado(db, provider_message_id=mid, estado_meta="delivered")
        _commit(db)
        db.refresh(enviado)
        estado_final = enviado.estado

    assert estado_final == "LEIDO"


def test_estado_de_mensaje_ajeno_se_ignora(app_engine: Engine, escuelas: dict) -> None:
    """El WABA recibe estados de mensajes que no son nuestros: no deben romper nada."""
    with _bandeja(app_engine) as db:
        assert svc.actualizar_estado(
            db, provider_message_id="wamid.de-otro", estado_meta="failed"
        ) is False


# --------------------------------------------------------------------------- #
# 6) Bandeja: orden, preview y no leídos
# --------------------------------------------------------------------------- #
def test_abrir_el_hilo_limpia_los_no_leidos(app_engine: Engine, escuelas: dict) -> None:
    """Dos entrantes suman 2; `marcar_leido` (al abrir el chat) los baja a 0."""
    with _bandeja(app_engine) as db:
        for mid in ("wamid.n1", "wamid.n2"):
            svc.registrar_entrante(
                db, telefono=TEL_TUTOR_A_E164, provider_message_id=mid, tipo="TEXTO", texto="hola"
            )
        _commit(db)
        conv = svc.listar_conversaciones(db, buscar=TEL_TUTOR_A_E164).items[0].conversacion
        assert conv.no_leidos == 2
        svc.marcar_leido(db, conv.id)
        _commit(db)
        conv = svc.listar_conversaciones(db, buscar=TEL_TUTOR_A_E164).items[0].conversacion

    assert conv.no_leidos == 0


def test_imagen_entrante_deja_preview_legible(app_engine: Engine, escuelas: dict) -> None:
    """Una foto sin caption no puede dejar la bandeja con el preview en blanco."""
    with _bandeja(app_engine) as db:
        svc.registrar_entrante(
            db, telefono=TEL_TUTOR_A_E164, provider_message_id="wamid.img", tipo="IMAGEN",
            texto=None, media=b"\xff\xd8\xff", media_mime="image/jpeg",
        )
        _commit(db)
        conv = svc.listar_conversaciones(db, buscar=TEL_TUTOR_A_E164).items[0].conversacion

    assert conv.ultimo_mensaje_texto == "📷 Imagen"


# --------------------------------------------------------------------------- #
# 7) Agenda: la escuela ESCRIBE PRIMERO (epic chat-whatsapp, fase 2)
#
# Sin esto el chat solo sirve para contestar: un hilo nace cuando el tutor escribe,
# y la mayoría de las familias nunca escribe. La agenda + `abrir_conversacion` son
# lo que permite iniciar el contacto, y el salto de RLS que hacen (la función
# SECURITY DEFINER de 0029) es justo lo que hay que vigilar con tests.
# --------------------------------------------------------------------------- #
def test_agenda_solo_trae_tutores_propios(app_engine: Engine, escuelas: dict) -> None:
    """La escuela A ve a sus tutores y a ninguno de B, con el teléfono ya normalizado."""
    with _escuela(app_engine, escuelas["org_a"]) as db:
        agenda = svc.listar_tutores_contactables(db)

    telefonos = {t.telefono for t in agenda}
    assert TEL_TUTOR_A_E164 in telefonos, "el teléfono humano debe salir normalizado"
    assert TEL_TUTOR_B_E164 not in telefonos, "no puede aparecer un tutor de otra escuela"


def test_agenda_trae_los_deportistas_del_tutor(app_engine: Engine, escuelas: dict) -> None:
    """Se busca "la mamá de Alexia", no "Tutor A": sin el hijo la agenda no se usa."""
    with _escuela(app_engine, escuelas["org_a"]) as db:
        agenda = svc.listar_tutores_contactables(db)
        por_hijo = svc.listar_tutores_contactables(db, buscar="alexia")

    tutor = next(t for t in agenda if t.telefono == TEL_TUTOR_A_E164)
    assert tutor.deportistas == ["COAGUILA ALEXIA"]
    assert [t.telefono for t in por_hijo] == [TEL_TUTOR_A_E164]


def test_abrir_conversacion_crea_el_hilo(app_engine: Engine, escuelas: dict) -> None:
    """Escribirle a un tutor que nunca escribió: el hilo se crea ya asignado a la escuela."""
    with _escuela(app_engine, escuelas["org_a"]) as db:
        conv = svc.abrir_conversacion(db, telefono=TEL_TUTOR_A_E164, org_id=escuelas["org_a"])
        assert conv is not None
        conv_id, org = conv.id, conv.org_id
        _commit(db, escuelas["org_a"])
        visible = svc.obtener_conversacion(db, conv_id)

    assert org == escuelas["org_a"]
    assert visible is not None


def test_abrir_conversacion_es_idempotente(app_engine: Engine, escuelas: dict) -> None:
    """Abrir dos veces devuelve el MISMO hilo (el UNIQUE del teléfono no se puede violar)."""
    with _escuela(app_engine, escuelas["org_a"]) as db:
        primero = svc.abrir_conversacion(db, telefono=TEL_TUTOR_A_E164, org_id=escuelas["org_a"])
        _commit(db, escuelas["org_a"])
        segundo = svc.abrir_conversacion(db, telefono=TEL_TUTOR_A_E164, org_id=escuelas["org_a"])
        _commit(db, escuelas["org_a"])
        assert primero is not None and segundo is not None
        iguales = primero.id == segundo.id

    assert iguales


def test_abrir_adopta_un_hilo_sin_clasificar(app_engine: Engine, escuelas: dict) -> None:
    """Si el número ya escribió y quedó sin asignar, la escuela lo adopta CON su historial.

    El caso real: alguien escribe desde un número que no casa con ningún registro, la
    conversación queda en la cola del superadmin, y después la escuela le escribe desde
    la agenda. No puede aparecer un hilo duplicado ni perderse lo que ya había dicho.
    """
    with _bandeja(app_engine) as db:
        svc.registrar_entrante(
            db, telefono=TEL_TUTOR_A_E164, provider_message_id="wamid.ad1", tipo="TEXTO",
            texto="buenas, una consulta",
        )
        _commit(db)
        # El hilo nació asignado (Tutor A es reconocible); lo dejamos huérfano a mano
        # para reproducir el caso del número que no casó con nadie.
        conv_id = svc.listar_conversaciones(db, buscar=TEL_TUTOR_A_E164).items[0].conversacion.id
        svc.asignar_org(db, conversacion_id=conv_id, org_id=None)
        _commit(db)

    with _escuela(app_engine, escuelas["org_a"]) as db:
        assert svc.obtener_conversacion(db, conv_id) is None, "sin asignar no debe verse"
        adoptado = svc.abrir_conversacion(db, telefono=TEL_TUTOR_A_E164, org_id=escuelas["org_a"])
        _commit(db, escuelas["org_a"])
        assert adoptado is not None and adoptado.id == conv_id
        mensajes = svc.listar_mensajes(db, conversacion_id=conv_id)

    assert [m.texto for m in mensajes] == ["buenas, una consulta"], (
        "al adoptar el hilo la escuela debe recibir también los mensajes previos"
    )


def test_no_se_puede_abrir_el_hilo_de_otra_escuela(app_engine: Engine, escuelas: dict) -> None:
    """El número compartido por dos escuelas: la segunda NO puede colarse en el hilo."""
    with _escuela(app_engine, escuelas["org_a"]) as db:
        conv = svc.abrir_conversacion(db, telefono=TEL_AMBIGUO, org_id=escuelas["org_a"])
        assert conv is not None
        _commit(db, escuelas["org_a"])

    with _escuela(app_engine, escuelas["org_b"]) as db:
        intruso = svc.abrir_conversacion(db, telefono=TEL_AMBIGUO, org_id=escuelas["org_b"])

    assert intruso is None, "el hilo es de A; B debe recibir None (la API lo traduce a 409)"


def test_solo_los_tutores_propios_son_contactables(app_engine: Engine, escuelas: dict) -> None:
    """La verificación que legitima el salto de RLS: B no reconoce al tutor de A."""
    with _escuela(app_engine, escuelas["org_b"]) as db:
        ajeno = svc.es_tutor_de_la_escuela(db, TEL_TUTOR_A_E164)
        propio = svc.es_tutor_de_la_escuela(db, TEL_TUTOR_B_E164)

    assert ajeno is False
    assert propio is True


# --------------------------------------------------------------------------- #
# 8) Fuera de la ventana el mensaje sale por plantilla, no falla
# --------------------------------------------------------------------------- #
def test_fuera_de_ventana_la_escuela_envia_por_plantilla(
    app_engine: Engine, escuelas: dict
) -> None:
    """Un tutor que nunca escribió NO tiene ventana abierta, y aun así se le puede escribir."""
    port = _PortFalso(oficial=True)
    with _escuela(app_engine, escuelas["org_a"]) as db:
        conv = svc.abrir_conversacion(db, telefono=TEL_TUTOR_A_E164, org_id=escuelas["org_a"])
        assert conv is not None
        assert svc.ventana_abierta(conv) is False
        resultado = svc.enviar_texto(
            db, conv=conv, texto="Hola, mañana no hay clase", port=port, escuela="Escuela A (test)"
        )
        _commit(db, escuelas["org_a"])
        assert resultado.mensaje is not None
        tipo = resultado.mensaje.tipo

    assert resultado.enviado is True
    assert tipo == "PLANTILLA"
    assert port.plantillas, "debió salir por send_template, no por texto libre"
    plantilla = port.plantillas[0]
    assert plantilla.template_name == svc.TEMPLATE_CONTACTO
    # {{1}} tutor · {{2}} escuela · {{3}} el mensaje.
    assert plantilla.body_params[1] == "Escuela A (test)"
    assert plantilla.body_params[2] == "Hola, mañana no hay clase"


def test_el_mensaje_viaja_aplanado_en_la_plantilla(app_engine: Engine, escuelas: dict) -> None:
    """Meta rechaza los parámetros con saltos de línea; el texto se guarda igual completo."""
    port = _PortFalso(oficial=True)
    original = "Hola:\n\n- Traer pelota\n- Llegar 10 min antes"
    with _escuela(app_engine, escuelas["org_a"]) as db:
        conv = svc.abrir_conversacion(db, telefono=TEL_TUTOR_A_E164, org_id=escuelas["org_a"])
        assert conv is not None
        resultado = svc.enviar_texto(
            db, conv=conv, texto=original, port=port, escuela="Escuela A (test)"
        )
        _commit(db, escuelas["org_a"])
        assert resultado.mensaje is not None
        guardado = resultado.mensaje.texto

    enviado = port.plantillas[0].body_params[2]
    assert "\n" not in enviado, "un salto de línea en el parámetro hace que Meta lo rechace"
    assert enviado == "Hola: - Traer pelota - Llegar 10 min antes"
    assert guardado == original, "en el chat se ve lo que la persona escribió, con saltos"


def test_texto_demasiado_largo_para_abrir(app_engine: Engine, escuelas: dict) -> None:
    """Mejor decirlo antes que mandar un mensaje que Meta va a rechazar."""
    port = _PortFalso(oficial=True)
    with _escuela(app_engine, escuelas["org_a"]) as db:
        conv = svc.abrir_conversacion(db, telefono=TEL_TUTOR_A_E164, org_id=escuelas["org_a"])
        assert conv is not None
        resultado = svc.enviar_texto(
            db, conv=conv, texto="x" * 1200, port=port, escuela="Escuela A (test)"
        )

    assert resultado.enviado is False
    assert resultado.motivo == "texto_largo_para_plantilla"
    assert port.plantillas == [] and port.enviados == []


def test_con_ventana_abierta_sigue_yendo_texto_libre(app_engine: Engine, escuelas: dict) -> None:
    """Si el tutor escribió hace poco NO se gasta una plantilla: va texto libre."""
    port = _PortFalso(oficial=True)
    with _bandeja(app_engine) as db:
        svc.registrar_entrante(
            db, telefono=TEL_TUTOR_A_E164, provider_message_id="wamid.vt1", tipo="TEXTO",
            texto="hola", ocurrido_en=datetime.now(UTC) - timedelta(hours=1),
        )
        _commit(db)

    with _escuela(app_engine, escuelas["org_a"]) as db:
        conv = svc.abrir_conversacion(db, telefono=TEL_TUTOR_A_E164, org_id=escuelas["org_a"])
        assert conv is not None
        resultado = svc.enviar_texto(
            db, conv=conv, texto="respuesta", port=port, escuela="Escuela A (test)"
        )
        _commit(db, escuelas["org_a"])
        assert resultado.mensaje is not None
        tipo = resultado.mensaje.tipo

    assert resultado.enviado is True
    assert tipo == "TEXTO"
    assert port.enviados == ["respuesta"]
    assert port.plantillas == []


# --------------------------------------------------------------------------- #
# 9) Envíos AUTOMÁTICOS en el chat (recordatorios, comprobantes, avisos…)
#
# Sin esto el chat miente por omisión: el tutor responde "ya pagué" a un
# recordatorio que en la pantalla no existe. Lo que se vigila acá es que la burbuja
# aparezca, que respete el aislamiento por escuela, y —sobre todo— que un fallo al
# registrarla NUNCA rompa el envío, porque el mensaje ya salió por WhatsApp.
# --------------------------------------------------------------------------- #
def test_el_automatico_abre_el_hilo_y_deja_la_burbuja(
    app_engine: Engine, escuelas: dict
) -> None:
    """Un recordatorio a un tutor que nunca escribió crea el hilo y se ve en el chat."""
    with _escuela(app_engine, escuelas["org_a"]) as db:
        msg = svc.registrar_automatico(
            db,
            org_id=escuelas["org_a"],
            telefono=TEL_TUTOR_A_E164,
            tipo="PLANTILLA",
            texto="Tu cuota de AGOSTO vence el 10/08",
            estado="ENVIADO",
            provider_message_id="wamid.auto1",
            autor=svc.AUTOR_RECORDATORIO,
        )
        assert msg is not None
        _commit(db, escuelas["org_a"])
        hilos = svc.listar_conversaciones(db, buscar=TEL_TUTOR_A_E164).items
        mensajes = svc.listar_mensajes(db, conversacion_id=hilos[0].conversacion.id)

    assert len(hilos) == 1
    assert [(m.direccion, m.texto, m.enviado_por_nombre) for m in mensajes] == [
        ("OUT", "Tu cuota de AGOSTO vence el 10/08", svc.AUTOR_RECORDATORIO)
    ]


def test_el_automatico_no_suma_no_leidos(app_engine: Engine, escuelas: dict) -> None:
    """Lo que mandamos nosotros no puede aparecer como pendiente de leer."""
    with _escuela(app_engine, escuelas["org_a"]) as db:
        svc.registrar_automatico(
            db, org_id=escuelas["org_a"], telefono=TEL_TUTOR_A_E164, tipo="PLANTILLA",
            texto="recordatorio", estado="ENVIADO", provider_message_id="wamid.auto2",
            autor=svc.AUTOR_RECORDATORIO,
        )
        _commit(db, escuelas["org_a"])
        conv = svc.listar_conversaciones(db, buscar=TEL_TUTOR_A_E164).items[0].conversacion

    assert conv.no_leidos == 0
    assert conv.ultimo_mensaje_texto == "recordatorio"


def test_el_automatico_respeta_el_aislamiento(app_engine: Engine, escuelas: dict) -> None:
    """La burbuja del recordatorio de A no puede verse desde B."""
    with _escuela(app_engine, escuelas["org_a"]) as db:
        svc.registrar_automatico(
            db, org_id=escuelas["org_a"], telefono=TEL_TUTOR_A_E164, tipo="PLANTILLA",
            texto="cuota de agosto", estado="ENVIADO", provider_message_id="wamid.auto3",
            autor=svc.AUTOR_RECORDATORIO,
        )
        _commit(db, escuelas["org_a"])

    with _escuela(app_engine, escuelas["org_b"]) as db:
        telefonos = {f.conversacion.telefono for f in svc.listar_conversaciones(db).items}

    assert TEL_TUTOR_A_E164 not in telefonos


def test_el_automatico_es_idempotente(app_engine: Engine, escuelas: dict) -> None:
    """Reintentar un envío ya registrado no puede duplicar la burbuja."""
    with _escuela(app_engine, escuelas["org_a"]) as db:
        primero = svc.registrar_automatico(
            db, org_id=escuelas["org_a"], telefono=TEL_TUTOR_A_E164, tipo="PLANTILLA",
            texto="recordatorio", estado="ENVIADO", provider_message_id="wamid.dup",
            autor=svc.AUTOR_RECORDATORIO,
        )
        _commit(db, escuelas["org_a"])
        repetido = svc.registrar_automatico(
            db, org_id=escuelas["org_a"], telefono=TEL_TUTOR_A_E164, tipo="PLANTILLA",
            texto="recordatorio", estado="ENVIADO", provider_message_id="wamid.dup",
            autor=svc.AUTOR_RECORDATORIO,
        )
        _commit(db, escuelas["org_a"])
        conv_id = primero.conversacion_id if primero else None
        mensajes = svc.listar_mensajes(db, conversacion_id=conv_id)  # type: ignore[arg-type]

    assert primero is not None
    assert repetido is None
    assert len(mensajes) == 1


def test_el_automatico_registra_tambien_los_fallidos(
    app_engine: Engine, escuelas: dict
) -> None:
    """Un recordatorio que no llegó tiene que verse; es el único rastro del intento."""
    with _escuela(app_engine, escuelas["org_a"]) as db:
        msg = svc.registrar_automatico(
            db, org_id=escuelas["org_a"], telefono=TEL_TUTOR_A_E164, tipo="PLANTILLA",
            texto="recordatorio", estado="FALLIDO", error_detalle="http 400: numero invalido",
            autor=svc.AUTOR_RECORDATORIO,
        )
        assert msg is not None
        _commit(db, escuelas["org_a"])
        conv_id = msg.conversacion_id
        mensajes = svc.listar_mensajes(db, conversacion_id=conv_id)

    assert [(m.estado, m.error_detalle) for m in mensajes] == [
        ("FALLIDO", "http 400: numero invalido")
    ]


def test_un_telefono_ilegible_no_rompe_el_envio(app_engine: Engine, escuelas: dict) -> None:
    """El mensaje ya salió por WhatsApp: quedarse sin burbuja no puede tumbar el cron."""
    with _escuela(app_engine, escuelas["org_a"]) as db:
        msg = svc.registrar_automatico(
            db, org_id=escuelas["org_a"], telefono="no-es-un-numero", tipo="PLANTILLA",
            texto="recordatorio", estado="ENVIADO", autor=svc.AUTOR_RECORDATORIO,
        )

    assert msg is None, "devuelve None en vez de lanzar"


def test_el_automatico_no_invade_el_hilo_de_otra_escuela(
    app_engine: Engine, escuelas: dict
) -> None:
    """Con el número compartido, el recordatorio de B no puede colarse en el hilo de A."""
    with _escuela(app_engine, escuelas["org_a"]) as db:
        conv = svc.abrir_conversacion(db, telefono=TEL_AMBIGUO, org_id=escuelas["org_a"])
        assert conv is not None
        _commit(db, escuelas["org_a"])

    with _escuela(app_engine, escuelas["org_b"]) as db:
        intruso = svc.registrar_automatico(
            db, org_id=escuelas["org_b"], telefono=TEL_AMBIGUO, tipo="PLANTILLA",
            texto="recordatorio de B", estado="ENVIADO", autor=svc.AUTOR_RECORDATORIO,
        )

    assert intruso is None

    with _escuela(app_engine, escuelas["org_a"]) as db:
        conv_a = svc.listar_conversaciones(db, buscar=TEL_AMBIGUO).items[0].conversacion
        mensajes = svc.listar_mensajes(db, conversacion_id=conv_a.id)

    assert mensajes == [], "el hilo de A no puede recibir el recordatorio de B"


# --------------------------------------------------------------------------- #
# 10) Paginación de la bandeja
#
# La consola de plataforma ve los hilos de TODAS las escuelas: sin corte la lista
# crece sin techo. El cursor va por (ultimo_mensaje_at, id) y no por offset porque
# la bandeja se reordena sola con cada mensaje que entra.
# --------------------------------------------------------------------------- #
def test_la_bandeja_pagina_y_no_repite(app_engine: Engine, escuelas: dict) -> None:
    """Recorrer las páginas devuelve cada hilo UNA vez y termina."""
    telefonos = [f"5917000{n:04d}" for n in range(1000, 1007)]  # 7 hilos
    with _bandeja(app_engine) as db:
        for i, tel in enumerate(telefonos):
            svc.registrar_entrante(
                db, telefono=tel, provider_message_id=f"wamid.pag{i}", tipo="TEXTO",
                texto=f"mensaje {i}",
                # Instantes distintos para que el orden sea determinista.
                ocurrido_en=datetime.now(UTC) - timedelta(minutes=i),
            )
        _commit(db)

        vistos: list[str] = []
        cursor_at = cursor_id = None
        paginas = 0
        while True:
            pagina = svc.listar_conversaciones(
                db, limite=3, cursor_at=cursor_at, cursor_id=cursor_id
            )
            vistos.extend(i.conversacion.telefono for i in pagina.items)
            paginas += 1
            if not pagina.hay_mas:
                break
            ultimo = pagina.items[-1].conversacion
            cursor_at, cursor_id = ultimo.ultimo_mensaje_at, ultimo.id
            assert paginas < 10, "el cursor no avanza: bucle infinito"

    nuestros = [t for t in vistos if t in telefonos]
    assert sorted(nuestros) == sorted(telefonos), "cada hilo debe salir exactamente una vez"
    assert len(vistos) == len(set(vistos)), "ninguna página puede repetir un hilo"

    # Limpieza: estos hilos no tienen org, así que el fixture no los borra.
    with _bandeja(app_engine) as db:
        db.execute(
            text(
                "DELETE FROM mensaje_whatsapp WHERE conversacion_id IN "
                "(SELECT id FROM conversacion_whatsapp WHERE telefono = ANY(:t))"
            ),
            {"t": telefonos},
        )
        db.execute(
            text("DELETE FROM conversacion_whatsapp WHERE telefono = ANY(:t)"), {"t": telefonos}
        )
        db.commit()


def test_la_consola_puede_acotar_a_una_escuela(app_engine: Engine, escuelas: dict) -> None:
    """El filtro por escuela acota lo que YA se podía ver; no amplía nada."""
    with _bandeja(app_engine) as db:
        for tel, mid in ((TEL_TUTOR_A_E164, "wamid.f1"), (TEL_TUTOR_B_E164, "wamid.f2")):
            svc.registrar_entrante(
                db, telefono=tel, provider_message_id=mid, tipo="TEXTO", texto="hola"
            )
        _commit(db)
        solo_a = svc.listar_conversaciones(db, org_id=escuelas["org_a"]).items
        todos = svc.listar_conversaciones(db).items

    assert {i.conversacion.telefono for i in solo_a} == {TEL_TUTOR_A_E164}
    assert {TEL_TUTOR_A_E164, TEL_TUTOR_B_E164} <= {i.conversacion.telefono for i in todos}


# --------------------------------------------------------------------------- #
# 11) La imagen que SALIÓ, visible en la burbuja (migración 0030)
#
# El QR se REFERENCIA en vez de copiarse: es el mismo en todos los recordatorios de
# la escuela, y duplicarlo por mensaje serían megabytes de copias idénticas. Lo que
# hay que vigilar es que la referencia se resuelva, que no se guarden bytes, y que
# el QR de una escuela no se sirva en el hilo de otra.
# --------------------------------------------------------------------------- #
QR_FALSO = b"\x89PNG\r\n\x1a\n-qr-de-la-escuela-A"


@pytest.fixture()
def qr_de_a(owner_engine: Engine, escuelas: dict) -> Iterator[None]:
    """La escuela A tiene QR de cobro cargado; la B no."""
    with owner_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO qr_cobro (id, org_id, imagen, mime, tamano_bytes, "
                "created_at, updated_at) "
                "VALUES (:id,:org,:img,'image/png',:n,now(),now())"
            ),
            {
                "id": str(uuid.uuid4()),
                "org": str(escuelas["org_a"]),
                "img": QR_FALSO,
                "n": len(QR_FALSO),
            },
        )
    yield
    with owner_engine.begin() as conn:
        conn.execute(
            text("DELETE FROM qr_cobro WHERE org_id = :o"), {"o": str(escuelas["org_a"])}
        )


def test_el_recordatorio_referencia_el_qr_sin_copiarlo(
    app_engine: Engine, escuelas: dict, qr_de_a: None
) -> None:
    """La burbuja tiene imagen, pero NO guarda bytes: los resuelve al vuelo."""
    with _escuela(app_engine, escuelas["org_a"]) as db:
        msg = svc.registrar_automatico(
            db, org_id=escuelas["org_a"], telefono=TEL_TUTOR_A_E164, tipo="PLANTILLA",
            texto="Tu cuota vence el 10/08", estado="ENVIADO",
            provider_message_id="wamid.qr1", autor=svc.AUTOR_RECORDATORIO,
            media_ref=svc.MEDIA_REF_QR,
        )
        assert msg is not None
        _commit(db, escuelas["org_a"])
        sin_bytes = msg.media is None
        ref = msg.media_ref
        resuelto = svc.resolver_media_ref(db, media_ref=ref, org_id=escuelas["org_a"])

    assert sin_bytes, "el QR no debe copiarse en el mensaje"
    assert ref == svc.MEDIA_REF_QR
    assert resuelto is not None
    assert resuelto == (QR_FALSO, "image/png")


def test_el_qr_de_una_escuela_no_se_sirve_a_otra(
    app_engine: Engine, escuelas: dict, qr_de_a: None
) -> None:
    """La resolución va por org: la escuela B no tiene QR y no puede recibir el de A."""
    with _escuela(app_engine, escuelas["org_b"]) as db:
        de_b = svc.resolver_media_ref(db, media_ref=svc.MEDIA_REF_QR, org_id=escuelas["org_b"])

    assert de_b is None


def test_sin_qr_cargado_la_referencia_no_resuelve(app_engine: Engine, escuelas: dict) -> None:
    """Escuela sin QR: la burbuja no revienta, simplemente no hay imagen."""
    with _escuela(app_engine, escuelas["org_a"]) as db:
        assert svc.resolver_media_ref(
            db, media_ref=svc.MEDIA_REF_QR, org_id=escuelas["org_a"]
        ) is None


def test_una_referencia_desconocida_se_ignora(app_engine: Engine, escuelas: dict, qr_de_a: None) -> None:
    """Solo se resuelve lo que conocemos; nada de servir bytes por un valor arbitrario."""
    with _escuela(app_engine, escuelas["org_a"]) as db:
        assert svc.resolver_media_ref(db, media_ref="otra-cosa", org_id=escuelas["org_a"]) is None
        assert svc.resolver_media_ref(db, media_ref=None, org_id=escuelas["org_a"]) is None


def test_el_comprobante_si_guarda_su_recibo(app_engine: Engine, escuelas: dict) -> None:
    """El recibo es único por pago y es un documento de dinero: se guarda, no se regenera."""
    recibo = b"\xff\xd8\xff-recibo-jpg"
    with _escuela(app_engine, escuelas["org_a"]) as db:
        msg = svc.registrar_automatico(
            db, org_id=escuelas["org_a"], telefono=TEL_TUTOR_A_E164, tipo="PLANTILLA",
            texto="Comprobante REC-000177", estado="ENVIADO",
            provider_message_id="wamid.rec1", autor=svc.AUTOR_COMPROBANTE,
            media=recibo, media_mime="image/jpeg",
        )
        assert msg is not None
        _commit(db, escuelas["org_a"])
        guardado, mime, ref = msg.media, msg.media_mime, msg.media_ref

    assert bytes(guardado) == recibo
    assert mime == "image/jpeg"
    assert ref is None, "el recibo lleva sus propios bytes, no una referencia"
