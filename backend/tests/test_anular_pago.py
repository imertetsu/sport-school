"""Tests del epic anular-pago (reversa CON rastro de un pago efectivo).

Dos capas, igual que el resto de la suite:

- **Sin BD** (rápidos, siempre corren): validación de `AnularPagoIn` (motivo
  obligatorio), `PagoError.code` discriminable, el mapeo `code -> status` del router y
  las formas de los schemas de salida.
- **Con BD** (`@pytest.mark.db`, requieren Postgres migrado a 0025 + RLS + rol
  `latinosport_app`): anular efectivo CONFIRMADO → ANULADO + cuotas cobrables + crédito
  revertido; rechazo QR; inexistente → 404; idempotencia (anular 2x sin doble reversa);
  crédito consumido → bloquea; multi-cuota revierte todas; RLS (pago de otra org
  invisible); lista `GET /pagos` con `anulable` correcto.

Los `@pytest.mark.db` los corre main en la fase de cierre contra Postgres a 0025.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import date, timedelta
from decimal import Decimal

import pytest
from app.api.v1.cobranza import _ANULAR_PAGO_STATUS
from app.schemas.cobranza import (
    AnularPagoIn,
    CuotaRevertida,
    PagoAnuladoOut,
    PagoEfectivoIn,
    PagoListItem,
)
from app.services import pagos as pagos_svc
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session


# =========================================================================== #
# SIN BD — schema AnularPagoIn (motivo obligatorio, no vacío)
# =========================================================================== #
def test_anular_pago_in_motivo_valido() -> None:
    obj = AnularPagoIn(motivo="Tecleo doble por error")
    assert obj.motivo == "Tecleo doble por error"


def test_anular_pago_in_motivo_vacio_falla() -> None:
    """`motivo` vacío -> ValidationError (=> 422 en la API)."""
    with pytest.raises(ValidationError):
        AnularPagoIn(motivo="")


def test_anular_pago_in_motivo_ausente_falla() -> None:
    with pytest.raises(ValidationError):
        AnularPagoIn()  # type: ignore[call-arg]


# =========================================================================== #
# SIN BD — PagoError.code discriminable + mapeo a HTTP del router
# =========================================================================== #
# =========================================================================== #
# SIN BD — schema PagoEfectivoIn: método (efectivo/QR) + fecha de pago manual
# =========================================================================== #
def test_pago_efectivo_in_metodo_y_fecha() -> None:
    """`metodo` default EFECTIVO, acepta QR y una `fecha_pago` opcional (registro manual)."""
    base = {"cuota_ids": [str(uuid.uuid4())]}
    assert PagoEfectivoIn(**base).metodo == "EFECTIVO"  # type: ignore[arg-type]
    assert PagoEfectivoIn(**base).fecha_pago is None  # type: ignore[arg-type]
    qr = PagoEfectivoIn(**{**base, "metodo": "QR", "fecha_pago": "2026-03-05"})  # type: ignore[arg-type]
    assert qr.metodo == "QR"
    assert qr.fecha_pago == date(2026, 3, 5)


def test_pago_efectivo_in_metodo_invalido_falla() -> None:
    """Un `metodo` fuera de {EFECTIVO, QR} -> ValidationError (=> 422)."""
    with pytest.raises(ValidationError):
        PagoEfectivoIn(cuota_ids=[uuid.uuid4()], metodo="TARJETA")  # type: ignore[arg-type]


def test_pago_error_code_discriminable() -> None:
    err = pagos_svc.PagoError("x", code="no_encontrado")
    assert err.code == "no_encontrado"


def test_pago_error_code_default_es_el_mensaje() -> None:
    """Errores históricos sin code explícito mantienen el mensaje como code."""
    err = pagos_svc.PagoError("Cuota no encontrada")
    assert err.code == "Cuota no encontrada"


def test_mapeo_codes_a_status() -> None:
    """El router mapea cada code de anulación al status HTTP esperado (C4)."""
    assert _ANULAR_PAGO_STATUS["no_encontrado"] == 404
    assert _ANULAR_PAGO_STATUS["no_anulable_qr"] == 422
    assert _ANULAR_PAGO_STATUS["estado_no_anulable"] == 422
    assert _ANULAR_PAGO_STATUS["credito_consumido"] == 409


# =========================================================================== #
# SIN BD — formas de los schemas de salida
# =========================================================================== #
def test_pago_anulado_out_shape() -> None:
    out = PagoAnuladoOut(
        id=uuid.uuid4(),
        estado="ANULADO",
        motivo_anulacion="error",
        anulado_en=date.today().isoformat() + "T00:00:00+00:00",  # type: ignore[arg-type]
        credito_revertido=Decimal("0.00"),
        cuotas_revertidas=[
            CuotaRevertida(
                cuota_id=uuid.uuid4(), saldo_restante=Decimal("100.00"), estado="PENDIENTE"
            )
        ],
    )
    assert out.estado == "ANULADO"
    assert out.cuotas_revertidas[0].estado == "PENDIENTE"


def test_pago_list_item_anulable_flag() -> None:
    item = PagoListItem(
        id=uuid.uuid4(),
        fecha=date.today().isoformat() + "T00:00:00+00:00",  # type: ignore[arg-type]
        metodo="EFECTIVO",
        estado="CONFIRMADO",
        monto=Decimal("100.00"),
        anulable=True,
    )
    assert item.anulable is True
    assert item.deportista_nombre is None


# =========================================================================== #
# CON BD — fixture: org + inscripción + 2 cuotas + (opcional) pago efectivo
# =========================================================================== #
@pytest.fixture()
def anular_fixture(owner_engine: Engine) -> Iterator[dict]:
    """Org + sucursal + deportista (MAYÚSCULAS) + inscripción + 2 cuotas PENDIENTE.

    Cuotas FIFO a futuro (no vencidas), mismo monto 100. Limpia al final (FK-safe).
    """
    org = uuid.uuid4()
    suc = uuid.uuid4()
    al = uuid.uuid4()
    usuario = uuid.uuid4()
    insc = uuid.uuid4()
    c1 = uuid.uuid4()
    c2 = uuid.uuid4()
    monto = Decimal("100.00")

    with owner_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO organizacion (id, nombre, pais, moneda, modo_cobro_default, "
                "prorratea_primer_periodo, created_at, updated_at) "
                "VALUES (:id,'Org Anular (test)','BO','BOB','ANIVERSARIO',true,now(),now())"
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
                "INSERT INTO usuario (id, org_id, email, password_hash, role, nombre, activo, "
                "created_at, updated_at) "
                "VALUES (:id,:org,:email,'x','ADMIN','Admin Anular',true,now(),now())"
            ),
            {"id": str(usuario), "org": str(org), "email": f"an_{uuid.uuid4().hex}@test.bo"},
        )
        conn.execute(
            text(
                "INSERT INTO deportista (id, org_id, sucursal_id, nombres, created_at, updated_at) "
                "VALUES (:id,:org,:suc,'JUAN PEREZ',now(),now())"
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
        hoy = date.today()
        for cid, pi, pf, v in (
            (c1, hoy, hoy + timedelta(days=30), hoy + timedelta(days=30)),
            (c2, hoy + timedelta(days=30), hoy + timedelta(days=60), hoy + timedelta(days=60)),
        ):
            conn.execute(
                text(
                    "INSERT INTO cuota (id, org_id, inscripcion_id, periodo_inicio, periodo_fin, "
                    "vence_el, monto, monto_pagado, estado, es_prorrateo, generada_en) "
                    "VALUES (:id,:org,:insc,:pi,:pf,:v,:m,0,'PENDIENTE',false,now())"
                ),
                {
                    "id": str(cid),
                    "org": str(org),
                    "insc": str(insc),
                    "pi": pi,
                    "pf": pf,
                    "v": v,
                    "m": monto,
                },
            )

    yield {
        "org": org,
        "inscripcion": insc,
        "usuario": usuario,
        "deportista": al,
        "c1": c1,
        "c2": c2,
        "monto": monto,
    }

    with owner_engine.begin() as conn:
        conn.execute(text("DELETE FROM pago_cuota WHERE org_id = :o"), {"o": str(org)})
        conn.execute(text("DELETE FROM pago WHERE org_id = :o"), {"o": str(org)})
        conn.execute(text("DELETE FROM credito WHERE org_id = :o"), {"o": str(org)})
        conn.execute(text("DELETE FROM cuota WHERE org_id = :o"), {"o": str(org)})
        conn.execute(text("DELETE FROM inscripcion WHERE org_id = :o"), {"o": str(org)})
        conn.execute(text("DELETE FROM usuario WHERE org_id = :o"), {"o": str(org)})
        conn.execute(text("DELETE FROM deportista WHERE org_id = :o"), {"o": str(org)})
        conn.execute(text("DELETE FROM sucursal WHERE org_id = :o"), {"o": str(org)})
        conn.execute(text("DELETE FROM organizacion WHERE id = :o"), {"o": str(org)})


def _set_org(conn, org: uuid.UUID) -> None:
    conn.execute(text("SELECT set_config('app.current_org', :o, true)"), {"o": str(org)})


# =========================================================================== #
# CON BD — C-Anular-OK: efectivo CONFIRMADO → ANULADO + cuota cobrable + crédito revertido
# =========================================================================== #
@pytest.mark.db
def test_anular_efectivo_revierte_cuota_y_credito(app_engine: Engine, anular_fixture: dict) -> None:
    org = anular_fixture["org"]
    insc = anular_fixture["inscripcion"]
    c1 = anular_fixture["c1"]

    # Pago sobre c1 (saldo 100) con sobrepago de 30 → crédito 30, c1 PAGADO.
    with Session(app_engine, expire_on_commit=False) as db:
        _set_org(db, org)
        pago = pagos_svc.registrar_pago_efectivo(
            db,
            org_id=org,
            cuota_ids=[c1],
            registrado_por=anular_fixture["usuario"],
            monto_recibido=Decimal("130.00"),
        )
        db.commit()
        pago_id = pago.id
        assert pago.credito_generado == Decimal("30.00")

    # Anular el pago.
    with Session(app_engine, expire_on_commit=False) as db:
        _set_org(db, org)
        anulado = pagos_svc.anular_pago(
            db,
            org_id=org,
            pago_id=pago_id,
            anulado_por=anular_fixture["usuario"],
            motivo="Monto equivocado",
        )
        db.commit()
        assert anulado.estado == "ANULADO"
        assert anulado.motivo_anulacion == "Monto equivocado"
        assert anulado.anulado_por == anular_fixture["usuario"]
        assert anulado.anulado_en is not None

    with app_engine.begin() as conn:
        _set_org(conn, org)
        c1_row = conn.execute(
            text("SELECT estado, monto_pagado FROM cuota WHERE id=:id"), {"id": str(c1)}
        ).one()
        saldo_credito = conn.execute(
            text("SELECT COALESCE(SUM(saldo),0) FROM credito WHERE inscripcion_id=:i"),
            {"i": str(insc)},
        ).scalar_one()
        puentes = conn.execute(
            text("SELECT count(*) FROM pago_cuota WHERE pago_id=:p"), {"p": str(pago_id)}
        ).scalar_one()
        pago_row = conn.execute(
            text("SELECT estado, numero_recibo FROM pago WHERE id=:id"), {"id": str(pago_id)}
        ).one()

    # La cuota vuelve a cobrable (PENDIENTE: no vencida, sin abono).
    assert c1_row.estado == "PENDIENTE"
    assert c1_row.monto_pagado == Decimal("0.00")
    # El crédito generado por el pago se deshizo por completo.
    assert saldo_credito == Decimal("0.00")
    # Las filas puente se borraron.
    assert puentes == 0
    # El pago queda ANULADO (rastro), numero_recibo intacto.
    assert pago_row.estado == "ANULADO"
    assert pago_row.numero_recibo is not None


@pytest.mark.db
def test_pago_qr_manual_guarda_fecha_y_es_anulable(
    app_engine: Engine, anular_fixture: dict
) -> None:
    """Un pago QR registrado A MANO guarda `metodo=QR` + la fecha elegida en `pagado_en`
    y ES anulable (tiene `registrado_por`). Mismo camino que el efectivo, otra etiqueta."""
    org = anular_fixture["org"]
    c1 = anular_fixture["c1"]

    with Session(app_engine, expire_on_commit=False) as db:
        _set_org(db, org)
        pago = pagos_svc.registrar_pago_efectivo(
            db,
            org_id=org,
            cuota_ids=[c1],
            registrado_por=anular_fixture["usuario"],
            metodo="QR",
            fecha_pago=date(2026, 3, 5),
        )
        db.commit()
        pago_id = pago.id
        assert pago.metodo == "QR"
        assert pago.pagado_en is not None
        assert (pago.pagado_en.year, pago.pagado_en.month, pago.pagado_en.day) == (2026, 3, 5)

    # Registrado a mano ⇒ anulable aunque sea QR.
    with Session(app_engine, expire_on_commit=False) as db:
        _set_org(db, org)
        anulado = pagos_svc.anular_pago(
            db, org_id=org, pago_id=pago_id, anulado_por=anular_fixture["usuario"], motivo="test"
        )
        db.commit()
        assert anulado.estado == "ANULADO"


# =========================================================================== #
# CON BD — C-Multi-cuota: revierte TODAS las filas puente
# =========================================================================== #
@pytest.mark.db
def test_anular_multi_cuota_revierte_todas(app_engine: Engine, anular_fixture: dict) -> None:
    org = anular_fixture["org"]
    c1, c2 = anular_fixture["c1"], anular_fixture["c2"]

    with Session(app_engine, expire_on_commit=False) as db:
        _set_org(db, org)
        pago = pagos_svc.registrar_pago_efectivo(
            db,
            org_id=org,
            cuota_ids=[c1, c2],
            registrado_por=anular_fixture["usuario"],
            monto_recibido=Decimal("150.00"),  # c1 PAGADO, c2 PARCIAL (50)
        )
        db.commit()
        pago_id = pago.id

    with Session(app_engine, expire_on_commit=False) as db:
        _set_org(db, org)
        pagos_svc.anular_pago(
            db,
            org_id=org,
            pago_id=pago_id,
            anulado_por=anular_fixture["usuario"],
            motivo="Deportista equivocado",
        )
        db.commit()

    with app_engine.begin() as conn:
        _set_org(conn, org)
        rows = conn.execute(
            text("SELECT estado, monto_pagado FROM cuota WHERE id IN (:a,:b)"),
            {"a": str(c1), "b": str(c2)},
        ).all()
        puentes = conn.execute(
            text("SELECT count(*) FROM pago_cuota WHERE pago_id=:p"), {"p": str(pago_id)}
        ).scalar_one()

    # Ambas cuotas vuelven a PENDIENTE con monto_pagado 0; todos los puentes borrados.
    assert all(r.estado == "PENDIENTE" for r in rows)
    assert all(r.monto_pagado == Decimal("0.00") for r in rows)
    assert puentes == 0


# =========================================================================== #
# CON BD — C-Idempotente: anular 2x → sin doble reversa (CRÍTICO)
# =========================================================================== #
@pytest.mark.db
def test_anular_dos_veces_idempotente(app_engine: Engine, anular_fixture: dict) -> None:
    org = anular_fixture["org"]
    insc = anular_fixture["inscripcion"]
    c1 = anular_fixture["c1"]

    with Session(app_engine, expire_on_commit=False) as db:
        _set_org(db, org)
        pago = pagos_svc.registrar_pago_efectivo(
            db,
            org_id=org,
            cuota_ids=[c1],
            registrado_por=anular_fixture["usuario"],
            monto_recibido=Decimal("130.00"),
        )
        db.commit()
        pago_id = pago.id

    # 1ª anulación.
    with Session(app_engine, expire_on_commit=False) as db:
        _set_org(db, org)
        pagos_svc.anular_pago(
            db, org_id=org, pago_id=pago_id, anulado_por=anular_fixture["usuario"], motivo="x"
        )
        db.commit()

    # 2ª anulación (no-op idempotente): no debe cambiar cuota ni crédito.
    with Session(app_engine, expire_on_commit=False) as db:
        _set_org(db, org)
        anulado2 = pagos_svc.anular_pago(
            db, org_id=org, pago_id=pago_id, anulado_por=anular_fixture["usuario"], motivo="y"
        )
        db.commit()
        # El motivo NO se sobreescribe (no-op): conserva el de la 1ª anulación.
        assert anulado2.estado == "ANULADO"
        assert anulado2.motivo_anulacion == "x"

    with app_engine.begin() as conn:
        _set_org(conn, org)
        c1_row = conn.execute(
            text("SELECT estado, monto_pagado FROM cuota WHERE id=:id"), {"id": str(c1)}
        ).one()
        saldo_credito = conn.execute(
            text("SELECT COALESCE(SUM(saldo),0) FROM credito WHERE inscripcion_id=:i"),
            {"i": str(insc)},
        ).scalar_one()

    # Sin doble reversa: monto_pagado no se vuelve negativo, crédito sigue en 0.
    assert c1_row.estado == "PENDIENTE"
    assert c1_row.monto_pagado == Decimal("0.00")
    assert saldo_credito == Decimal("0.00")


# =========================================================================== #
# CON BD — C-QR-rechazo: anular un pago QR → no_anulable_qr
# =========================================================================== #
@pytest.mark.db
def test_anular_qr_rechazo(app_engine: Engine, anular_fixture: dict) -> None:
    org = anular_fixture["org"]
    c1 = anular_fixture["c1"]
    qr_ref = f"qr_an_{uuid.uuid4().hex}"

    with Session(app_engine, expire_on_commit=False) as db:
        _set_org(db, org)
        pago = pagos_svc.crear_pago_qr(db, org_id=org, cuota_ids=[c1], qr_ref=qr_ref)
        db.commit()
        pago_id = pago.id

    with Session(app_engine, expire_on_commit=False) as db:
        _set_org(db, org)
        with pytest.raises(pagos_svc.PagoError) as exc:
            pagos_svc.anular_pago(
                db, org_id=org, pago_id=pago_id, anulado_por=anular_fixture["usuario"], motivo="x"
            )
        assert exc.value.code == "no_anulable_qr"


# =========================================================================== #
# CON BD — C-404: anular un pago inexistente → no_encontrado
# =========================================================================== #
@pytest.mark.db
def test_anular_inexistente(app_engine: Engine, anular_fixture: dict) -> None:
    org = anular_fixture["org"]
    with Session(app_engine, expire_on_commit=False) as db:
        _set_org(db, org)
        with pytest.raises(pagos_svc.PagoError) as exc:
            pagos_svc.anular_pago(
                db,
                org_id=org,
                pago_id=uuid.uuid4(),
                anulado_por=anular_fixture["usuario"],
                motivo="x",
            )
        assert exc.value.code == "no_encontrado"


# =========================================================================== #
# CON BD — C-Estado: anular un pago no CONFIRMADO → estado_no_anulable
# =========================================================================== #
@pytest.mark.db
def test_anular_estado_no_anulable(app_engine: Engine, anular_fixture: dict) -> None:
    """Un pago PENDIENTE (no aplicado) no es anulable por este flujo."""
    org = anular_fixture["org"]
    pago_id = uuid.uuid4()
    with app_engine.begin() as conn:
        _set_org(conn, org)
        conn.execute(
            text(
                "INSERT INTO pago (id, org_id, metodo, estado, monto, credito_aplicado, "
                "credito_generado, registrado_por, created_at) "
                "VALUES (:id,:org,'EFECTIVO','PENDIENTE',100,0,0,:reg,now())"
            ),
            # registrado_por seteado: es un pago manual (pasa la guarda de "a mano");
            # lo que lo hace no anulable es el ESTADO PENDIENTE, no el método.
            {"id": str(pago_id), "org": str(org), "reg": str(anular_fixture["usuario"])},
        )

    with Session(app_engine, expire_on_commit=False) as db:
        _set_org(db, org)
        with pytest.raises(pagos_svc.PagoError) as exc:
            pagos_svc.anular_pago(
                db, org_id=org, pago_id=pago_id, anulado_por=anular_fixture["usuario"], motivo="x"
            )
        assert exc.value.code == "estado_no_anulable"


# =========================================================================== #
# CON BD — C-Crédito-consumido: el crédito ya fue consumido por un pago posterior → bloquea
# =========================================================================== #
@pytest.mark.db
def test_anular_credito_consumido_bloquea(app_engine: Engine, anular_fixture: dict) -> None:
    org = anular_fixture["org"]
    c1, c2 = anular_fixture["c1"], anular_fixture["c2"]

    # Pago 1 sobre c1 con sobrepago 30 → crédito 30, c1 PAGADO.
    with Session(app_engine, expire_on_commit=False) as db:
        _set_org(db, org)
        pago1 = pagos_svc.registrar_pago_efectivo(
            db,
            org_id=org,
            cuota_ids=[c1],
            registrado_por=anular_fixture["usuario"],
            monto_recibido=Decimal("130.00"),
        )
        db.commit()
        pago1_id = pago1.id

    # Pago 2 sobre c2 que CONSUME el crédito 30 (efectivo 70 + crédito 30 = 100, c2 PAGADO).
    with Session(app_engine, expire_on_commit=False) as db:
        _set_org(db, org)
        pago2 = pagos_svc.registrar_pago_efectivo(
            db,
            org_id=org,
            cuota_ids=[c2],
            registrado_por=anular_fixture["usuario"],
            monto_recibido=Decimal("70.00"),
        )
        db.commit()
        assert pago2.credito_aplicado == Decimal("30.00")

    # Anular el PRIMER pago debe bloquear: su crédito (30) ya fue consumido.
    with Session(app_engine, expire_on_commit=False) as db:
        _set_org(db, org)
        with pytest.raises(pagos_svc.PagoError) as exc:
            pagos_svc.anular_pago(
                db, org_id=org, pago_id=pago1_id, anulado_por=anular_fixture["usuario"], motivo="x"
            )
        assert exc.value.code == "credito_consumido"


# =========================================================================== #
# CON BD — C-RLS: un pago de otra org no es visible → no_encontrado
# =========================================================================== #
@pytest.mark.db
def test_anular_pago_de_otra_org_invisible(
    app_engine: Engine, anular_fixture: dict, two_orgs: dict
) -> None:
    org = anular_fixture["org"]
    c1 = anular_fixture["c1"]
    org_otra = two_orgs["org_a"]

    with Session(app_engine, expire_on_commit=False) as db:
        _set_org(db, org)
        pago = pagos_svc.registrar_pago_efectivo(
            db,
            org_id=org,
            cuota_ids=[c1],
            registrado_por=anular_fixture["usuario"],
            monto_recibido=Decimal("100.00"),
        )
        db.commit()
        pago_id = pago.id

    # Desde OTRA org, el pago es invisible por RLS → no_encontrado (404, no 403).
    with Session(app_engine, expire_on_commit=False) as db:
        _set_org(db, org_otra)
        with pytest.raises(pagos_svc.PagoError) as exc:
            pagos_svc.anular_pago(
                db,
                org_id=org_otra,
                pago_id=pago_id,
                anulado_por=anular_fixture["usuario"],
                motivo="x",
            )
        assert exc.value.code == "no_encontrado"


# =========================================================================== #
# CON BD — C-Lista: GET /cobranza/pagos (helper de armado) con anulable correcto
# =========================================================================== #
@pytest.mark.db
def test_lista_pagos_anulable_y_nombre(app_engine: Engine, anular_fixture: dict) -> None:
    """El pago efectivo CONFIRMADO sale anulable=True con deportista en MAYÚSCULAS."""
    from app.models.pago import Pago
    from sqlalchemy import func, select

    org = anular_fixture["org"]
    c1 = anular_fixture["c1"]

    with Session(app_engine, expire_on_commit=False) as db:
        _set_org(db, org)
        pago = pagos_svc.registrar_pago_efectivo(
            db,
            org_id=org,
            cuota_ids=[c1],
            registrado_por=anular_fixture["usuario"],
            monto_recibido=Decimal("100.00"),
        )
        db.commit()
        pago_id = pago.id

    with Session(app_engine, expire_on_commit=False) as db:
        _set_org(db, org)
        total = db.execute(select(func.count()).select_from(Pago)).scalar_one()
        pagos = db.execute(select(Pago).order_by(Pago.created_at.desc())).scalars().all()
        item = None
        for p in pagos:
            cuotas = pagos_svc._cuotas_de_pago(db, p.id)
            deportista = pagos_svc._deportista_de_cuotas(db, cuotas)
            if p.id == pago_id:
                nombre = (
                    " ".join(
                        x
                        for x in [deportista.ap_paterno, deportista.ap_materno, deportista.nombres]
                        if x
                    ).strip()
                    if deportista
                    else None
                )
                item = (p, nombre)

    assert total >= 1
    assert item is not None
    p, nombre = item
    assert (p.metodo == "EFECTIVO" and p.estado == "CONFIRMADO") is True
    assert nombre == "JUAN PEREZ"
