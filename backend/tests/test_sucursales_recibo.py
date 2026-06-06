"""Tests del epic Sucursales/Categorías (CRUD ADMIN) + Recibo por WhatsApp.

Cubre:
- **recibo_token** (sin BD): firma HMAC determinista, validación constante,
  rechazo de token alterado, forma de `url_recibo`.
- **CRUD Sucursales/Categorías** (`@db`, vía TestClient + JWT real): alta/edición/
  baja ADMIN; RLS (INSERT con el org del token; sin contexto = 0 filas).
- **DELETE protegido** (`@db`): borrar sucursal con alumnos ⇒ 409 y NADA se borró
  (ni la sucursal ni el alumno).
- **Recibo enlace** (`@db`): token válido + pago CONFIRMADO ⇒ 200 PDF; token
  inválido ⇒ 404; pago NO confirmado ⇒ 404.
- **Recibo envío** (`@db`): `enviar_recibo_whatsapp` deja un mensaje en `.sent` con
  el enlace en `body_params`; sin teléfono ⇒ no envía.
- **Idempotencia**: confirmar un pago QR vía webhook dos veces ⇒ recibo enviado UNA
  sola vez (mock instrumentado en `pagos._enviar_recibo_por_whatsapp`).

Patrón BD idéntico al resto de la suite: `owner_engine` siembra saltando RLS; una
`Session(app_engine, expire_on_commit=False)` ejercita los servicios bajo RLS real
fijando `app.current_org` con `set_config(..., true)`. Los `@pytest.mark.db` los
corre main contra Postgres recién migrado.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from datetime import date
from decimal import Decimal

import pytest
from app.adapters.whatsapp.mock import MockWhatsAppAdapter
from app.core.security import create_access_token
from app.services import recibo_token
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session


# --------------------------------------------------------------------------- #
# recibo_token — SIN BD (HMAC puro)
# --------------------------------------------------------------------------- #
def test_firmar_recibo_determinista_y_valido() -> None:
    org = uuid.uuid4()
    pago = uuid.uuid4()
    t1 = recibo_token.firmar_recibo(org, pago)
    t2 = recibo_token.firmar_recibo(org, pago)
    assert t1 == t2, "la firma HMAC del mismo par (org, pago) es determinista"
    assert recibo_token.token_valido(org, pago, t1) is True


def test_token_invalido_rechazado() -> None:
    org = uuid.uuid4()
    pago = uuid.uuid4()
    token = recibo_token.firmar_recibo(org, pago)
    # Token alterado.
    assert recibo_token.token_valido(org, pago, token + "x") is False
    assert recibo_token.token_valido(org, pago, "no-es-un-token") is False
    # Mismo token pero otro pago ⇒ inválido (no reutilizable entre recursos).
    assert recibo_token.token_valido(org, uuid.uuid4(), token) is False


def test_url_recibo_incluye_ruta_y_token() -> None:
    org = uuid.uuid4()
    pago = uuid.uuid4()
    url = recibo_token.url_recibo(org, pago)
    token = recibo_token.firmar_recibo(org, pago)
    assert url.endswith(f"/api/v1/recibos/{org}/{pago}/{token}.pdf")
    assert "//" in url  # esquema://host conservado


# --------------------------------------------------------------------------- #
# Helpers de siembra (con BD)
# --------------------------------------------------------------------------- #
def _set_org(conn, org: uuid.UUID) -> None:
    conn.execute(text("SELECT set_config('app.current_org', :o, true)"), {"o": str(org)})


def _sembrar_org_admin(conn, *, org: uuid.UUID, user: uuid.UUID, email: str) -> None:
    conn.execute(
        text(
            "INSERT INTO organizacion (id, nombre, pais, moneda, modo_cobro_default, "
            "prorratea_primer_periodo, created_at, updated_at) "
            "VALUES (:id,'Org Suc/Recibo (test)','BO','BOB','ANIVERSARIO',true,now(),now()) "
            "ON CONFLICT (id) DO NOTHING"
        ),
        {"id": str(org)},
    )
    conn.execute(
        text(
            "INSERT INTO usuario (id, org_id, email, password_hash, role, nombre, "
            "activo, created_at, updated_at) "
            "VALUES (:id,:org,:email,'x','ADMIN','Admin Test',true,now(),now())"
        ),
        {"id": str(user), "org": str(org), "email": email},
    )


def _limpiar_org(conn, org: uuid.UUID) -> None:
    for tabla in (
        "recordatorio_pago",
        "pago_cuota",
        "pago",
        "credito",
        "cuota",
        "inscripcion",
        "alumno_tutor",
        "tutor",
        "asistencia",
        "sesion",
        "horario_clase",
        "alumno",
        "consentimiento",
        "categoria",
        "sucursal",
        "recibo_contador",
        "usuario",
    ):
        conn.execute(text(f"DELETE FROM {tabla} WHERE org_id = :o"), {"o": str(org)})
    conn.execute(text("DELETE FROM organizacion WHERE id = :o"), {"o": str(org)})


def _token_admin(org: uuid.UUID, user: uuid.UUID) -> str:
    return create_access_token(user_id=str(user), org_id=str(org), role="ADMIN", sucursal_ids=[])


def _client_or_skip():
    if not os.getenv("DATABASE_URL"):
        pytest.skip("DATABASE_URL no definido; requiere Postgres migrado")
    from app.main import app
    from fastapi.testclient import TestClient

    return TestClient(app)


@pytest.fixture()
def org_admin(owner_engine: Engine) -> Iterator[dict]:
    """Una org con un usuario ADMIN; limpia todo lo de la org al final."""
    org = uuid.uuid4()
    user = uuid.uuid4()
    with owner_engine.begin() as conn:
        _sembrar_org_admin(conn, org=org, user=user, email=f"admin_{user.hex}@t.test")
    yield {"org": org, "user": user, "token": _token_admin(org, user)}
    with owner_engine.begin() as conn:
        _limpiar_org(conn, org)


# --------------------------------------------------------------------------- #
# CRUD Sucursales/Categorías (TestClient + JWT real)
# --------------------------------------------------------------------------- #
@pytest.mark.db
def test_crud_sucursal_admin(org_admin: dict) -> None:
    client = _client_or_skip()
    headers = {"Authorization": f"Bearer {org_admin['token']}"}

    # Alta (201).
    resp = client.post("/api/v1/sucursales", headers=headers, json={"nombre": "Central"})
    assert resp.status_code == 201, resp.text
    suc = resp.json()
    suc_id = suc["id"]
    assert suc["nombre"] == "Central"

    # Aparece en el listado (RLS deja verla con el contexto del token).
    lista = client.get("/api/v1/sucursales", headers=headers).json()
    assert any(s["id"] == suc_id for s in lista)

    # Edición.
    resp = client.put(
        f"/api/v1/sucursales/{suc_id}",
        headers=headers,
        json={"nombre": "Central Norte", "direccion": "Av. Siempre Viva"},
    )
    assert resp.status_code == 200
    assert resp.json()["nombre"] == "Central Norte"
    assert resp.json()["direccion"] == "Av. Siempre Viva"

    # Baja (204) — sin uso.
    resp = client.delete(f"/api/v1/sucursales/{suc_id}", headers=headers)
    assert resp.status_code == 204

    # Otra org / id inexistente ⇒ 404.
    assert client.delete(f"/api/v1/sucursales/{uuid.uuid4()}", headers=headers).status_code == 404


@pytest.mark.db
def test_crud_categoria_admin(org_admin: dict) -> None:
    client = _client_or_skip()
    headers = {"Authorization": f"Bearer {org_admin['token']}"}

    suc_id = client.post("/api/v1/sucursales", headers=headers, json={"nombre": "Suc Cat"}).json()[
        "id"
    ]

    # Alta categoría (201) con nivel válido.
    resp = client.post(
        "/api/v1/categorias",
        headers=headers,
        json={"nombre": "Sub-14", "nivel": "INTERMEDIO", "sucursal_id": suc_id},
    )
    assert resp.status_code == 201, resp.text
    cat = resp.json()
    cat_id = cat["id"]
    assert cat["nivel"] == "INTERMEDIO"
    assert cat["sucursal_id"] == suc_id

    # nivel inválido ⇒ 422 (Literal del schema).
    bad = client.post(
        "/api/v1/categorias",
        headers=headers,
        json={"nombre": "X", "nivel": "EXPERTO", "sucursal_id": suc_id},
    )
    assert bad.status_code == 422

    # Edición (sucursal_id no editable: el body no lo lleva).
    resp = client.put(
        f"/api/v1/categorias/{cat_id}",
        headers=headers,
        json={"nombre": "Sub-16", "nivel": "AVANZADO", "rango_edad": "15-16"},
    )
    assert resp.status_code == 200
    assert resp.json()["nombre"] == "Sub-16"
    assert resp.json()["nivel"] == "AVANZADO"
    assert resp.json()["sucursal_id"] == suc_id, "sucursal_id no debe cambiar"

    # Baja (204).
    assert client.delete(f"/api/v1/categorias/{cat_id}", headers=headers).status_code == 204


@pytest.mark.db
def test_crud_requiere_admin(org_admin: dict) -> None:
    """ENTRENADOR ⇒ 403; sin token ⇒ 401."""
    client = _client_or_skip()
    coach_token = create_access_token(
        user_id=str(uuid.uuid4()),
        org_id=str(org_admin["org"]),
        role="ENTRENADOR",
        sucursal_ids=[],
    )
    resp = client.post(
        "/api/v1/sucursales",
        headers={"Authorization": f"Bearer {coach_token}"},
        json={"nombre": "No permitido"},
    )
    assert resp.status_code == 403
    assert client.post("/api/v1/sucursales", json={"nombre": "x"}).status_code == 401


@pytest.mark.db
def test_rls_sucursal_sin_contexto_cero_filas(app_engine: Engine, org_admin: dict) -> None:
    """Fail-closed: sin `app.current_org`, `sucursal` no devuelve filas."""
    client = _client_or_skip()
    headers = {"Authorization": f"Bearer {org_admin['token']}"}
    client.post("/api/v1/sucursales", headers=headers, json={"nombre": "Aislada"})

    with app_engine.connect() as conn:
        count = conn.execute(
            text("SELECT count(*) FROM sucursal WHERE org_id = :o"),
            {"o": str(org_admin["org"])},
        ).scalar_one()
    assert count == 0, "sin contexto de tenant, sucursal debe devolver 0 filas"


# --------------------------------------------------------------------------- #
# DELETE protegido: sucursal con alumno ⇒ 409 y NADA se borra
# --------------------------------------------------------------------------- #
@pytest.mark.db
def test_delete_sucursal_con_alumno_409_no_borra(
    app_engine: Engine, owner_engine: Engine, org_admin: dict
) -> None:
    org = org_admin["org"]
    suc = uuid.uuid4()
    al = uuid.uuid4()
    with owner_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO sucursal (id, org_id, nombre, created_at, updated_at) "
                "VALUES (:id,:org,'Con Alumnos',now(),now())"
            ),
            {"id": str(suc), "org": str(org)},
        )
        conn.execute(
            text(
                "INSERT INTO alumno (id, org_id, sucursal_id, nombres, created_at, updated_at) "
                "VALUES (:id,:org,:suc,'Alumno X',now(),now())"
            ),
            {"id": str(al), "org": str(org), "suc": str(suc)},
        )

    client = _client_or_skip()
    headers = {"Authorization": f"Bearer {org_admin['token']}"}
    resp = client.delete(f"/api/v1/sucursales/{suc}", headers=headers)
    assert resp.status_code == 409
    assert "alumno" in resp.json()["detail"].lower()

    # NADA se borró: la sucursal sigue, el alumno sigue (no cascada).
    with app_engine.begin() as conn:
        _set_org(conn, org)
        n_suc = conn.execute(
            text("SELECT count(*) FROM sucursal WHERE id = :i"), {"i": str(suc)}
        ).scalar_one()
        n_al = conn.execute(
            text("SELECT count(*) FROM alumno WHERE id = :i"), {"i": str(al)}
        ).scalar_one()
    assert n_suc == 1, "la sucursal NO debe borrarse cuando está en uso"
    assert n_al == 1, "el alumno NO debe borrarse en cascada"


# --------------------------------------------------------------------------- #
# Recibo: enlace tokenizado público
# --------------------------------------------------------------------------- #
def _sembrar_pago_confirmado(
    owner_engine: Engine, app_engine: Engine, *, org: uuid.UUID, user: uuid.UUID
) -> dict:
    """Org + sucursal + alumno + tutor responsable + inscripción + cuota, y confirma
    un pago EFECTIVO (que asigna numero_recibo). Devuelve ids + pago_id."""
    suc = uuid.uuid4()
    al = uuid.uuid4()
    tutor = uuid.uuid4()
    insc = uuid.uuid4()
    cuota = uuid.uuid4()
    monto = Decimal("250.00")
    with owner_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO sucursal (id, org_id, nombre, created_at, updated_at) "
                "VALUES (:id,:org,'Suc',now(),now())"
            ),
            {"id": str(suc), "org": str(org)},
        )
        conn.execute(
            text(
                "INSERT INTO alumno (id, org_id, sucursal_id, nombres, ap_paterno, "
                "created_at, updated_at) VALUES (:id,:org,:suc,'Camila','Rojas',now(),now())"
            ),
            {"id": str(al), "org": str(org), "suc": str(suc)},
        )
        conn.execute(
            text(
                "INSERT INTO tutor (id, org_id, nombres, telefono, created_at, updated_at) "
                "VALUES (:id,:org,'Maria Rojas','59177712345',now(),now())"
            ),
            {"id": str(tutor), "org": str(org)},
        )
        conn.execute(
            text(
                "INSERT INTO alumno_tutor (id, org_id, alumno_id, tutor_id, parentesco, "
                "responsable_pago, created_at, updated_at) "
                "VALUES (:id,:org,:al,:tut,'Madre',true,now(),now())"
            ),
            {"id": str(uuid.uuid4()), "org": str(org), "al": str(al), "tut": str(tutor)},
        )
        conn.execute(
            text(
                "INSERT INTO inscripcion (id, org_id, alumno_id, fecha_inscripcion, "
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
                "pi": date(2026, 1, 10),
                "pf": date(2026, 2, 10),
                "v": date(2026, 2, 10),
                "m": monto,
            },
        )

    from app.services import pagos as pagos_svc

    with Session(app_engine, expire_on_commit=False) as db:
        db.execute(text("SELECT set_config('app.current_org', :o, true)"), {"o": str(org)})
        pago = pagos_svc.registrar_pago_efectivo(
            db, org_id=org, cuota_ids=[cuota], registrado_por=user
        )
        db.flush()
        pago_id = pago.id
        db.commit()

    return {"suc": suc, "alumno": al, "tutor": tutor, "cuota": cuota, "pago": pago_id}


@pytest.fixture()
def pago_confirmado(owner_engine: Engine, app_engine: Engine, org_admin: dict) -> dict:
    return _sembrar_pago_confirmado(
        owner_engine, app_engine, org=org_admin["org"], user=org_admin["user"]
    )


@pytest.mark.db
def test_recibo_enlace_token_valido_200_pdf(org_admin: dict, pago_confirmado: dict) -> None:
    client = _client_or_skip()
    org = org_admin["org"]
    pago = pago_confirmado["pago"]
    token = recibo_token.firmar_recibo(org, pago)

    resp = client.get(f"/api/v1/recibos/{org}/{pago}/{token}.pdf")
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"] == "application/pdf"
    assert resp.content[:4] == b"%PDF"


@pytest.mark.db
def test_recibo_enlace_token_invalido_404(org_admin: dict, pago_confirmado: dict) -> None:
    client = _client_or_skip()
    org = org_admin["org"]
    pago = pago_confirmado["pago"]
    resp = client.get(f"/api/v1/recibos/{org}/{pago}/token-falso.pdf")
    assert resp.status_code == 404


@pytest.mark.db
def test_recibo_enlace_pago_no_confirmado_404(owner_engine: Engine, org_admin: dict) -> None:
    """Un pago PENDIENTE (no confirmado) ⇒ 404 aunque el token sea válido."""
    client = _client_or_skip()
    org = org_admin["org"]
    pago_id = uuid.uuid4()
    with owner_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO pago (id, org_id, metodo, estado, monto, credito_aplicado, "
                "created_at) VALUES (:id,:org,'QR','PENDIENTE',100,0,now())"
            ),
            {"id": str(pago_id), "org": str(org)},
        )
    token = recibo_token.firmar_recibo(org, pago_id)
    resp = client.get(f"/api/v1/recibos/{org}/{pago_id}/{token}.pdf")
    assert resp.status_code == 404


# --------------------------------------------------------------------------- #
# Recibo: servicio de envío (mock)
# --------------------------------------------------------------------------- #
@pytest.mark.db
def test_envio_recibo_whatsapp_lleva_enlace(
    app_engine: Engine, org_admin: dict, pago_confirmado: dict
) -> None:
    from app.models.pago import Pago
    from app.services.recibo_envio import enviar_recibo_whatsapp

    org = org_admin["org"]
    pago_id = pago_confirmado["pago"]
    mock = MockWhatsAppAdapter()

    with Session(app_engine, expire_on_commit=False) as db:
        db.execute(text("SELECT set_config('app.current_org', :o, true)"), {"o": str(org)})
        pago = db.get(Pago, pago_id)
        assert pago is not None
        res = enviar_recibo_whatsapp(db, pago=pago, port=mock)

    assert res.enviado is True
    assert res.motivo == "ok"
    assert len(mock.sent) == 1
    enlace_esperado = recibo_token.url_recibo(org, pago_id)
    assert enlace_esperado in mock.sent[0].body_params
    assert mock.sent[0].template_name == "recibo_pago"
    assert mock.sent[0].to == "59177712345"


@pytest.mark.db
def test_envio_recibo_sin_telefono_no_envia(
    owner_engine: Engine, app_engine: Engine, org_admin: dict
) -> None:
    """Tutor responsable SIN teléfono (o sin tutor) ⇒ no llama al puerto."""
    from app.models.pago import Pago
    from app.services.recibo_envio import enviar_recibo_whatsapp

    org = org_admin["org"]
    user = org_admin["user"]
    suc = uuid.uuid4()
    al = uuid.uuid4()
    tutor = uuid.uuid4()
    insc = uuid.uuid4()
    cuota = uuid.uuid4()
    monto = Decimal("100.00")
    with owner_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO sucursal (id, org_id, nombre, created_at, updated_at) "
                "VALUES (:id,:org,'Suc',now(),now())"
            ),
            {"id": str(suc), "org": str(org)},
        )
        conn.execute(
            text(
                "INSERT INTO alumno (id, org_id, sucursal_id, nombres, created_at, updated_at) "
                "VALUES (:id,:org,:suc,'Sin Tel',now(),now())"
            ),
            {"id": str(al), "org": str(org), "suc": str(suc)},
        )
        # Tutor responsable PERO sin teléfono.
        conn.execute(
            text(
                "INSERT INTO tutor (id, org_id, nombres, telefono, created_at, updated_at) "
                "VALUES (:id,:org,'Sin Tel',NULL,now(),now())"
            ),
            {"id": str(tutor), "org": str(org)},
        )
        conn.execute(
            text(
                "INSERT INTO alumno_tutor (id, org_id, alumno_id, tutor_id, "
                "responsable_pago, created_at, updated_at) "
                "VALUES (:id,:org,:al,:tut,true,now(),now())"
            ),
            {"id": str(uuid.uuid4()), "org": str(org), "al": str(al), "tut": str(tutor)},
        )
        conn.execute(
            text(
                "INSERT INTO inscripcion (id, org_id, alumno_id, monto_mensual, estado, "
                "created_at, updated_at) VALUES (:id,:org,:al,:m,'ACTIVA',now(),now())"
            ),
            {"id": str(insc), "org": str(org), "al": str(al), "m": monto},
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
                "pi": date(2026, 1, 10),
                "pf": date(2026, 2, 10),
                "v": date(2026, 2, 10),
                "m": monto,
            },
        )

    from app.services import pagos as pagos_svc

    mock = MockWhatsAppAdapter()
    with Session(app_engine, expire_on_commit=False) as db:
        db.execute(text("SELECT set_config('app.current_org', :o, true)"), {"o": str(org)})
        pago = pagos_svc.registrar_pago_efectivo(
            db, org_id=org, cuota_ids=[cuota], registrado_por=user
        )
        db.flush()
        pago_id = pago.id
        db.commit()

    with Session(app_engine, expire_on_commit=False) as db:
        db.execute(text("SELECT set_config('app.current_org', :o, true)"), {"o": str(org)})
        pago_db = db.get(Pago, pago_id)
        assert pago_db is not None
        res = enviar_recibo_whatsapp(db, pago=pago_db, port=mock)

    assert res.enviado is False
    assert res.motivo == "sin_telefono"
    assert len(mock.sent) == 0


# --------------------------------------------------------------------------- #
# Idempotencia: webhook QR duplicado ⇒ recibo enviado UNA sola vez
# --------------------------------------------------------------------------- #
@pytest.mark.db
def test_webhook_qr_duplicado_recibo_una_vez(
    owner_engine: Engine, app_engine: Engine, org_admin: dict, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Confirmar el MISMO pago QR vía webhook dos veces ⇒ el recibo se envía 1 vez.

    Instrumentamos `get_whatsapp_port` (usado por `pagos._enviar_recibo_por_whatsapp`)
    con un único mock compartido para contar los envíos a lo largo de ambas
    invocaciones del webhook. La conciliación NO se toca: usamos `procesar_webhook`
    tal cual, con su idempotencia por `transaccion_id`/estado.
    """
    from app.services import pagos as pagos_svc

    org = org_admin["org"]
    suc = uuid.uuid4()
    al = uuid.uuid4()
    tutor = uuid.uuid4()
    insc = uuid.uuid4()
    cuota = uuid.uuid4()
    monto = Decimal("150.00")
    with owner_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO sucursal (id, org_id, nombre, created_at, updated_at) "
                "VALUES (:id,:org,'Suc',now(),now())"
            ),
            {"id": str(suc), "org": str(org)},
        )
        conn.execute(
            text(
                "INSERT INTO alumno (id, org_id, sucursal_id, nombres, created_at, updated_at) "
                "VALUES (:id,:org,:suc,'QR Alumno',now(),now())"
            ),
            {"id": str(al), "org": str(org), "suc": str(suc)},
        )
        conn.execute(
            text(
                "INSERT INTO tutor (id, org_id, nombres, telefono, created_at, updated_at) "
                "VALUES (:id,:org,'Tutor QR','59177700123',now(),now())"
            ),
            {"id": str(tutor), "org": str(org)},
        )
        conn.execute(
            text(
                "INSERT INTO alumno_tutor (id, org_id, alumno_id, tutor_id, "
                "responsable_pago, created_at, updated_at) "
                "VALUES (:id,:org,:al,:tut,true,now(),now())"
            ),
            {"id": str(uuid.uuid4()), "org": str(org), "al": str(al), "tut": str(tutor)},
        )
        conn.execute(
            text(
                "INSERT INTO inscripcion (id, org_id, alumno_id, monto_mensual, estado, "
                "created_at, updated_at) VALUES (:id,:org,:al,:m,'ACTIVA',now(),now())"
            ),
            {"id": str(insc), "org": str(org), "al": str(al), "m": monto},
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
                "pi": date(2026, 1, 10),
                "pf": date(2026, 2, 10),
                "v": date(2026, 2, 10),
                "m": monto,
            },
        )

    # Mock compartido para todas las invocaciones del envío de recibo.
    from app.services import recibo_envio

    mock = MockWhatsAppAdapter()

    def _enviar_con_mock(db: Session, *, pago) -> None:  # type: ignore[no-untyped-def]
        recibo_envio.enviar_recibo_whatsapp(db, pago=pago, port=mock)

    monkeypatch.setattr("app.services.pagos._enviar_recibo_por_whatsapp", _enviar_con_mock)

    qr_ref = f"qr_{uuid.uuid4().hex}"
    tx_id = f"tx_{uuid.uuid4().hex}"

    # Crear el pago QR PENDIENTE (intención).
    with Session(app_engine, expire_on_commit=False) as db:
        db.execute(text("SELECT set_config('app.current_org', :o, true)"), {"o": str(org)})
        pagos_svc.crear_pago_qr(db, org_id=org, cuota_ids=[cuota], qr_ref=qr_ref)
        db.commit()

    # Webhook #1: confirma; #2: idempotente (mismo transaccion_id).
    with Session(app_engine, expire_on_commit=False) as db:
        r1 = pagos_svc.procesar_webhook(db, transaccion_id=tx_id, referencia=qr_ref, monto=monto)
        db.commit()
    with Session(app_engine, expire_on_commit=False) as db:
        r2 = pagos_svc.procesar_webhook(db, transaccion_id=tx_id, referencia=qr_ref, monto=monto)
        db.commit()

    assert r1 == "confirmado"
    assert r2 == "idempotente"
    assert len(mock.sent) == 1, "webhook duplicado NO debe reenviar el recibo"
