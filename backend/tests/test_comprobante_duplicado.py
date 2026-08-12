"""El comprobante no se le manda dos veces al tutor (migración 0031).

Por qué importa tanto como para tener su propio archivo: el comprobante sale por DOS
caminos que no se conocían entre sí —automático al confirmar el pago, y manual desde el
botón "Enviar por WhatsApp"— y el tutor terminaba recibiendo el mismo mensaje dos veces
con segundos de diferencia. Y no hay arreglo posterior: la Cloud API de Meta **no tiene**
endpoint para eliminar un mensaje ya entregado, así que el duplicado se queda en el
teléfono del padre para siempre. La única defensa es cortarlo antes de enviarlo.

Lo que se verifica:
  1. el segundo envío se corta y NO llega al proveedor;
  2. `forzar=True` sí reenvía (el tutor dice que no le llegó: caso legítimo);
  3. un envío FALLIDO no deja el comprobante bloqueado — si no salió, el siguiente
     intento tiene que poder salir sin que nadie fuerce nada.

Se siembra con `owner_engine` (salta RLS) y se ejercita con una Session sobre
`app_engine`. Skip si no hay BD (ver conftest).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.adapters.comprobante.pdf import PdfComprobanteService
from app.domain.ports.whatsapp import (
    WhatsAppImageMessage,
    WhatsAppSendResult,
    WhatsAppTemplateMessage,
    WhatsAppTextMessage,
)
from app.models.organizacion import Organizacion
from app.models.pago import Pago
from app.services import comprobante_whatsapp as svc

pytestmark = pytest.mark.db


class _PortFalso:
    """Puerto que cuenta los envíos: lo que se mide es CUÁNTOS llegan al proveedor."""

    def __init__(self, *, ok: bool = True, error: str | None = None) -> None:
        self._ok = ok
        self._error = error
        self.enviados: list[str] = []

    def requiere_plantilla(self) -> bool:
        # Canal oficial (Meta): es el que usa producción.
        return True

    def send_template(self, msg: WhatsAppTemplateMessage) -> WhatsAppSendResult:
        self.enviados.append(msg.template_name)
        return WhatsAppSendResult(
            ok=self._ok,
            provider_message_id=f"wamid.{uuid.uuid4().hex}" if self._ok else None,
            error=self._error,
        )

    def send_image(self, msg: WhatsAppImageMessage) -> WhatsAppSendResult:
        self.enviados.append("imagen")
        return WhatsAppSendResult(ok=self._ok, provider_message_id=None, error=self._error)

    def send_text(self, msg: WhatsAppTextMessage) -> WhatsAppSendResult:  # pragma: no cover
        raise AssertionError("el comprobante no sale como texto")


@pytest.fixture()
def pago_confirmado(owner_engine: Engine) -> Iterator[dict]:
    """Org con tutor (con teléfono), deportista, cuota y un pago CONFIRMADO con recibo."""
    org = uuid.uuid4()
    suc, dep, tutor, insc, cuota, pago, usuario = (uuid.uuid4() for _ in range(7))
    vence = date(2026, 8, 20)

    with owner_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO organizacion (id, nombre, pais, moneda, modo_cobro_default, "
                "prorratea_primer_periodo, created_at, updated_at) "
                "VALUES (:id,'Escuela Dup (test)','BO','BOB','ANIVERSARIO',true,now(),now())"
            ),
            {"id": str(org)},
        )
        conn.execute(
            text(
                "INSERT INTO usuario (id, org_id, email, password_hash, role, nombre, activo, "
                "created_at, updated_at) "
                "VALUES (:id,:org,:email,'x','ADMIN','Admin',true,now(),now())"
            ),
            {"id": str(usuario), "org": str(org), "email": f"dup_{uuid.uuid4().hex}@test.bo"},
        )
        conn.execute(
            text(
                "INSERT INTO sucursal (id, org_id, nombre, created_at, updated_at) "
                "VALUES (:id,:org,'Central',now(),now())"
            ),
            {"id": str(suc), "org": str(org)},
        )
        conn.execute(
            text(
                "INSERT INTO deportista (id, org_id, sucursal_id, ap_paterno, nombres, activo, "
                "created_at, updated_at) "
                "VALUES (:id,:org,:suc,'VARGAS','BRUNO',true,now(),now())"
            ),
            {"id": str(dep), "org": str(org), "suc": str(suc)},
        )
        conn.execute(
            text(
                "INSERT INTO tutor (id, org_id, nombres, telefono, created_at, updated_at) "
                "VALUES (:id,:org,'Mamá de Bruno','+591 76123456',now(),now())"
            ),
            {"id": str(tutor), "org": str(org)},
        )
        conn.execute(
            text(
                "INSERT INTO deportista_tutor (id, org_id, deportista_id, tutor_id, "
                "parentesco, responsable_pago) VALUES (:id,:org,:dep,:tut,'MADRE',true)"
            ),
            {"id": str(uuid.uuid4()), "org": str(org), "dep": str(dep), "tut": str(tutor)},
        )
        conn.execute(
            text(
                "INSERT INTO inscripcion (id, org_id, deportista_id, estado, monto_mensual, "
                "created_at, updated_at) VALUES (:id,:org,:dep,'ACTIVA',60.00,now(),now())"
            ),
            {"id": str(insc), "org": str(org), "dep": str(dep)},
        )
        conn.execute(
            text(
                "INSERT INTO cuota (id, org_id, inscripcion_id, periodo_inicio, periodo_fin, "
                "vence_el, monto, estado, monto_pagado, generada_en) "
                "VALUES (:id,:org,:ins,:v,:v,:v,60.00,'PAGADO',60.00,now())"
            ),
            {"id": str(cuota), "org": str(org), "ins": str(insc), "v": vence},
        )
        conn.execute(
            text(
                "INSERT INTO pago (id, org_id, metodo, estado, monto, numero_recibo, pagado_en, "
                "registrado_por, created_at) "
                "VALUES (:id,:org,'QR','CONFIRMADO',60.00,'REC-000198',:pagado,:reg,now())"
            ),
            {
                "id": str(pago),
                "org": str(org),
                "pagado": datetime(2026, 8, 11, 12, 0, tzinfo=UTC),
                "reg": str(usuario),
            },
        )
        conn.execute(
            text(
                "INSERT INTO pago_cuota (id, org_id, pago_id, cuota_id, monto_aplicado) "
                "VALUES (:id,:org,:p,:c,60.00)"
            ),
            {"id": str(uuid.uuid4()), "org": str(org), "p": str(pago), "c": str(cuota)},
        )

    yield {"org": org, "pago": pago}

    with owner_engine.begin() as conn:
        for tabla in (
            "mensaje_whatsapp",
            "conversacion_whatsapp",
            "pago_cuota",
            "pago",
            "cuota",
            "inscripcion",
            "deportista_tutor",
            "deportista",
            "tutor",
            "sucursal",
            "usuario",
        ):
            conn.execute(text(f"DELETE FROM {tabla} WHERE org_id = :o"), {"o": str(org)})
        conn.execute(text("DELETE FROM organizacion WHERE id = :o"), {"o": str(org)})


def _enviar(db: Session, datos: dict, port: _PortFalso, *, forzar: bool = False):
    """Llama al servicio como lo hace producción (con el contexto de tenant fijado)."""
    pago = db.execute(select(Pago).where(Pago.id == datos["pago"])).scalar_one()
    org = db.execute(select(Organizacion).where(Organizacion.id == datos["org"])).scalar_one()
    return svc.enviar_comprobante_whatsapp(
        db,
        pago=pago,
        org=org,
        port=port,
        comprobante_svc=PdfComprobanteService(),
        forzar=forzar,
    )


def _sesion(app_engine: Engine, org: uuid.UUID) -> Session:
    db = Session(app_engine, expire_on_commit=False)
    db.execute(text("SELECT set_config('app.current_org', :o, true)"), {"o": str(org)})
    return db


def test_no_se_manda_dos_veces(app_engine: Engine, pago_confirmado: dict) -> None:
    """El segundo envío se corta con `ya_enviado` y NO llega al proveedor."""
    port = _PortFalso()
    with _sesion(app_engine, pago_confirmado["org"]) as db:
        primero = _enviar(db, pago_confirmado, port)
        segundo = _enviar(db, pago_confirmado, port)

    assert primero.enviado is True
    assert segundo.enviado is False
    assert segundo.motivo == "ya_enviado"
    assert segundo.enviado_en is not None, "hay que poder decirle a la secretaria CUÁNDO salió"
    assert len(port.enviados) == 1, "el proveedor no puede recibir el duplicado"


def test_forzar_reenvia(app_engine: Engine, pago_confirmado: dict) -> None:
    """Reenviar sigue siendo posible: es el caso de "el tutor dice que no le llegó"."""
    port = _PortFalso()
    with _sesion(app_engine, pago_confirmado["org"]) as db:
        _enviar(db, pago_confirmado, port)
        reenvio = _enviar(db, pago_confirmado, port, forzar=True)

    assert reenvio.enviado is True
    assert len(port.enviados) == 2


def test_un_fallo_no_bloquea_el_reintento(app_engine: Engine, pago_confirmado: dict) -> None:
    """Solo se marca lo ACEPTADO por el proveedor: si no salió, debe poder reintentarse."""
    fallido = _PortFalso(ok=False, error="timeout")
    bueno = _PortFalso()
    with _sesion(app_engine, pago_confirmado["org"]) as db:
        primero = _enviar(db, pago_confirmado, fallido)
        reintento = _enviar(db, pago_confirmado, bueno)

    assert primero.enviado is False
    assert reintento.enviado is True, "un fallo no puede dejar el comprobante bloqueado"
    assert len(bueno.enviados) == 1


# --------------------------------------------------------------------------- #
# El escenario REAL que reportó la escuela, de punta a punta
#
# "Al registrar el pago apreté 'enviar recibo' y se envió dos veces." No es que el
# boton mande dos: es que el comprobante YA habia salido solo al confirmar el pago,
# y el boton mandaba el segundo sin que nadie lo supiera. Los tests de arriba
# llaman al servicio dos veces a mano; este reproduce la secuencia completa.
# --------------------------------------------------------------------------- #
@pytest.fixture()
def cuota_por_pagar(owner_engine: Engine) -> Iterator[dict]:
    """Org con tutor, deportista y una cuota PENDIENTE lista para cobrar."""
    org = uuid.uuid4()
    suc, dep, tutor, insc, cuota, usuario = (uuid.uuid4() for _ in range(6))

    with owner_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO organizacion (id, nombre, pais, moneda, modo_cobro_default, "
                "prorratea_primer_periodo, created_at, updated_at) "
                "VALUES (:id,'Escuela E2E (test)','BO','BOB','ANIVERSARIO',true,now(),now())"
            ),
            {"id": str(org)},
        )
        conn.execute(
            text(
                "INSERT INTO usuario (id, org_id, email, password_hash, role, nombre, activo, "
                "created_at, updated_at) "
                "VALUES (:id,:org,:email,'x','ADMIN','Admin',true,now(),now())"
            ),
            {"id": str(usuario), "org": str(org), "email": f"e2e_{uuid.uuid4().hex}@test.bo"},
        )
        conn.execute(
            text(
                "INSERT INTO sucursal (id, org_id, nombre, created_at, updated_at) "
                "VALUES (:id,:org,'Central',now(),now())"
            ),
            {"id": str(suc), "org": str(org)},
        )
        conn.execute(
            text(
                "INSERT INTO deportista (id, org_id, sucursal_id, ap_paterno, nombres, activo, "
                "created_at, updated_at) "
                "VALUES (:id,:org,:suc,'FLORES','BRAYAN',true,now(),now())"
            ),
            {"id": str(dep), "org": str(org), "suc": str(suc)},
        )
        conn.execute(
            text(
                "INSERT INTO tutor (id, org_id, nombres, telefono, created_at, updated_at) "
                "VALUES (:id,:org,'Papá de Brayan','+591 76123457',now(),now())"
            ),
            {"id": str(tutor), "org": str(org)},
        )
        conn.execute(
            text(
                "INSERT INTO deportista_tutor (id, org_id, deportista_id, tutor_id, "
                "parentesco, responsable_pago) VALUES (:id,:org,:dep,:tut,'PADRE',true)"
            ),
            {"id": str(uuid.uuid4()), "org": str(org), "dep": str(dep), "tut": str(tutor)},
        )
        conn.execute(
            text(
                "INSERT INTO inscripcion (id, org_id, deportista_id, estado, monto_mensual, "
                "created_at, updated_at) VALUES (:id,:org,:dep,'ACTIVA',60.00,now(),now())"
            ),
            {"id": str(insc), "org": str(org), "dep": str(dep)},
        )
        conn.execute(
            text(
                "INSERT INTO cuota (id, org_id, inscripcion_id, periodo_inicio, periodo_fin, "
                "vence_el, monto, estado, monto_pagado, generada_en) "
                "VALUES (:id,:org,:ins,:v,:v,:v,60.00,'PENDIENTE',0,now())"
            ),
            {"id": str(cuota), "org": str(org), "ins": str(insc), "v": date(2026, 8, 20)},
        )

    yield {"org": org, "cuota": cuota, "usuario": usuario}

    with owner_engine.begin() as conn:
        for tabla in (
            "mensaje_whatsapp",
            "conversacion_whatsapp",
            "pago_cuota",
            "pago",
            "cuota",
            "inscripcion",
            "deportista_tutor",
            "deportista",
            "tutor",
            "sucursal",
            "usuario",
        ):
            conn.execute(text(f"DELETE FROM {tabla} WHERE org_id = :o"), {"o": str(org)})
        conn.execute(text("DELETE FROM organizacion WHERE id = :o"), {"o": str(org)})


def test_registrar_pago_y_apretar_enviar_no_duplica(
    app_engine: Engine, cuota_por_pagar: dict
) -> None:
    """Registrar el pago YA manda el comprobante; el botón después no puede mandar otro."""
    from app.services import pagos as pagos_svc

    with _sesion(app_engine, cuota_por_pagar["org"]) as db:
        # 1) La secretaria registra el pago -> el comprobante sale SOLO.
        pago = pagos_svc.registrar_pago_efectivo(
            db,
            org_id=cuota_por_pagar["org"],
            cuota_ids=[cuota_por_pagar["cuota"]],
            registrado_por=cuota_por_pagar["usuario"],
            comprobante=PdfComprobanteService(),
        )
        db.commit()
        marcado = pago.comprobante_enviado_en

        # 2) Y después aprieta "Enviar por WhatsApp" sin saber que ya salió.
        port = _PortFalso()
        org = db.execute(
            select(Organizacion).where(Organizacion.id == cuota_por_pagar["org"])
        ).scalar_one()
        boton = svc.enviar_comprobante_whatsapp(
            db, pago=pago, org=org, port=port, comprobante_svc=PdfComprobanteService()
        )

    assert marcado is not None, "el envío automático al confirmar debe dejar la marca"
    assert boton.enviado is False
    assert boton.motivo == "ya_enviado"
    assert port.enviados == [], "el tutor NO puede recibir el segundo comprobante"


def test_el_pago_informa_como_le_fue_al_recibo(
    app_engine: Engine, cuota_por_pagar: dict
) -> None:
    """El resultado del envío viaja pegado al pago: sin eso la pantalla no puede avisar.

    Era el envío MUDO lo que hacía que la secretaria apretara "Enviar por WhatsApp"
    después de cobrar. El candado corta el duplicado; esto es para que no llegue a
    intentarlo.
    """
    from app.services import pagos as pagos_svc

    with _sesion(app_engine, cuota_por_pagar["org"]) as db:
        pago = pagos_svc.registrar_pago_efectivo(
            db,
            org_id=cuota_por_pagar["org"],
            cuota_ids=[cuota_por_pagar["cuota"]],
            registrado_por=cuota_por_pagar["usuario"],
            comprobante=PdfComprobanteService(),
        )
        db.commit()
        envio = getattr(pago, "envio_recibo", None)

    assert envio is not None, "el pago tiene que decir si el recibo salió"
    assert envio.enviado is True
    assert envio.motivo == "ok"


def test_sin_telefono_el_pago_lo_informa(app_engine: Engine, cuota_por_pagar: dict) -> None:
    """Si el tutor no tiene teléfono, la pantalla debe poder decir POR QUÉ no salió."""
    from app.services import pagos as pagos_svc

    with _sesion(app_engine, cuota_por_pagar["org"]) as db:
        db.execute(text("UPDATE tutor SET telefono = NULL"))
        db.flush()
        pago = pagos_svc.registrar_pago_efectivo(
            db,
            org_id=cuota_por_pagar["org"],
            cuota_ids=[cuota_por_pagar["cuota"]],
            registrado_por=cuota_por_pagar["usuario"],
            comprobante=PdfComprobanteService(),
        )
        db.commit()
        envio = getattr(pago, "envio_recibo", None)

    assert envio is not None
    assert envio.enviado is False
    assert envio.motivo == "sin_telefono", "el motivo tiene que ser accionable, no genérico"
