"""Tests de la DoD del epic WhatsApp Cobro (recordatorios salientes).

Cubre el servicio `app.services.recordatorios.enviar_recordatorio_cuota`:

- **Idempotencia** (DoD crítico): re-llamar el mismo día NO reenvía ni crea un
  segundo QR; 1 fila `recordatorio_pago` por `(cuota_id, tipo, ciclo)`.
- **sin_telefono**: tutor responsable sin teléfono ⇒ fila `FALLIDO`, sin envío.
- **MOROSIDAD**: dedup mensual (mismo `YYYY-MM` ⇒ 1 envío; mes distinto ⇒ 2º).
- **forzar=True**: reenvía sobre la MISMA fila (UPDATE, no nueva fila).
- **RLS** fail-closed de `recordatorio_pago` (sin contexto ⇒ 0 filas; org A no ve B).
- **Webhook GET verify** (sin BD, `TestClient`): challenge si el token coincide, 403 si no.

Patrón BD idéntico al resto de la suite: `owner_engine` siembra (saltando RLS),
una `Session(app_engine, expire_on_commit=False)` ejercita el servicio bajo RLS
real fijando `app.current_org` con `set_config(..., true)` (SET LOCAL). El offline
está garantizado: `get_payment_provider()` devuelve el sandbox OpenBCB (no red) y el
adaptador WhatsApp es el `MockWhatsAppAdapter` (acumula en `.sent`, no envía).

Los `@pytest.mark.db` los corre main contra Postgres recién migrado.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import date
from decimal import Decimal

import pytest
from app.adapters.whatsapp.mock import MockWhatsAppAdapter
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session


def _set_org(conn, org: uuid.UUID) -> None:
    """Fija `app.current_org` para la tx (SET LOCAL vía set_config 3er arg=true)."""
    conn.execute(text("SELECT set_config('app.current_org', :o, true)"), {"o": str(org)})


def _sembrar_org_con_cuota(
    conn,
    *,
    org: uuid.UUID,
    monto: Decimal,
    vence_el: date,
    estado_cuota: str,
    con_tutor: bool,
    tutor_telefono: str | None,
    tutor_responsable: bool,
) -> dict:
    """Org + sucursal + alumno + inscripción + 1 cuota, opcionalmente tutor.

    - `estado_cuota`: 'PENDIENTE' (próximo vencimiento) | 'VENCIDO' (morosidad).
    - `con_tutor=False` ⇒ no hay tutor (resuelve a sin_telefono).
    - `con_tutor=True` + `tutor_telefono=None` ⇒ tutor responsable SIN teléfono.
    - `tutor_responsable` controla `alumno_tutor.responsable_pago`.

    La org usa `ON CONFLICT (id) DO NOTHING` (mismo patrón que el resto de la
    suite). Devuelve los ids sembrados.
    """
    suc = uuid.uuid4()
    al = uuid.uuid4()
    insc = uuid.uuid4()
    cuota = uuid.uuid4()
    periodo_inicio = date(vence_el.year, 1, 10)

    conn.execute(
        text(
            "INSERT INTO organizacion (id, nombre, pais, moneda, modo_cobro_default, "
            "prorratea_primer_periodo, created_at, updated_at) "
            "VALUES (:id,'Org Recordatorio (test)','BO','BOB','ANIVERSARIO',true,now(),now()) "
            "ON CONFLICT (id) DO NOTHING"
        ),
        {"id": str(org)},
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
            "INSERT INTO alumno (id, org_id, sucursal_id, nombres, ap_paterno, "
            "created_at, updated_at) "
            "VALUES (:id,:org,:suc,'Camila','Rojas',now(),now())"
        ),
        {"id": str(al), "org": str(org), "suc": str(suc)},
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
            "VALUES (:id,:org,:insc,:pi,:pf,:v,:m,0,:estado,false,now())"
        ),
        {
            "id": str(cuota),
            "org": str(org),
            "insc": str(insc),
            "pi": periodo_inicio,
            "pf": vence_el,
            "v": vence_el,
            "m": monto,
            "estado": estado_cuota,
        },
    )

    tutor = None
    if con_tutor:
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
                "INSERT INTO alumno_tutor (id, org_id, alumno_id, tutor_id, parentesco, "
                "responsable_pago, created_at, updated_at) "
                "VALUES (:id,:org,:al,:tut,'Madre',:resp,now(),now())"
            ),
            {
                "id": str(uuid.uuid4()),
                "org": str(org),
                "al": str(al),
                "tut": str(tutor),
                "resp": tutor_responsable,
            },
        )

    return {"suc": suc, "alumno": al, "inscripcion": insc, "cuota": cuota, "tutor": tutor}


def _limpiar_org(conn, org: uuid.UUID) -> None:
    """Borra todo lo sembrado de una org (orden FK-safe)."""
    conn.execute(text("DELETE FROM recordatorio_pago WHERE org_id = :o"), {"o": str(org)})
    conn.execute(text("DELETE FROM pago_cuota WHERE org_id = :o"), {"o": str(org)})
    conn.execute(text("DELETE FROM pago WHERE org_id = :o"), {"o": str(org)})
    conn.execute(text("DELETE FROM credito WHERE org_id = :o"), {"o": str(org)})
    conn.execute(text("DELETE FROM cuota WHERE org_id = :o"), {"o": str(org)})
    conn.execute(text("DELETE FROM inscripcion WHERE org_id = :o"), {"o": str(org)})
    conn.execute(text("DELETE FROM alumno_tutor WHERE org_id = :o"), {"o": str(org)})
    conn.execute(text("DELETE FROM tutor WHERE org_id = :o"), {"o": str(org)})
    conn.execute(text("DELETE FROM alumno WHERE org_id = :o"), {"o": str(org)})
    conn.execute(text("DELETE FROM sucursal WHERE org_id = :o"), {"o": str(org)})
    conn.execute(text("DELETE FROM organizacion WHERE id = :o"), {"o": str(org)})


# --------------------------------------------------------------------------- #
# Fixtures de siembra (con BD)
# --------------------------------------------------------------------------- #
@pytest.fixture()
def recordatorio_proximo(owner_engine: Engine) -> Iterator[dict]:
    """Cuota PENDIENTE que vence en N días + tutor responsable CON teléfono."""
    org = uuid.uuid4()
    monto = Decimal("250.00")
    vence_el = date(2026, 6, 10)
    with owner_engine.begin() as conn:
        ids = _sembrar_org_con_cuota(
            conn,
            org=org,
            monto=monto,
            vence_el=vence_el,
            estado_cuota="PENDIENTE",
            con_tutor=True,
            tutor_telefono="59177712345",
            tutor_responsable=True,
        )
    yield {"org": org, "vence_el": vence_el, "monto": monto, **ids}
    with owner_engine.begin() as conn:
        _limpiar_org(conn, org)


@pytest.fixture()
def recordatorio_sin_telefono(owner_engine: Engine) -> Iterator[dict]:
    """Cuota PENDIENTE + tutor responsable SIN teléfono (resuelve a sin_telefono)."""
    org = uuid.uuid4()
    monto = Decimal("250.00")
    vence_el = date(2026, 6, 10)
    with owner_engine.begin() as conn:
        ids = _sembrar_org_con_cuota(
            conn,
            org=org,
            monto=monto,
            vence_el=vence_el,
            estado_cuota="PENDIENTE",
            con_tutor=True,
            tutor_telefono=None,
            tutor_responsable=True,
        )
    yield {"org": org, "vence_el": vence_el, "monto": monto, **ids}
    with owner_engine.begin() as conn:
        _limpiar_org(conn, org)


@pytest.fixture()
def recordatorio_morosidad(owner_engine: Engine) -> Iterator[dict]:
    """Cuota VENCIDA + tutor responsable CON teléfono (para MOROSIDAD)."""
    org = uuid.uuid4()
    monto = Decimal("250.00")
    vence_el = date(2026, 4, 10)
    with owner_engine.begin() as conn:
        ids = _sembrar_org_con_cuota(
            conn,
            org=org,
            monto=monto,
            vence_el=vence_el,
            estado_cuota="VENCIDO",
            con_tutor=True,
            tutor_telefono="59177799999",
            tutor_responsable=True,
        )
    yield {"org": org, "vence_el": vence_el, "monto": monto, **ids}
    with owner_engine.begin() as conn:
        _limpiar_org(conn, org)


def _get_cuota(db: Session, cuota_id: uuid.UUID):
    from app.models.cuota import Cuota

    cuota = db.get(Cuota, cuota_id)
    assert cuota is not None
    return cuota


# --------------------------------------------------------------------------- #
# 1) Idempotencia (DoD CRÍTICO): mismo `hoy` ⇒ 1 envío, 1 fila
# --------------------------------------------------------------------------- #
@pytest.mark.db
def test_idempotencia_proximo_vencimiento(app_engine: Engine, recordatorio_proximo: dict) -> None:
    from app.services.recordatorios import enviar_recordatorio_cuota

    org = recordatorio_proximo["org"]
    cuota_id = recordatorio_proximo["cuota"]
    hoy = date(2026, 6, 7)  # vence el 2026-06-10 (3 días antes)
    mock = MockWhatsAppAdapter()

    with Session(app_engine, expire_on_commit=False) as db:
        _set_org(db, org)
        cuota = _get_cuota(db, cuota_id)
        r1 = enviar_recordatorio_cuota(
            db, cuota=cuota, tipo="PROXIMO_VENCIMIENTO", hoy=hoy, port=mock
        )
        r2 = enviar_recordatorio_cuota(
            db, cuota=cuota, tipo="PROXIMO_VENCIMIENTO", hoy=hoy, port=mock
        )
        db.commit()

    assert r1.enviado is True
    assert r1.motivo == "ok"
    assert r2.enviado is False
    assert r2.motivo == "ya_enviado"
    # Idempotencia del proveedor: un solo mensaje enviado (no doble QR/envío).
    assert len(mock.sent) == 1

    with app_engine.begin() as conn:
        _set_org(conn, org)
        filas = conn.execute(
            text(
                "SELECT count(*) FROM recordatorio_pago "
                "WHERE cuota_id = :c AND tipo = 'PROXIMO_VENCIMIENTO'"
            ),
            {"c": str(cuota_id)},
        ).scalar_one()
    assert filas == 1, "exactamente 1 fila para esa cuota+tipo (UNIQUE cuota,tipo,ciclo)"


# --------------------------------------------------------------------------- #
# 2) sin_telefono: tutor responsable sin teléfono ⇒ FALLIDO, sin envío
# --------------------------------------------------------------------------- #
@pytest.mark.db
def test_sin_telefono_registra_fallido_sin_enviar(
    app_engine: Engine, recordatorio_sin_telefono: dict
) -> None:
    from app.services.recordatorios import enviar_recordatorio_cuota

    org = recordatorio_sin_telefono["org"]
    cuota_id = recordatorio_sin_telefono["cuota"]
    hoy = date(2026, 6, 7)
    mock = MockWhatsAppAdapter()

    with Session(app_engine, expire_on_commit=False) as db:
        _set_org(db, org)
        cuota = _get_cuota(db, cuota_id)
        res = enviar_recordatorio_cuota(
            db, cuota=cuota, tipo="PROXIMO_VENCIMIENTO", hoy=hoy, port=mock
        )
        db.commit()

    assert res.enviado is False
    assert res.motivo == "sin_telefono"
    assert len(mock.sent) == 0, "sin teléfono no debe llamar al puerto"

    with app_engine.begin() as conn:
        _set_org(conn, org)
        row = conn.execute(
            text(
                "SELECT estado FROM recordatorio_pago "
                "WHERE cuota_id = :c AND tipo = 'PROXIMO_VENCIMIENTO'"
            ),
            {"c": str(cuota_id)},
        ).one()
    assert row.estado == "FALLIDO", "el intento queda auditado como FALLIDO (no se pierde)"


# --------------------------------------------------------------------------- #
# 3) Morosidad — dedup mensual (mismo YYYY-MM ⇒ 1 envío; mes distinto ⇒ 2º)
# --------------------------------------------------------------------------- #
@pytest.mark.db
def test_morosidad_dedup_mensual(app_engine: Engine, recordatorio_morosidad: dict) -> None:
    from app.services.recordatorios import enviar_recordatorio_cuota

    org = recordatorio_morosidad["org"]
    cuota_id = recordatorio_morosidad["cuota"]
    mock = MockWhatsAppAdapter()

    hoy_jun = date(2026, 6, 5)
    with Session(app_engine, expire_on_commit=False) as db:
        _set_org(db, org)
        cuota = _get_cuota(db, cuota_id)
        r1 = enviar_recordatorio_cuota(db, cuota=cuota, tipo="MOROSIDAD", hoy=hoy_jun, port=mock)
        r2 = enviar_recordatorio_cuota(db, cuota=cuota, tipo="MOROSIDAD", hoy=hoy_jun, port=mock)
        db.commit()

    assert r1.enviado is True and r1.motivo == "ok"
    assert r2.enviado is False and r2.motivo == "ya_enviado"
    assert len(mock.sent) == 1, "mismo YYYY-MM: máx. 1 morosidad por cuota por mes"

    # Mes distinto (otro ciclo) ⇒ se permite un 2º envío.
    hoy_jul = date(2026, 7, 5)
    with Session(app_engine, expire_on_commit=False) as db:
        _set_org(db, org)
        cuota = _get_cuota(db, cuota_id)
        r3 = enviar_recordatorio_cuota(db, cuota=cuota, tipo="MOROSIDAD", hoy=hoy_jul, port=mock)
        db.commit()

    assert r3.enviado is True and r3.motivo == "ok"
    assert len(mock.sent) == 2

    with app_engine.begin() as conn:
        _set_org(conn, org)
        filas = conn.execute(
            text(
                "SELECT count(*) FROM recordatorio_pago WHERE cuota_id = :c AND tipo = 'MOROSIDAD'"
            ),
            {"c": str(cuota_id)},
        ).scalar_one()
    assert filas == 2, "una fila por ciclo mensual"


# --------------------------------------------------------------------------- #
# 4) forzar=True reenvía sobre la MISMA fila (UPDATE, no INSERT nuevo)
# --------------------------------------------------------------------------- #
@pytest.mark.db
def test_forzar_reenvia_sin_duplicar_fila(app_engine: Engine, recordatorio_proximo: dict) -> None:
    from app.services.recordatorios import enviar_recordatorio_cuota

    org = recordatorio_proximo["org"]
    cuota_id = recordatorio_proximo["cuota"]
    hoy = date(2026, 6, 7)
    mock = MockWhatsAppAdapter()

    with Session(app_engine, expire_on_commit=False) as db:
        _set_org(db, org)
        cuota = _get_cuota(db, cuota_id)
        r1 = enviar_recordatorio_cuota(
            db, cuota=cuota, tipo="PROXIMO_VENCIMIENTO", hoy=hoy, port=mock
        )
        r2 = enviar_recordatorio_cuota(
            db, cuota=cuota, tipo="PROXIMO_VENCIMIENTO", hoy=hoy, port=mock, forzar=True
        )
        db.commit()

    assert r1.enviado is True and r1.motivo == "ok"
    assert r2.enviado is True and r2.motivo == "ok"
    assert len(mock.sent) == 2, "forzar=True reenvía un segundo mensaje"

    with app_engine.begin() as conn:
        _set_org(conn, org)
        filas = conn.execute(
            text(
                "SELECT count(*) FROM recordatorio_pago "
                "WHERE cuota_id = :c AND tipo = 'PROXIMO_VENCIMIENTO'"
            ),
            {"c": str(cuota_id)},
        ).scalar_one()
    assert filas == 1, "forzar reusa la misma fila (UPDATE), no inserta una nueva"


# --------------------------------------------------------------------------- #
# 5) RLS fail-closed de `recordatorio_pago`
# --------------------------------------------------------------------------- #
@pytest.mark.db
def test_rls_recordatorio_sin_contexto_cero_filas(
    app_engine: Engine, recordatorio_proximo: dict
) -> None:
    """Fail-closed: sin `app.current_org`, `recordatorio_pago` no devuelve filas."""
    from app.services.recordatorios import enviar_recordatorio_cuota

    org = recordatorio_proximo["org"]
    cuota_id = recordatorio_proximo["cuota"]
    mock = MockWhatsAppAdapter()

    # Genera una fila para la org.
    with Session(app_engine, expire_on_commit=False) as db:
        _set_org(db, org)
        cuota = _get_cuota(db, cuota_id)
        enviar_recordatorio_cuota(
            db, cuota=cuota, tipo="PROXIMO_VENCIMIENTO", hoy=date(2026, 6, 7), port=mock
        )
        db.commit()

    with app_engine.connect() as conn:
        count = conn.execute(text("SELECT count(*) FROM recordatorio_pago")).scalar_one()
    assert count == 0, "sin contexto de tenant, recordatorio_pago debe devolver 0 filas"


@pytest.mark.db
def test_rls_recordatorio_org_a_no_ve_org_b(app_engine: Engine, owner_engine: Engine) -> None:
    """Con org A fijada se ven sus recordatorios pero ninguno de B."""
    from app.services.recordatorios import enviar_recordatorio_cuota

    org_a = uuid.uuid4()
    org_b = uuid.uuid4()
    monto = Decimal("250.00")
    vence_el = date(2026, 6, 10)
    with owner_engine.begin() as conn:
        ids_a = _sembrar_org_con_cuota(
            conn,
            org=org_a,
            monto=monto,
            vence_el=vence_el,
            estado_cuota="PENDIENTE",
            con_tutor=True,
            tutor_telefono="59177700001",
            tutor_responsable=True,
        )
        ids_b = _sembrar_org_con_cuota(
            conn,
            org=org_b,
            monto=monto,
            vence_el=vence_el,
            estado_cuota="PENDIENTE",
            con_tutor=True,
            tutor_telefono="59177700002",
            tutor_responsable=True,
        )

    try:
        for org, ids in ((org_a, ids_a), (org_b, ids_b)):
            with Session(app_engine, expire_on_commit=False) as db:
                _set_org(db, org)
                cuota = _get_cuota(db, ids["cuota"])
                enviar_recordatorio_cuota(
                    db,
                    cuota=cuota,
                    tipo="PROXIMO_VENCIMIENTO",
                    hoy=date(2026, 6, 7),
                    port=MockWhatsAppAdapter(),
                )
                db.commit()

        with app_engine.begin() as conn:
            _set_org(conn, org_a)
            orgs = {
                str(r)
                for r in conn.execute(text("SELECT org_id FROM recordatorio_pago")).scalars().all()
            }
        assert str(org_a) in orgs
        assert str(org_b) not in orgs, "org A no debe ver recordatorios de org B"
    finally:
        with owner_engine.begin() as conn:
            _limpiar_org(conn, org_a)
            _limpiar_org(conn, org_b)


# --------------------------------------------------------------------------- #
# 6) Webhook GET verify (SIN BD): challenge si coincide el token, 403 si no
# --------------------------------------------------------------------------- #
def _client():
    from app.main import app
    from fastapi.testclient import TestClient

    return TestClient(app)


def test_webhook_whatsapp_verify_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    """`hub.verify_token` correcto ⇒ 200 + body con el challenge en texto plano."""
    from app.api.v1.webhooks import whatsapp as wh

    monkeypatch.setattr(wh.settings, "whatsapp_verify_token", "tok-secreto")
    resp = _client().get(
        "/api/v1/webhooks/whatsapp",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "tok-secreto",
            "hub.challenge": "XYZ",
        },
    )
    assert resp.status_code == 200
    assert resp.text == "XYZ"


def test_webhook_whatsapp_verify_token_invalido(monkeypatch: pytest.MonkeyPatch) -> None:
    """`hub.verify_token` que NO coincide ⇒ 403."""
    from app.api.v1.webhooks import whatsapp as wh

    monkeypatch.setattr(wh.settings, "whatsapp_verify_token", "tok-secreto")
    resp = _client().get(
        "/api/v1/webhooks/whatsapp",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "otro-token",
            "hub.challenge": "XYZ",
        },
    )
    assert resp.status_code == 403
