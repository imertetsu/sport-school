"""Tests del epic Recordatorio de deudores al entrenador.

Cubre el servicio `app.services.recordatorio_deudores` y el endpoint a demanda
`POST /entrenadores/{id}/recordatorio-deudores`:

- **RLS fail-closed** (DoD crítico): la consulta de deudores y el INSERT en
  `recordatorio_deudores` **sin** `app.current_org` ⇒ 0 filas / `WITH CHECK` falla.
- **Idempotencia**: re-correr el mismo período (semana ISO) NO reenvía: ni
  `mock.sent` ni `mock.sent_text` crecen; 1 fila por `(ent, suc, periodo)`.
- **Manual vs cron no colisionan**: períodos distintos ⇒ 2 envíos (2 filas).
- **Endpoint ADMIN-only**: un ENTRENADOR ⇒ 403.
- **Casos borde**: entrenador sin teléfono ⇒ `FALLIDO` sin llamar al puerto;
  sucursal sin deudores ⇒ `SIN_DEUDORES` sin llamar al puerto.

Patrón BD idéntico al resto de la suite: `owner_engine` siembra (saltando RLS), una
`Session(app_engine, expire_on_commit=False)` ejercita el servicio bajo RLS real
fijando `app.current_org` con `set_config(..., true)` (SET LOCAL). El adaptador
WhatsApp es el `MockWhatsAppAdapter` (acumula en `.sent`/`.sent_text`, no envía).

Los `@pytest.mark.db` los corre main contra Postgres recién migrado (0014).
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
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session


def _set_org(conn, org: uuid.UUID) -> None:
    """Fija `app.current_org` para la tx (SET LOCAL vía set_config 3er arg=true)."""
    conn.execute(text("SELECT set_config('app.current_org', :o, true)"), {"o": str(org)})


def _sembrar(
    conn,
    *,
    org: uuid.UUID,
    coach_telefono: str | None,
    con_deudor: bool,
    coach_activo: bool = True,
) -> dict:
    """Org + sucursal + entrenador (usuario+perfil) asignado a la sucursal.

    Si `con_deudor`, agrega 1 deportista + inscripción + 1 cuota VENCIDA (monto 300, pagado
    0 ⇒ saldo 300). Devuelve los ids sembrados.
    """
    suc = uuid.uuid4()
    coach_user = uuid.uuid4()
    coach = uuid.uuid4()
    email = f"coach_{uuid.uuid4().hex}@test.bo"

    conn.execute(
        text(
            "INSERT INTO organizacion (id, nombre, pais, moneda, modo_cobro_default, "
            "prorratea_primer_periodo, estado, created_at, updated_at) "
            "VALUES (:id,'Org Deudores (test)','BO','BOB','ANIVERSARIO',true,'ACTIVA',now(),now()) "
            "ON CONFLICT (id) DO NOTHING"
        ),
        {"id": str(org)},
    )
    conn.execute(
        text(
            "INSERT INTO sucursal (id, org_id, nombre, created_at, updated_at) "
            "VALUES (:id,:org,'Sucursal Centro',now(),now())"
        ),
        {"id": str(suc), "org": str(org)},
    )
    conn.execute(
        text(
            "INSERT INTO usuario (id, org_id, email, password_hash, role, nombre, activo, "
            "created_at, updated_at) "
            "VALUES (:id,:org,:email,'x','ENTRENADOR','Coach Activo',:act,now(),now())"
        ),
        {"id": str(coach_user), "org": str(org), "email": email, "act": coach_activo},
    )
    conn.execute(
        text(
            "INSERT INTO entrenador (id, org_id, usuario_id, nombres, telefono, disciplinas, "
            "created_at, updated_at) "
            "VALUES (:id,:org,:uid,'Carlos Coach',:tel,'[]'::jsonb,now(),now())"
        ),
        {"id": str(coach), "org": str(org), "uid": str(coach_user), "tel": coach_telefono},
    )
    conn.execute(
        text(
            "INSERT INTO entrenador_sucursal (id, org_id, entrenador_id, sucursal_id, created_at) "
            "VALUES (:id,:org,:ent,:suc,now())"
        ),
        {"id": str(uuid.uuid4()), "org": str(org), "ent": str(coach), "suc": str(suc)},
    )

    deportista = None
    if con_deudor:
        deportista = uuid.uuid4()
        insc = uuid.uuid4()
        cuota = uuid.uuid4()
        conn.execute(
            text(
                "INSERT INTO deportista (id, org_id, sucursal_id, nombres, ap_paterno, "
                "created_at, updated_at) "
                "VALUES (:id,:org,:suc,'Juan','Perez',now(),now())"
            ),
            {"id": str(deportista), "org": str(org), "suc": str(suc)},
        )
        conn.execute(
            text(
                "INSERT INTO inscripcion (id, org_id, deportista_id, fecha_inscripcion, "
                "monto_mensual, estado, created_at, updated_at) "
                "VALUES (:id,:org,:al,:f,300,'ACTIVA',now(),now())"
            ),
            {"id": str(insc), "org": str(org), "al": str(deportista), "f": date(2026, 1, 10)},
        )
        conn.execute(
            text(
                "INSERT INTO cuota (id, org_id, inscripcion_id, periodo_inicio, periodo_fin, "
                "vence_el, monto, monto_pagado, estado, es_prorrateo, generada_en) "
                "VALUES (:id,:org,:insc,:pi,:pf,:v,300,0,'VENCIDO',false,now())"
            ),
            {
                "id": str(cuota),
                "org": str(org),
                "insc": str(insc),
                "pi": date(2026, 4, 10),
                "pf": date(2026, 5, 10),
                "v": date(2026, 5, 10),
            },
        )

    return {"suc": suc, "coach_user": coach_user, "coach": coach, "deportista": deportista}


def _limpiar(conn, org: uuid.UUID) -> None:
    """Borra todo lo sembrado de una org (orden FK-safe)."""
    conn.execute(text("DELETE FROM recordatorio_deudores WHERE org_id = :o"), {"o": str(org)})
    conn.execute(text("DELETE FROM entrenador_sucursal WHERE org_id = :o"), {"o": str(org)})
    conn.execute(text("DELETE FROM cuota WHERE org_id = :o"), {"o": str(org)})
    conn.execute(text("DELETE FROM inscripcion WHERE org_id = :o"), {"o": str(org)})
    conn.execute(text("DELETE FROM deportista WHERE org_id = :o"), {"o": str(org)})
    conn.execute(text("DELETE FROM entrenador WHERE org_id = :o"), {"o": str(org)})
    conn.execute(text("DELETE FROM usuario WHERE org_id = :o"), {"o": str(org)})
    conn.execute(text("DELETE FROM sucursal WHERE org_id = :o"), {"o": str(org)})
    conn.execute(text("DELETE FROM organizacion WHERE id = :o"), {"o": str(org)})


# --------------------------------------------------------------------------- #
# Fixtures de siembra (con BD)
# --------------------------------------------------------------------------- #
@pytest.fixture()
def org_con_deudor(owner_engine: Engine) -> Iterator[dict]:
    """Org con 1 entrenador (con teléfono) + sucursal con 1 deudor (cuota VENCIDA)."""
    org = uuid.uuid4()
    with owner_engine.begin() as conn:
        ids = _sembrar(conn, org=org, coach_telefono="59177712345", con_deudor=True)
    yield {"org": org, **ids}
    with owner_engine.begin() as conn:
        _limpiar(conn, org)


@pytest.fixture()
def org_sin_telefono(owner_engine: Engine) -> Iterator[dict]:
    """Org con 1 entrenador SIN teléfono + sucursal con 1 deudor."""
    org = uuid.uuid4()
    with owner_engine.begin() as conn:
        ids = _sembrar(conn, org=org, coach_telefono=None, con_deudor=True)
    yield {"org": org, **ids}
    with owner_engine.begin() as conn:
        _limpiar(conn, org)


@pytest.fixture()
def org_sin_deudores(owner_engine: Engine) -> Iterator[dict]:
    """Org con 1 entrenador (con teléfono) + sucursal SIN deudores."""
    org = uuid.uuid4()
    with owner_engine.begin() as conn:
        ids = _sembrar(conn, org=org, coach_telefono="59177700000", con_deudor=False)
    yield {"org": org, **ids}
    with owner_engine.begin() as conn:
        _limpiar(conn, org)


def _get_entrenador(db: Session, ent_id: uuid.UUID):
    from app.models.entrenador import Entrenador

    ent = db.get(Entrenador, ent_id)
    assert ent is not None
    return ent


# --------------------------------------------------------------------------- #
# 1) Consulta de deudores (CONTRATO 2): saldo = SUM(monto - monto_pagado)
# --------------------------------------------------------------------------- #
@pytest.mark.db
def test_consulta_deudores_suma_saldo(app_engine: Engine, org_con_deudor: dict) -> None:
    from app.services.recordatorio_deudores import deudores_de_sucursal

    with Session(app_engine, expire_on_commit=False) as db:
        _set_org(db, org_con_deudor["org"])
        deudores = deudores_de_sucursal(db, sucursal_id=org_con_deudor["suc"])

    assert len(deudores) == 1
    d = deudores[0]
    assert d.nombre == "Perez Juan"  # ap_paterno (sin ap_materno) + nombres
    assert d.num_cuotas_vencidas == 1
    assert d.monto_adeudado == Decimal("300.00")


# --------------------------------------------------------------------------- #
# 2) Idempotencia (DoD CRÍTICO): mismo período ⇒ 1 envío, 1 fila
# --------------------------------------------------------------------------- #
@pytest.mark.db
def test_idempotencia_mismo_periodo(app_engine: Engine, org_con_deudor: dict) -> None:
    from app.services.recordatorio_deudores import enviar_digests_org

    org = org_con_deudor["org"]
    periodo = "2026-W23"
    mock = MockWhatsAppAdapter()

    with Session(app_engine, expire_on_commit=False) as db:
        _set_org(db, org)
        n1 = enviar_digests_org(db, org_id=org, periodo=periodo, origen="CRON", port=mock)
        n2 = enviar_digests_org(db, org_id=org, periodo=periodo, origen="CRON", port=mock)
        db.commit()

    assert n1 == 1, "primer envío: 1 sucursal con deudores ENVIADA"
    assert n2 == 0, "re-correr el mismo período no reenvía (idempotente)"
    # 2 mensajes (plantilla + detalle) UNA sola vez; el 2º run no llama al puerto.
    assert len(mock.sent) == 1, "una plantilla, no dos"
    assert len(mock.sent_text) == 1, "un detalle de texto, no dos"

    with app_engine.begin() as conn:
        _set_org(conn, org)
        filas = conn.execute(
            text("SELECT count(*) FROM recordatorio_deudores WHERE periodo = :p"),
            {"p": periodo},
        ).scalar_one()
    assert filas == 1, "exactamente 1 fila (UNIQUE ent,suc,periodo)"


# --------------------------------------------------------------------------- #
# 3) Manual vs cron NO colisionan (períodos distintos ⇒ 2 envíos / 2 filas)
# --------------------------------------------------------------------------- #
@pytest.mark.db
def test_manual_y_cron_no_colisionan(app_engine: Engine, org_con_deudor: dict) -> None:
    from app.services.recordatorio_deudores import enviar_digest_entrenador, enviar_digests_org

    org = org_con_deudor["org"]
    coach_id = org_con_deudor["coach"]
    mock = MockWhatsAppAdapter()

    with Session(app_engine, expire_on_commit=False) as db:
        _set_org(db, org)
        # Cron (semana ISO).
        enviar_digests_org(db, org_id=org, periodo="2026-W23", origen="CRON", port=mock)
        # Manual (período único): NO colisiona con el del cron.
        ent = _get_entrenador(db, coach_id)
        res = enviar_digest_entrenador(
            db,
            org_id=org,
            entrenador=ent,
            periodo="MANUAL-20260606T101500",
            origen="MANUAL",
            port=mock,
        )
        db.commit()

    assert [r.estado for r in res] == ["ENVIADO"]
    # Dos períodos distintos ⇒ dos envíos (2 plantillas, 2 detalles).
    assert len(mock.sent) == 2
    assert len(mock.sent_text) == 2

    with app_engine.begin() as conn:
        _set_org(conn, org)
        filas = conn.execute(
            text("SELECT count(*) FROM recordatorio_deudores WHERE entrenador_id = :e"),
            {"e": str(coach_id)},
        ).scalar_one()
    assert filas == 2, "una fila por período (cron + manual)"


# --------------------------------------------------------------------------- #
# 4) Sin teléfono ⇒ FALLIDO sin llamar al puerto
# --------------------------------------------------------------------------- #
@pytest.mark.db
def test_sin_telefono_fallido_sin_enviar(app_engine: Engine, org_sin_telefono: dict) -> None:
    from app.services.recordatorio_deudores import enviar_digests_org

    org = org_sin_telefono["org"]
    mock = MockWhatsAppAdapter()

    with Session(app_engine, expire_on_commit=False) as db:
        _set_org(db, org)
        enviados = enviar_digests_org(db, org_id=org, periodo="2026-W23", origen="CRON", port=mock)
        db.commit()

    assert enviados == 0, "sin teléfono no cuenta como ENVIADO"
    assert len(mock.sent) == 0 and len(mock.sent_text) == 0, "sin teléfono no llama al puerto"

    with app_engine.begin() as conn:
        _set_org(conn, org)
        row = conn.execute(
            text("SELECT estado, destino FROM recordatorio_deudores WHERE org_id = :o"),
            {"o": str(org)},
        ).one()
    assert row.estado == "FALLIDO"
    assert row.destino is None


# --------------------------------------------------------------------------- #
# 5) Sin deudores ⇒ SIN_DEUDORES sin llamar al puerto
# --------------------------------------------------------------------------- #
@pytest.mark.db
def test_sin_deudores_sin_enviar(app_engine: Engine, org_sin_deudores: dict) -> None:
    from app.services.recordatorio_deudores import enviar_digests_org

    org = org_sin_deudores["org"]
    mock = MockWhatsAppAdapter()

    with Session(app_engine, expire_on_commit=False) as db:
        _set_org(db, org)
        enviados = enviar_digests_org(db, org_id=org, periodo="2026-W23", origen="CRON", port=mock)
        db.commit()

    assert enviados == 0
    assert len(mock.sent) == 0 and len(mock.sent_text) == 0, "sin deudores no llama al puerto"

    with app_engine.begin() as conn:
        _set_org(conn, org)
        row = conn.execute(
            text("SELECT estado FROM recordatorio_deudores WHERE org_id = :o"),
            {"o": str(org)},
        ).one()
    assert row.estado == "SIN_DEUDORES"


# --------------------------------------------------------------------------- #
# 6) RLS fail-closed: consulta + INSERT sin contexto ⇒ 0 filas
# --------------------------------------------------------------------------- #
@pytest.mark.db
def test_rls_fail_closed(app_engine: Engine, org_con_deudor: dict) -> None:
    """Sin `app.current_org`: la consulta de deudores y `recordatorio_deudores` dan 0 filas."""
    from app.services.recordatorio_deudores import deudores_de_sucursal, enviar_digests_org

    org = org_con_deudor["org"]
    suc = org_con_deudor["suc"]
    mock = MockWhatsAppAdapter()

    # Genera una fila bajo contexto.
    with Session(app_engine, expire_on_commit=False) as db:
        _set_org(db, org)
        enviar_digests_org(db, org_id=org, periodo="2026-W23", origen="CRON", port=mock)
        db.commit()

    # Sin contexto: la consulta de deudores no ve cuotas, y recordatorio_deudores da 0.
    with Session(app_engine, expire_on_commit=False) as db:
        sin_contexto = deudores_de_sucursal(db, sucursal_id=suc)
    assert sin_contexto == [], "sin contexto de tenant, la consulta de deudores da 0 filas"

    with app_engine.connect() as conn:
        count = conn.execute(text("SELECT count(*) FROM recordatorio_deudores")).scalar_one()
    assert count == 0, "sin contexto de tenant, recordatorio_deudores devuelve 0 filas"


# --------------------------------------------------------------------------- #
# 7) Endpoint a demanda — gating (ADMIN-only) + casos de negocio
# --------------------------------------------------------------------------- #
def _client_or_skip():
    if not os.getenv("DATABASE_URL"):
        pytest.skip("DATABASE_URL no definido; requiere Postgres migrado")
    from app.main import app
    from fastapi.testclient import TestClient

    return TestClient(app)


def _token(user_id: uuid.UUID, org_id: uuid.UUID, role: str) -> str:
    return create_access_token(user_id=str(user_id), org_id=str(org_id), role=role, sucursal_ids=[])


@pytest.mark.db
def test_endpoint_entrenador_403(org_con_deudor: dict) -> None:
    """Un ENTRENADOR NO puede disparar el recordatorio (ADMIN-only) ⇒ 403."""
    client = _client_or_skip()
    token = _token(org_con_deudor["coach_user"], org_con_deudor["org"], "ENTRENADOR")
    resp = client.post(
        f"/api/v1/entrenadores/{org_con_deudor['coach']}/recordatorio-deudores",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


@pytest.mark.db
def test_endpoint_admin_envia(org_con_deudor: dict) -> None:
    """ADMIN dispara el digest ⇒ 200, 1 sucursal ENVIADO, período MANUAL-*."""
    client = _client_or_skip()
    admin = uuid.uuid4()
    # El admin debe existir en la org para emitir un token operativo coherente.
    from sqlalchemy import create_engine

    owner = create_engine(os.environ["MIGRATION_DATABASE_URL"], future=True)
    with owner.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO usuario (id, org_id, email, password_hash, role, nombre, activo, "
                "created_at, updated_at) "
                "VALUES (:id,:org,:email,'x','ADMIN','Admin',true,now(),now())"
            ),
            {
                "id": str(admin),
                "org": str(org_con_deudor["org"]),
                "email": f"admin_{uuid.uuid4().hex}@test.bo",
            },
        )
    owner.dispose()

    token = _token(admin, org_con_deudor["org"], "ADMIN")
    resp = client.post(
        f"/api/v1/entrenadores/{org_con_deudor['coach']}/recordatorio-deudores",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["enviados"] == 1
    assert body["periodo"].startswith("MANUAL-")
    assert len(body["sucursales"]) == 1
    assert body["sucursales"][0]["estado"] == "ENVIADO"
    assert body["sucursales"][0]["num_deudores"] == 1


@pytest.mark.db
def test_endpoint_inexistente_404(org_con_deudor: dict) -> None:
    """Entrenador inexistente en la org ⇒ 404."""
    client = _client_or_skip()
    admin = uuid.uuid4()
    token = _token(admin, org_con_deudor["org"], "ADMIN")
    resp = client.post(
        f"/api/v1/entrenadores/{uuid.uuid4()}/recordatorio-deudores",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 404
