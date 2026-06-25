"""Tests del servicio y la API de comprobantes "Pagos por verificar".

Epic pagos-qr-comprobante (Fase 3). Cubre la DoD del epic en backend:

Servicio (`app.services.comprobantes`):
- `procesar_comprobante_inbound`: crea fila identificada (tutor por teléfono + cuota
  FIFO); idempotente por `message_id` (2x ⇒ 1 fila); teléfono no matchea ⇒
  tutor/cuota None; fija contexto org (la fila respeta RLS).
- `confirmar_comprobante`: reusa `registrar_pago_efectivo` (crea pago, marca cuota);
  confirmar 2x ⇒ no duplica pago (409 idempotente); `transaccion_id_ocr` repetido ⇒
  bloqueado al insertar (se guarda sin él, RNF-06).

API (Bearer ADMIN, RLS):
- subir/ver/borrar QR; pendientes/confirmar/rechazar; RLS (org B no ve A).

Patrón BD idéntico al resto de la suite: `owner_engine` siembra (saltando RLS); una
`Session(app_engine)` ejercita el servicio bajo RLS real fijando `app.current_org`; el
`TestClient` ejercita la API con JWT. El OCR de `procesar_comprobante_inbound` es
best-effort (sin binario de Tesseract devuelve todo None) — los tests NO dependen de él.
"""

from __future__ import annotations

import base64
import io
import os
import uuid
from collections.abc import Iterator
from datetime import date
from decimal import Decimal

import pytest
from app.core.security import create_access_token
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session


# --------------------------------------------------------------------------- #
# Helpers de siembra (con BD, como owner saltando RLS)
# --------------------------------------------------------------------------- #
def _set_org(conn, org: uuid.UUID) -> None:
    conn.execute(text("SELECT set_config('app.current_org', :o, true)"), {"o": str(org)})


def _png_bytes() -> bytes:
    """PNG mínimo válido (1x1) — sirve de QR/comprobante en los tests de subida."""
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (1, 1), (255, 255, 255)).save(buf, format="PNG")
    return buf.getvalue()


def _sembrar_org_tutor_cuota(
    conn,
    *,
    org: uuid.UUID,
    tutor_telefono: str | None,
    monto: Decimal = Decimal("250.00"),
    vence_el: date = date(2026, 5, 10),
) -> dict:
    """Org + sucursal + deportista + (tutor) + inscripción + 1 cuota PENDIENTE con saldo.

    `tutor_telefono=None` ⇒ no se crea tutor (caso "sin identificar"). Devuelve los ids.
    """
    suc = uuid.uuid4()
    al = uuid.uuid4()
    insc = uuid.uuid4()
    cuota = uuid.uuid4()
    admin = uuid.uuid4()

    conn.execute(
        text(
            "INSERT INTO organizacion (id, nombre, pais, moneda, modo_cobro_default, "
            "prorratea_primer_periodo, created_at, updated_at) "
            "VALUES (:id,'Org Comprobante (test)','BO','BOB','ANIVERSARIO',true,now(),now()) "
            "ON CONFLICT (id) DO NOTHING"
        ),
        {"id": str(org)},
    )
    conn.execute(
        text(
            "INSERT INTO usuario (id, org_id, email, password_hash, role, nombre, activo, "
            "created_at, updated_at) "
            "VALUES (:id,:org,:email,'x','ADMIN','Admin',true,now(),now())"
        ),
        {"id": str(admin), "org": str(org), "email": f"admin_{admin.hex}@t.test"},
    )
    conn.execute(
        text(
            "INSERT INTO sucursal (id, org_id, nombre, created_at, updated_at) "
            "VALUES (:id,:org,'Suc',now(),now())"
        ),
        {"id": str(suc), "org": str(org)},
    )
    conn.execute(
        text(
            "INSERT INTO deportista (id, org_id, sucursal_id, nombres, ap_paterno, "
            "created_at, updated_at) VALUES (:id,:org,:suc,'Camila','Rojas',now(),now())"
        ),
        {"id": str(al), "org": str(org), "suc": str(suc)},
    )
    conn.execute(
        text(
            "INSERT INTO inscripcion (id, org_id, deportista_id, fecha_inscripcion, "
            "monto_mensual, estado, created_at, updated_at) "
            "VALUES (:id,:org,:al,:f,:m,'ACTIVA',now(),now())"
        ),
        {"id": str(insc), "org": str(org), "al": str(al), "f": date(2026, 1, 10), "m": monto},
    )
    conn.execute(
        text(
            "INSERT INTO cuota (id, org_id, inscripcion_id, periodo_inicio, periodo_fin, "
            "vence_el, monto, monto_pagado, estado, es_prorrateo, generada_en) "
            "VALUES (:id,:org,:insc,:pi,:pf,:v,:m,0,'PENDIENTE',false,now())"
        ),
        {
            "id": str(cuota),
            "org": str(org),
            "insc": str(insc),
            "pi": date(vence_el.year, vence_el.month, 1),
            "pf": vence_el,
            "v": vence_el,
            "m": monto,
        },
    )

    tutor = None
    if tutor_telefono is not None:
        tutor = uuid.uuid4()
        conn.execute(
            text(
                "INSERT INTO tutor (id, org_id, nombres, telefono, created_at, updated_at) "
                "VALUES (:id,:org,'Maria Rojas',:tel,now(),now())"
            ),
            {"id": str(tutor), "org": str(org), "tel": tutor_telefono},
        )
        conn.execute(
            text(
                "INSERT INTO deportista_tutor (id, org_id, deportista_id, tutor_id, "
                "parentesco, responsable_pago, created_at, updated_at) "
                "VALUES (:id,:org,:al,:tut,'Madre',true,now(),now())"
            ),
            {"id": str(uuid.uuid4()), "org": str(org), "al": str(al), "tut": str(tutor)},
        )

    return {"admin": admin, "suc": suc, "deportista": al, "inscripcion": insc,
            "cuota": cuota, "tutor": tutor, "monto": monto}  # fmt: skip


def _limpiar_org(conn, org: uuid.UUID) -> None:
    for tabla in (
        "comprobante_pendiente",
        "recordatorio_pago",
        "pago_cuota",
        "pago",
        "credito",
        "cuota",
        "inscripcion",
        "deportista_tutor",
        "tutor",
        "deportista",
        "qr_cobro",
        "sucursal",
        "usuario",
    ):
        conn.execute(text(f"DELETE FROM {tabla} WHERE org_id = :o"), {"o": str(org)})
    conn.execute(text("DELETE FROM organizacion WHERE id = :o"), {"o": str(org)})


@pytest.fixture()
def org_identificada(owner_engine: Engine) -> Iterator[dict]:
    """Org con tutor (teléfono `+591 76123456`) + cuota PENDIENTE; limpia al final."""
    org = uuid.uuid4()
    with owner_engine.begin() as conn:
        ids = _sembrar_org_tutor_cuota(conn, org=org, tutor_telefono="+591 76123456")
    yield {"org": org, **ids}
    with owner_engine.begin() as conn:
        _limpiar_org(conn, org)


@pytest.fixture()
def org_sin_tutor(owner_engine: Engine) -> Iterator[dict]:
    """Org SIN tutor (teléfono no matcheará) + cuota PENDIENTE; limpia al final."""
    org = uuid.uuid4()
    with owner_engine.begin() as conn:
        ids = _sembrar_org_tutor_cuota(conn, org=org, tutor_telefono=None)
    yield {"org": org, **ids}
    with owner_engine.begin() as conn:
        _limpiar_org(conn, org)


def _client_or_skip():
    if not os.getenv("DATABASE_URL"):
        pytest.skip("DATABASE_URL no definido; requiere Postgres migrado")
    from app.main import app
    from fastapi.testclient import TestClient

    return TestClient(app)


def _token_admin(org: uuid.UUID, user: uuid.UUID) -> str:
    return create_access_token(user_id=str(user), org_id=str(org), role="ADMIN", sucursal_ids=[])


# =========================================================================== #
# Servicio: procesar_comprobante_inbound
# =========================================================================== #
@pytest.mark.db
def test_inbound_identifica_tutor_y_cuota_fifo(app_engine: Engine, org_identificada: dict) -> None:
    from app.services import comprobantes as svc

    org = org_identificada["org"]
    media = base64.b64encode(_png_bytes()).decode("ascii")

    with Session(app_engine, expire_on_commit=False) as db:
        fila = svc.procesar_comprobante_inbound(
            db,
            org_id=str(org),
            from_telefono="59176123456",  # E.164 del mismo número humano del tutor
            media_b64=media,
            mime="image/png",
            caption="ya pagué",
            message_id="wamid.A1",
        )
        db.commit()
        assert fila is not None
        assert fila.estado == "PENDIENTE"
        assert fila.tutor_id == org_identificada["tutor"]
        assert fila.cuota_sugerida_id == org_identificada["cuota"]  # FIFO (la única)
        assert fila.from_telefono == "59176123456"


@pytest.mark.db
def test_inbound_idempotente_por_message_id(app_engine: Engine, org_identificada: dict) -> None:
    from app.services import comprobantes as svc

    org = org_identificada["org"]
    media = base64.b64encode(_png_bytes()).decode("ascii")

    with Session(app_engine, expire_on_commit=False) as db:
        f1 = svc.procesar_comprobante_inbound(
            db, org_id=str(org), from_telefono="59176123456", media_b64=media,
            mime="image/png", caption=None, message_id="wamid.DUP",
        )  # fmt: skip
        f2 = svc.procesar_comprobante_inbound(
            db, org_id=str(org), from_telefono="59176123456", media_b64=media,
            mime="image/png", caption=None, message_id="wamid.DUP",
        )  # fmt: skip
        db.commit()
        assert f1 is not None and f2 is not None
        assert f1.id == f2.id  # misma fila, no se reinsertó

    with app_engine.begin() as conn:
        _set_org(conn, org)
        n = conn.execute(
            text("SELECT count(*) FROM comprobante_pendiente WHERE message_id = 'wamid.DUP'")
        ).scalar_one()
    assert n == 1


@pytest.mark.db
def test_inbound_sin_match_telefono_tutor_y_cuota_none(
    app_engine: Engine, org_sin_tutor: dict
) -> None:
    from app.services import comprobantes as svc

    org = org_sin_tutor["org"]
    media = base64.b64encode(_png_bytes()).decode("ascii")

    with Session(app_engine, expire_on_commit=False) as db:
        fila = svc.procesar_comprobante_inbound(
            db, org_id=str(org), from_telefono="59170000000", media_b64=media,
            mime="image/png", caption=None, message_id="wamid.NM",
        )  # fmt: skip
        db.commit()
        assert fila is not None
        assert fila.tutor_id is None
        assert fila.cuota_sugerida_id is None


@pytest.mark.db
def test_inbound_respeta_rls(app_engine: Engine, org_identificada: dict) -> None:
    """La fila insertada respeta RLS: sin contexto de org ⇒ 0 filas."""
    from app.services import comprobantes as svc

    org = org_identificada["org"]
    media = base64.b64encode(_png_bytes()).decode("ascii")

    with Session(app_engine, expire_on_commit=False) as db:
        svc.procesar_comprobante_inbound(
            db, org_id=str(org), from_telefono="59176123456", media_b64=media,
            mime="image/png", caption=None, message_id="wamid.RLS",
        )  # fmt: skip
        db.commit()

    with app_engine.connect() as conn:
        # SIN fijar app.current_org ⇒ fail-closed.
        n = conn.execute(text("SELECT count(*) FROM comprobante_pendiente")).scalar_one()
    assert n == 0


@pytest.mark.db
def test_inbound_transaccion_ocr_duplicado_se_guarda_sin_ella(
    app_engine: Engine, org_identificada: dict
) -> None:
    """Mismo `transaccion_id_ocr` que otro comprobante ⇒ se guarda con None (RNF-06)."""
    from app.services import comprobantes as svc
    from app.services import ocr

    org = org_identificada["org"]
    media = base64.b64encode(_png_bytes()).decode("ascii")

    # Forzamos el OCR a devolver SIEMPRE el mismo transaccion_id (sin binario de Tesseract
    # el OCR real daría None; aquí simulamos una lectura exitosa repetida).
    def _fake(_img):  # type: ignore[no-untyped-def]
        return {
            "monto": None,
            "transaccion_id": "TX-REPETIDA-001",
            "fecha": None,
            "texto_crudo": "",
        }

    original = ocr.extraer_campos
    svc.ocr.extraer_campos = _fake  # type: ignore[assignment]
    try:
        with Session(app_engine, expire_on_commit=False) as db:
            f1 = svc.procesar_comprobante_inbound(
                db, org_id=str(org), from_telefono="59176123456", media_b64=media,
                mime="image/png", caption="primero", message_id="wamid.TX1",
            )  # fmt: skip
            f2 = svc.procesar_comprobante_inbound(
                db, org_id=str(org), from_telefono="59176123456", media_b64=media,
                mime="image/png", caption="segundo", message_id="wamid.TX2",
            )  # fmt: skip
            db.commit()
            assert f1 is not None and f2 is not None
            assert f1.transaccion_id_ocr == "TX-REPETIDA-001"
            # El 2º choca con el UNIQUE parcial ⇒ se guarda SIN transaccion (no se pierde).
            assert f2.transaccion_id_ocr is None
            assert f2.estado == "PENDIENTE"
    finally:
        svc.ocr.extraer_campos = original  # type: ignore[assignment]


# =========================================================================== #
# Servicio: confirmar / rechazar
# =========================================================================== #
@pytest.mark.db
def test_confirmar_registra_pago_y_marca_cuota(app_engine: Engine, org_identificada: dict) -> None:
    from app.models.cuota import Cuota
    from app.services import comprobantes as svc

    org = org_identificada["org"]
    admin = org_identificada["admin"]
    cuota_id = org_identificada["cuota"]
    media = base64.b64encode(_png_bytes()).decode("ascii")

    with Session(app_engine, expire_on_commit=False) as db:
        _set_org(db, org)
        comp = svc.procesar_comprobante_inbound(
            db, org_id=str(org), from_telefono="59176123456", media_b64=media,
            mime="image/png", caption=None, message_id="wamid.CF",
        )  # fmt: skip
        assert comp is not None
        pago = svc.confirmar_comprobante(
            db, comprobante_id=comp.id, cuota_id=cuota_id,
            monto=Decimal("250.00"), admin_id=admin,
        )  # fmt: skip
        # Asserts DENTRO de la tx (con org fijada): tras commit el GUC se limpia y RLS
        # ocultaría las filas a una query nueva.
        assert pago.estado == "CONFIRMADO"
        assert pago.metodo == "EFECTIVO"

        cuota = db.get(Cuota, cuota_id)
        assert cuota is not None and cuota.estado == "PAGADO"
        assert comp.estado == "CONFIRMADO"
        assert comp.pago_id == pago.id
        assert comp.resuelto_por == admin
        assert comp.resuelto_en is not None
        db.commit()


@pytest.mark.db
def test_confirmar_dos_veces_no_duplica_pago(app_engine: Engine, org_identificada: dict) -> None:
    from app.services import comprobantes as svc

    org = org_identificada["org"]
    admin = org_identificada["admin"]
    cuota_id = org_identificada["cuota"]
    media = base64.b64encode(_png_bytes()).decode("ascii")

    with Session(app_engine, expire_on_commit=False) as db:
        _set_org(db, org)
        comp = svc.procesar_comprobante_inbound(
            db, org_id=str(org), from_telefono="59176123456", media_b64=media,
            mime="image/png", caption=None, message_id="wamid.CF2",
        )  # fmt: skip
        assert comp is not None
        svc.confirmar_comprobante(
            db, comprobante_id=comp.id, cuota_id=cuota_id,
            monto=Decimal("250.00"), admin_id=admin,
        )  # fmt: skip
        db.commit()

    # 2º intento sobre el MISMO comprobante (ya CONFIRMADO) ⇒ ComprobanteError.
    with Session(app_engine, expire_on_commit=False) as db:
        _set_org(db, org)
        with pytest.raises(svc.ComprobanteError):
            svc.confirmar_comprobante(
                db, comprobante_id=comp.id, cuota_id=cuota_id,
                monto=Decimal("250.00"), admin_id=admin,
            )  # fmt: skip
        db.rollback()

    with app_engine.begin() as conn:
        _set_org(conn, org)
        n = conn.execute(
            text("SELECT count(*) FROM pago WHERE org_id = :o"), {"o": str(org)}
        ).scalar_one()
    assert n == 1, "confirmar 2x ⇒ 1 solo pago"


@pytest.mark.db
def test_rechazar_marca_rechazado(app_engine: Engine, org_identificada: dict) -> None:
    from app.services import comprobantes as svc

    org = org_identificada["org"]
    admin = org_identificada["admin"]
    media = base64.b64encode(_png_bytes()).decode("ascii")

    with Session(app_engine, expire_on_commit=False) as db:
        _set_org(db, org)
        comp = svc.procesar_comprobante_inbound(
            db, org_id=str(org), from_telefono="59176123456", media_b64=media,
            mime="image/png", caption=None, message_id="wamid.RJ",
        )  # fmt: skip
        assert comp is not None
        rechazado = svc.rechazar_comprobante(
            db, comprobante_id=comp.id, admin_id=admin, motivo="ilegible"
        )
        db.commit()
        assert rechazado.estado == "RECHAZADO"
        assert rechazado.resuelto_por == admin


# =========================================================================== #
# API: QR de cobro (subir/ver/meta/borrar)
# =========================================================================== #
@pytest.mark.db
def test_api_qr_subir_ver_borrar(org_identificada: dict) -> None:
    client = _client_or_skip()
    org = org_identificada["org"]
    headers = {"Authorization": f"Bearer {_token_admin(org, org_identificada['admin'])}"}

    # Sin QR aún.
    meta = client.get("/api/v1/qr-cobro/meta", headers=headers).json()
    assert meta["tiene_qr"] is False

    # Subir.
    png = _png_bytes()
    resp = client.post(
        "/api/v1/qr-cobro",
        headers=headers,
        files={"file": ("qr.png", png, "image/png")},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["tiene_qr"] is True
    assert body["mime"] == "image/png"
    assert body["tamano_bytes"] == len(png)
    assert body["imagen_url"] and ".img" in body["imagen_url"]

    # Ver (binario, Bearer).
    img = client.get("/api/v1/qr-cobro", headers=headers)
    assert img.status_code == 200
    assert img.content == png

    # Borrar.
    borrado = client.delete("/api/v1/qr-cobro", headers=headers).json()
    assert borrado["tiene_qr"] is False
    assert client.get("/api/v1/qr-cobro", headers=headers).status_code == 404


@pytest.mark.db
def test_api_qr_imagen_url_firmada_sin_bearer(org_identificada: dict) -> None:
    """La `imagen_url` firmada devuelve el binario SIN header Authorization (para `<img>`)."""
    client = _client_or_skip()
    org = org_identificada["org"]
    headers = {"Authorization": f"Bearer {_token_admin(org, org_identificada['admin'])}"}
    png = _png_bytes()
    client.post("/api/v1/qr-cobro", headers=headers, files={"file": ("qr.png", png, "image/png")})

    url = client.get("/api/v1/qr-cobro/meta", headers=headers).json()["imagen_url"]
    # Quita el host: el TestClient pega a la ruta relativa.
    ruta = url.split("/api/v1/", 1)[1]
    img = client.get(f"/api/v1/{ruta}")  # SIN Authorization
    assert img.status_code == 200
    assert img.content == png

    # Token manipulado ⇒ 404.
    bad = client.get(f"/api/v1/{ruta[:-5]}xxxx.img")
    assert bad.status_code == 404


# =========================================================================== #
# API: comprobantes (pendientes/confirmar/rechazar)
# =========================================================================== #
@pytest.mark.db
def test_api_pendientes_confirmar(app_engine: Engine, org_identificada: dict) -> None:
    from app.services import comprobantes as svc

    client = _client_or_skip()
    org = org_identificada["org"]
    cuota_id = org_identificada["cuota"]
    headers = {"Authorization": f"Bearer {_token_admin(org, org_identificada['admin'])}"}
    media = base64.b64encode(_png_bytes()).decode("ascii")

    with Session(app_engine, expire_on_commit=False) as db:
        svc.procesar_comprobante_inbound(
            db, org_id=str(org), from_telefono="59176123456", media_b64=media,
            mime="image/png", caption=None, message_id="wamid.API1",
        )  # fmt: skip
        db.commit()

    page = client.get("/api/v1/comprobantes/pendientes", headers=headers).json()
    assert page["total"] == 1
    item = page["items"][0]
    assert item["estado"] == "PENDIENTE"
    assert item["tutor"]["id"] == str(org_identificada["tutor"])
    assert item["cuota_sugerida"]["cuota_id"] == str(cuota_id)
    assert ".img" in item["imagen_url"]

    # Confirmar (1 clic).
    resp = client.post(
        f"/api/v1/comprobantes/{item['id']}/confirmar",
        headers=headers,
        json={"cuota_id": str(cuota_id), "monto": "250.00"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["estado"] == "CONFIRMADO"

    # Ya no está en pendientes.
    page2 = client.get("/api/v1/comprobantes/pendientes", headers=headers).json()
    assert page2["total"] == 0


@pytest.mark.db
def test_api_rechazar(app_engine: Engine, org_identificada: dict) -> None:
    from app.services import comprobantes as svc

    client = _client_or_skip()
    org = org_identificada["org"]
    headers = {"Authorization": f"Bearer {_token_admin(org, org_identificada['admin'])}"}
    media = base64.b64encode(_png_bytes()).decode("ascii")

    with Session(app_engine, expire_on_commit=False) as db:
        comp = svc.procesar_comprobante_inbound(
            db, org_id=str(org), from_telefono="59176123456", media_b64=media,
            mime="image/png", caption=None, message_id="wamid.API2",
        )  # fmt: skip
        db.commit()
        comp_id = comp.id  # type: ignore[union-attr]

    resp = client.post(
        f"/api/v1/comprobantes/{comp_id}/rechazar",
        headers=headers,
        json={"motivo": "no se lee"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"id": str(comp_id), "estado": "RECHAZADO"}


@pytest.mark.db
def test_api_rls_org_b_no_ve_comprobante_de_a(app_engine: Engine, owner_engine: Engine) -> None:
    """Org B (otro token) NO ve el comprobante de la org A (RLS)."""
    from app.services import comprobantes as svc

    client = _client_or_skip()
    org_a = uuid.uuid4()
    org_b = uuid.uuid4()
    with owner_engine.begin() as conn:
        ids_a = _sembrar_org_tutor_cuota(conn, org=org_a, tutor_telefono="+591 76100001")
        ids_b = _sembrar_org_tutor_cuota(conn, org=org_b, tutor_telefono="+591 76100002")

    media = base64.b64encode(_png_bytes()).decode("ascii")
    try:
        with Session(app_engine, expire_on_commit=False) as db:
            svc.procesar_comprobante_inbound(
                db, org_id=str(org_a), from_telefono="59176100001", media_b64=media,
                mime="image/png", caption=None, message_id="wamid.RLSA",
            )  # fmt: skip
            db.commit()

        headers_b = {"Authorization": f"Bearer {_token_admin(org_b, ids_b['admin'])}"}
        page_b = client.get("/api/v1/comprobantes/pendientes", headers=headers_b).json()
        assert page_b["total"] == 0, "org B no debe ver el comprobante de A"

        headers_a = {"Authorization": f"Bearer {_token_admin(org_a, ids_a['admin'])}"}
        page_a = client.get("/api/v1/comprobantes/pendientes", headers=headers_a).json()
        assert page_a["total"] == 1
    finally:
        with owner_engine.begin() as conn:
            _limpiar_org(conn, org_a)
            _limpiar_org(conn, org_b)
