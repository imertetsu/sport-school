"""Tests del epic Abonos (pagos parciales sobre Cobranza, RF-ABO-01..11).

Dos capas, igual que el resto de la suite:

- **Sin BD** (rápidos, siempre corren): el motor puro `distribuir_abono` (FIFO,
  sobrepago, sin perder centavos), validación de `PagoEfectivoIn`, el estado destino
  por cuota (RF-ABO-05) y el comprobante (puerto/adapter con columnas Aplicado/Saldo
  + pie crédito).
- **Con BD** (`@pytest.mark.db`, requieren Postgres migrado con `0009` + RLS + rol
  `latinosport_app`): FIFO 1.5 cuotas (PAGADO + PARCIAL), sobrepago → crédito, consumo
  de crédito en el siguiente pago, invariante por pago, idempotencia de re-aplicar,
  cron PARCIAL → VENCIDO, RLS de `credito`, retrocompat, QR full sin regresión, recibo.

Los `@pytest.mark.db` los corre main en la fase de cierre contra Postgres.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import date, datetime
from decimal import Decimal

import pytest
from app.adapters.comprobante.pdf import PdfComprobanteService
from app.domain.cobranza.abono_engine import distribuir_abono
from app.domain.ports.invoice import ComprobanteData, CuotaLinea
from app.schemas.cobranza import PagoEfectivoIn
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session


# =========================================================================== #
# SIN BD — motor puro (RF-ABO-04): FIFO, sobrepago, sin perder centavos
# =========================================================================== #
def test_distribuir_abono_cubre_una_y_media_cuota() -> None:
    """Criterio 1: monto que cubre 1.5 cuotas (mismo saldo) → 1ª completa, 2ª mitad."""
    res = distribuir_abono(Decimal("150.00"), [Decimal("100.00"), Decimal("100.00")])
    assert res.aplicaciones == [Decimal("100.00"), Decimal("50.00")]
    assert res.remanente == Decimal("0.00")


def test_distribuir_abono_fifo_respeta_orden() -> None:
    """El primer saldo se llena antes que el segundo (FIFO)."""
    res = distribuir_abono(Decimal("70.00"), [Decimal("100.00"), Decimal("100.00")])
    assert res.aplicaciones == [Decimal("70.00"), Decimal("0.00")]
    assert res.remanente == Decimal("0.00")


def test_distribuir_abono_sobrepago_genera_remanente() -> None:
    """Criterio 3: sobrepago tras cubrir todos los saldos → remanente (→ crédito)."""
    res = distribuir_abono(Decimal("250.00"), [Decimal("100.00"), Decimal("100.00")])
    assert res.aplicaciones == [Decimal("100.00"), Decimal("100.00")]
    assert res.remanente == Decimal("50.00")


def test_distribuir_abono_total_exacto_sin_remanente() -> None:
    """QR full: monto == Σ saldos → todo aplicado, sin remanente."""
    res = distribuir_abono(Decimal("200.00"), [Decimal("100.00"), Decimal("100.00")])
    assert res.aplicaciones == [Decimal("100.00"), Decimal("100.00")]
    assert res.remanente == Decimal("0.00")


def test_distribuir_abono_no_pierde_centavos() -> None:
    """La suma de aplicaciones + remanente == monto disponible (acotado por Σ saldos)."""
    saldos = [Decimal("33.33"), Decimal("33.33"), Decimal("33.34")]
    disponible = Decimal("80.01")
    res = distribuir_abono(disponible, saldos)
    assert sum(res.aplicaciones, Decimal("0")) + res.remanente == disponible
    # FIFO: 33.33 + 33.33 + 13.35 = 80.01; sin remanente (no se cubrió la 3ª).
    assert res.aplicaciones == [Decimal("33.33"), Decimal("33.33"), Decimal("13.35")]
    assert res.remanente == Decimal("0.00")


def test_distribuir_abono_cero_no_aplica() -> None:
    res = distribuir_abono(Decimal("0"), [Decimal("100.00")])
    assert res.aplicaciones == [Decimal("0")]
    assert res.remanente == Decimal("0")


def test_distribuir_abono_negativo_se_trata_como_cero() -> None:
    res = distribuir_abono(Decimal("-10"), [Decimal("100.00")])
    assert res.aplicaciones == [Decimal("0")]
    assert res.remanente == Decimal("0")


# =========================================================================== #
# SIN BD — schema PagoEfectivoIn (monto_recibido opcional, > 0)
# =========================================================================== #
def test_pago_efectivo_in_sin_monto_recibido() -> None:
    obj = PagoEfectivoIn(cuota_ids=[uuid.uuid4()])
    assert obj.monto_recibido is None


def test_pago_efectivo_in_monto_recibido_valido() -> None:
    obj = PagoEfectivoIn(cuota_ids=[uuid.uuid4()], monto_recibido=Decimal("100.00"))
    assert obj.monto_recibido == Decimal("100.00")


def test_pago_efectivo_in_monto_recibido_cero_falla() -> None:
    """`monto_recibido == 0` -> ValidationError (=> 422 en la API)."""
    with pytest.raises(ValidationError):
        PagoEfectivoIn(cuota_ids=[uuid.uuid4()], monto_recibido=Decimal("0"))


def test_pago_efectivo_in_monto_recibido_negativo_falla() -> None:
    with pytest.raises(ValidationError):
        PagoEfectivoIn(cuota_ids=[uuid.uuid4()], monto_recibido=Decimal("-5.00"))


# =========================================================================== #
# SIN BD — recibo (puerto/adapter): columnas Aplicado/Saldo + pie crédito
# =========================================================================== #
def test_comprobante_pdf_parcial_con_credito_render() -> None:
    """Criterio 11: el comprobante con abono parcial + crédito renderiza (bytes PDF)."""
    data = ComprobanteData(
        numero="abc",
        org_nombre="Club Test",
        moneda="BOB",
        alumno_nombre="Juan Perez",
        metodo="EFECTIVO",
        fecha=datetime(2026, 6, 1, 10, 0),
        monto_total=Decimal("150.00"),
        cuotas=[
            CuotaLinea(
                periodo_inicio="2026-05-01",
                vence_el="2026-06-01",
                monto=Decimal("100.00"),
                monto_aplicado=Decimal("100.00"),
                saldo_restante=Decimal("0.00"),
            ),
            CuotaLinea(
                periodo_inicio="2026-06-01",
                vence_el="2026-07-01",
                monto=Decimal("100.00"),
                monto_aplicado=Decimal("50.00"),
                saldo_restante=Decimal("50.00"),
            ),
        ],
        credito_aplicado=Decimal("0.00"),
        credito_generado=Decimal("0.00"),
    )
    out = PdfComprobanteService().render_pdf(data)
    assert isinstance(out, bytes) and out[:4] == b"%PDF"


def test_comprobante_pdf_defaults_qr_igual_que_hoy() -> None:
    """Criterio 11: con QR (defaults 0, sin monto_aplicado) el comprobante renderiza."""
    data = ComprobanteData(
        numero="qr1",
        org_nombre="Club Test",
        moneda="BOB",
        alumno_nombre="Ana",
        metodo="QR",
        fecha=datetime(2026, 6, 1, 10, 0),
        monto_total=Decimal("250.00"),
        cuotas=[
            CuotaLinea(
                periodo_inicio="2026-06-01",
                vence_el="2026-07-01",
                monto=Decimal("250.00"),
            )
        ],
    )
    out = PdfComprobanteService().render_pdf(data)
    assert isinstance(out, bytes) and out[:4] == b"%PDF"


# =========================================================================== #
# CON BD — fixture de inscripción con cuotas para los flujos de abono
# =========================================================================== #
@pytest.fixture()
def abono_fixture(owner_engine: Engine) -> Iterator[dict]:
    """Org + sucursal + alumno + inscripción + 2 cuotas PENDIENTE (mismo saldo).

    Cuotas FIFO: c1 vence antes que c2, ambas monto 100, monto_pagado 0.
    Limpia al final (orden FK-safe, incluye `credito`). Skip si no hay BD.
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
                "VALUES (:id,'Org Abonos (test)','BO','BOB','ANIVERSARIO',true,now(),now())"
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
                "VALUES (:id,:org,:email,'x','ADMIN','Admin Abono',true,now(),now())"
            ),
            {"id": str(usuario), "org": str(org), "email": f"ab_{uuid.uuid4().hex}@test.bo"},
        )
        conn.execute(
            text(
                "INSERT INTO alumno (id, org_id, sucursal_id, nombres, created_at, updated_at) "
                "VALUES (:id,:org,:suc,'Alumno Abono',now(),now())"
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
        # 2 cuotas, c1 vence antes que c2 (FIFO). Ambas a futuro (no vencidas).
        for cid, pi, pf, v in (
            (c1, date(2026, 5, 10), date(2026, 6, 10), date(2026, 6, 10)),
            (c2, date(2026, 6, 10), date(2026, 7, 10), date(2026, 7, 10)),
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
        conn.execute(text("DELETE FROM alumno WHERE org_id = :o"), {"o": str(org)})
        conn.execute(text("DELETE FROM sucursal WHERE org_id = :o"), {"o": str(org)})
        conn.execute(text("DELETE FROM organizacion WHERE id = :o"), {"o": str(org)})


def _set_org(conn, org: uuid.UUID) -> None:
    conn.execute(text("SELECT set_config('app.current_org', :o, true)"), {"o": str(org)})


# =========================================================================== #
# CON BD — criterio 1: FIFO 1.5 cuotas (PAGADO + PARCIAL)
# =========================================================================== #
@pytest.mark.db
def test_pago_parcial_fifo_pagado_y_parcial(app_engine: Engine, abono_fixture: dict) -> None:
    from app.services import pagos as pagos_svc

    org = abono_fixture["org"]
    c1, c2 = abono_fixture["c1"], abono_fixture["c2"]

    with Session(app_engine, expire_on_commit=False) as db:
        _set_org(db, org)
        pago = pagos_svc.registrar_pago_efectivo(
            db,
            org_id=org,
            cuota_ids=[c1, c2],
            registrado_por=abono_fixture["usuario"],
            monto_recibido=Decimal("150.00"),
        )
        db.commit()
        pago_id = pago.id

    with app_engine.begin() as conn:
        _set_org(conn, org)
        c1_row = conn.execute(
            text("SELECT estado, monto_pagado FROM cuota WHERE id=:id"), {"id": str(c1)}
        ).one()
        c2_row = conn.execute(
            text("SELECT estado, monto_pagado FROM cuota WHERE id=:id"), {"id": str(c2)}
        ).one()
        monto_pago = conn.execute(
            text("SELECT monto FROM pago WHERE id=:id"), {"id": str(pago_id)}
        ).scalar_one()

    assert c1_row.estado == "PAGADO"
    assert c1_row.monto_pagado == Decimal("100.00")
    assert c2_row.estado == "PARCIAL"
    assert c2_row.monto_pagado == Decimal("50.00")
    assert monto_pago == Decimal("150.00")


# =========================================================================== #
# CON BD — criterio 3: sobrepago → crédito
# =========================================================================== #
@pytest.mark.db
def test_sobrepago_genera_credito(app_engine: Engine, abono_fixture: dict) -> None:
    from app.services import pagos as pagos_svc

    org = abono_fixture["org"]
    insc = abono_fixture["inscripcion"]
    c1, c2 = abono_fixture["c1"], abono_fixture["c2"]

    with Session(app_engine, expire_on_commit=False) as db:
        _set_org(db, org)
        pago = pagos_svc.registrar_pago_efectivo(
            db,
            org_id=org,
            cuota_ids=[c1, c2],
            registrado_por=abono_fixture["usuario"],
            monto_recibido=Decimal("250.00"),  # Σ saldos = 200 → 50 de exceso
        )
        db.commit()
        # credito_aplicado refleja SOLO lo consumido (no había crédito previo) = 0.
        assert pago.credito_aplicado == Decimal("0.00")

    with app_engine.begin() as conn:
        _set_org(conn, org)
        saldo_credito = conn.execute(
            text("SELECT saldo FROM credito WHERE inscripcion_id=:i"), {"i": str(insc)}
        ).scalar_one()
        estados = (
            conn.execute(
                text("SELECT estado FROM cuota WHERE inscripcion_id=:i ORDER BY vence_el"),
                {"i": str(insc)},
            )
            .scalars()
            .all()
        )

    assert saldo_credito == Decimal("50.00")
    assert estados == ["PAGADO", "PAGADO"]


# =========================================================================== #
# CON BD — criterio 4: consumo de crédito en el siguiente pago
# =========================================================================== #
@pytest.mark.db
def test_consumo_credito_en_siguiente_pago(app_engine: Engine, abono_fixture: dict) -> None:
    from app.services import pagos as pagos_svc

    org = abono_fixture["org"]
    insc = abono_fixture["inscripcion"]
    c1, c2 = abono_fixture["c1"], abono_fixture["c2"]

    # 1) Pago sobre c1 con sobrepago de 30 → genera crédito 30, c1 PAGADO.
    with Session(app_engine, expire_on_commit=False) as db:
        _set_org(db, org)
        pagos_svc.registrar_pago_efectivo(
            db,
            org_id=org,
            cuota_ids=[c1],
            registrado_por=abono_fixture["usuario"],
            monto_recibido=Decimal("130.00"),
        )
        db.commit()

    with app_engine.begin() as conn:
        _set_org(conn, org)
        saldo1 = conn.execute(
            text("SELECT saldo FROM credito WHERE inscripcion_id=:i"), {"i": str(insc)}
        ).scalar_one()
    assert saldo1 == Decimal("30.00")

    # 2) Pago sobre c2 (saldo 100) con efectivo 80 → consume crédito 30 + efectivo 70
    #    (en realidad: disponible 110, c2 saldo 100 → aplica 100, remanente 10).
    with Session(app_engine, expire_on_commit=False) as db:
        _set_org(db, org)
        pago2 = pagos_svc.registrar_pago_efectivo(
            db,
            org_id=org,
            cuota_ids=[c2],
            registrado_por=abono_fixture["usuario"],
            monto_recibido=Decimal("80.00"),
        )
        db.commit()
        # credito_aplicado = min(credito_previo=30, total_aplicado=100) = 30.
        assert pago2.credito_aplicado == Decimal("30.00")
        # pago.monto = total_aplicado - credito_aplicado = 100 - 30 = 70.
        assert pago2.monto == Decimal("70.00")

    with app_engine.begin() as conn:
        _set_org(conn, org)
        saldo2 = conn.execute(
            text("SELECT saldo FROM credito WHERE inscripcion_id=:i"), {"i": str(insc)}
        ).scalar_one()
        c2_estado = conn.execute(
            text("SELECT estado, monto_pagado FROM cuota WHERE id=:id"), {"id": str(c2)}
        ).one()
    # remanente = disponible(110) - aplicado(100) = 10.
    assert saldo2 == Decimal("10.00")
    assert c2_estado.estado == "PAGADO"
    assert c2_estado.monto_pagado == Decimal("100.00")


# =========================================================================== #
# CON BD — criterio 5: invariante por pago (Σ aplicado = monto + credito_aplicado)
# =========================================================================== #
@pytest.mark.db
def test_invariante_por_pago(app_engine: Engine, abono_fixture: dict) -> None:
    from app.services import pagos as pagos_svc

    org = abono_fixture["org"]
    c1, c2 = abono_fixture["c1"], abono_fixture["c2"]

    with Session(app_engine, expire_on_commit=False) as db:
        _set_org(db, org)
        pago = pagos_svc.registrar_pago_efectivo(
            db,
            org_id=org,
            cuota_ids=[c1, c2],
            registrado_por=abono_fixture["usuario"],
            monto_recibido=Decimal("250.00"),
        )
        db.commit()
        pago_id = pago.id

    with app_engine.begin() as conn:
        _set_org(conn, org)
        suma_aplicado = conn.execute(
            text("SELECT COALESCE(SUM(monto_aplicado),0) FROM pago_cuota WHERE pago_id=:p"),
            {"p": str(pago_id)},
        ).scalar_one()
        pago_row = conn.execute(
            text("SELECT monto, credito_aplicado FROM pago WHERE id=:id"), {"id": str(pago_id)}
        ).one()

    assert suma_aplicado == pago_row.monto + pago_row.credito_aplicado


# =========================================================================== #
# CON BD — criterio 7: idempotencia de _aplicar_pago_a_cuotas (re-aplicar)
# =========================================================================== #
@pytest.mark.db
def test_reaplicar_pago_es_idempotente(app_engine: Engine, abono_fixture: dict) -> None:
    """Re-aplicar el mismo pago a la misma cuota no altera monto_pagado ni estado."""
    from app.models.cuota import Cuota
    from app.models.pago import Pago
    from app.services import pagos as pagos_svc

    org = abono_fixture["org"]
    c1 = abono_fixture["c1"]

    with Session(app_engine, expire_on_commit=False) as db:
        _set_org(db, org)
        pago = pagos_svc.registrar_pago_efectivo(
            db,
            org_id=org,
            cuota_ids=[c1],
            registrado_por=abono_fixture["usuario"],
            monto_recibido=Decimal("40.00"),  # parcial
        )
        db.commit()
        pago_id = pago.id

    # Re-aplicar el MISMO pago a la MISMA cuota (re-INSERT bloqueado por UNIQUE).
    with Session(app_engine, expire_on_commit=False) as db:
        _set_org(db, org)
        pago_obj = db.get(Pago, pago_id)
        cuota = db.get(Cuota, c1)
        assert pago_obj is not None and cuota is not None
        pagos_svc._aplicar_pago_a_cuotas(
            db,
            pago=pago_obj,
            cuotas=[cuota],
            org_id=org,
            aplicaciones={c1: Decimal("40.00")},
        )
        db.commit()

    with app_engine.begin() as conn:
        _set_org(conn, org)
        row = conn.execute(
            text("SELECT estado, monto_pagado FROM cuota WHERE id=:id"), {"id": str(c1)}
        ).one()
        puentes = conn.execute(
            text("SELECT count(*) FROM pago_cuota WHERE pago_id=:p AND cuota_id=:c"),
            {"p": str(pago_id), "c": str(c1)},
        ).scalar_one()

    assert row.monto_pagado == Decimal("40.00"), "re-aplicar no debe duplicar el abono"
    assert row.estado == "PARCIAL"
    assert puentes == 1


# =========================================================================== #
# CON BD — criterio 2: cron PARCIAL → VENCIDO (precedencia de vencido)
# =========================================================================== #
@pytest.mark.db
def test_cron_marca_parcial_vencido(app_engine: Engine, abono_fixture: dict) -> None:
    from app.workers.tasks import _procesar_org

    org = abono_fixture["org"]
    c1 = abono_fixture["c1"]

    # Dejar c1 en PARCIAL con vence_el en el pasado (saldo > 0).
    with app_engine.begin() as conn:
        _set_org(conn, org)
        conn.execute(
            text("UPDATE cuota SET estado='PARCIAL', monto_pagado=40, vence_el=:v WHERE id=:id"),
            {"id": str(c1), "v": date(2026, 1, 1)},
        )

    hoy = date(2026, 3, 1)
    with Session(app_engine, expire_on_commit=False) as db:
        _set_org(db, org)
        _procesar_org(db, org_id=org, hoy=hoy)
        db.commit()

    with app_engine.begin() as conn:
        _set_org(conn, org)
        estado1 = conn.execute(
            text("SELECT estado FROM cuota WHERE id=:id"), {"id": str(c1)}
        ).scalar_one()
    assert estado1 == "VENCIDO", "PARCIAL con vence_el < hoy debe pasar a VENCIDO"

    # Re-correr el cron no cambia nada (idempotente).
    with Session(app_engine, expire_on_commit=False) as db:
        _set_org(db, org)
        _procesar_org(db, org_id=org, hoy=hoy)
        db.commit()
    with app_engine.begin() as conn:
        _set_org(conn, org)
        estado2 = conn.execute(
            text("SELECT estado FROM cuota WHERE id=:id"), {"id": str(c1)}
        ).scalar_one()
    assert estado2 == "VENCIDO"


# =========================================================================== #
# CON BD — criterio 8: RLS de `credito` aislado (patrón NULLIF / fail-closed)
# =========================================================================== #
@pytest.fixture()
def credito_dos_orgs(owner_engine: Engine) -> Iterator[dict]:
    """2 orgs, cada una con inscripción + 1 fila de crédito. Limpia al final."""
    org_a, org_b = uuid.uuid4(), uuid.uuid4()
    suc_a, suc_b = uuid.uuid4(), uuid.uuid4()
    al_a, al_b = uuid.uuid4(), uuid.uuid4()
    insc_a, insc_b = uuid.uuid4(), uuid.uuid4()

    with owner_engine.begin() as conn:
        for org_id in (org_a, org_b):
            conn.execute(
                text(
                    "INSERT INTO organizacion (id, nombre, pais, moneda, modo_cobro_default, "
                    "prorratea_primer_periodo, created_at, updated_at) "
                    "VALUES (:id,'Org Cred (test)','BO','BOB','ANIVERSARIO',true,now(),now())"
                ),
                {"id": str(org_id)},
            )
        for org_id, suc_id, al_id, insc_id in (
            (org_a, suc_a, al_a, insc_a),
            (org_b, suc_b, al_b, insc_b),
        ):
            conn.execute(
                text(
                    "INSERT INTO sucursal (id, org_id, nombre, created_at, updated_at) "
                    "VALUES (:id,:org,'Suc',now(),now())"
                ),
                {"id": str(suc_id), "org": str(org_id)},
            )
            conn.execute(
                text(
                    "INSERT INTO alumno (id, org_id, sucursal_id, nombres, created_at, "
                    "updated_at) VALUES (:id,:org,:suc,'Al',now(),now())"
                ),
                {"id": str(al_id), "org": str(org_id), "suc": str(suc_id)},
            )
            conn.execute(
                text(
                    "INSERT INTO inscripcion (id, org_id, alumno_id, fecha_inscripcion, "
                    "monto_mensual, estado, created_at, updated_at) "
                    "VALUES (:id,:org,:al,:f,100,'ACTIVA',now(),now())"
                ),
                {"id": str(insc_id), "org": str(org_id), "al": str(al_id), "f": date(2026, 1, 1)},
            )
            conn.execute(
                text(
                    "INSERT INTO credito (id, org_id, inscripcion_id, saldo, created_at, "
                    "updated_at) VALUES (:id,:org,:insc,75,now(),now())"
                ),
                {"id": str(uuid.uuid4()), "org": str(org_id), "insc": str(insc_id)},
            )

    yield {"org_a": org_a, "org_b": org_b}

    with owner_engine.begin() as conn:
        for org_id in (org_a, org_b):
            conn.execute(text("DELETE FROM credito WHERE org_id=:o"), {"o": str(org_id)})
            conn.execute(text("DELETE FROM inscripcion WHERE org_id=:o"), {"o": str(org_id)})
            conn.execute(text("DELETE FROM alumno WHERE org_id=:o"), {"o": str(org_id)})
            conn.execute(text("DELETE FROM sucursal WHERE org_id=:o"), {"o": str(org_id)})
            conn.execute(text("DELETE FROM organizacion WHERE id=:o"), {"o": str(org_id)})


@pytest.mark.db
def test_credito_rls_fail_closed_sin_contexto(app_engine: Engine, credito_dos_orgs: dict) -> None:
    """Sin `app.current_org` (NULLIF → NULL) → 0 filas de credito (fail-closed)."""
    with app_engine.connect() as conn:
        count = conn.execute(text("SELECT count(*) FROM credito")).scalar_one()
    assert count == 0


@pytest.mark.db
def test_credito_rls_org_a_no_ve_org_b(app_engine: Engine, credito_dos_orgs: dict) -> None:
    """Con org A fijada se ve el crédito de A y NINGUNO de B."""
    org_a = str(credito_dos_orgs["org_a"])
    org_b = str(credito_dos_orgs["org_b"])
    with app_engine.begin() as conn:
        conn.execute(text("SELECT set_config('app.current_org', :o, true)"), {"o": org_a})
        orgs = {str(r) for r in conn.execute(text("SELECT org_id FROM credito")).scalars().all()}
    assert org_a in orgs
    assert org_b not in orgs


# =========================================================================== #
# CON BD — criterio 9: retrocompat (cuota antigua PAGADO con monto_pagado=monto)
# =========================================================================== #
@pytest.mark.db
def test_retrocompat_no_rompe_pago_de_cuota_pagada(app_engine: Engine, abono_fixture: dict) -> None:
    """Una cuota ya PAGADO con monto_pagado=monto (saldo 0) no recibe doble abono."""
    from app.services import pagos as pagos_svc

    org = abono_fixture["org"]
    c1 = abono_fixture["c1"]

    with app_engine.begin() as conn:
        _set_org(conn, org)
        conn.execute(
            text("UPDATE cuota SET estado='PAGADO', monto_pagado=monto WHERE id=:id"),
            {"id": str(c1)},
        )

    with Session(app_engine, expire_on_commit=False) as db:
        _set_org(db, org)
        pago = pagos_svc.registrar_pago_efectivo(
            db,
            org_id=org,
            cuota_ids=[c1],
            registrado_por=abono_fixture["usuario"],
            monto_recibido=Decimal("100.00"),
        )
        db.commit()
        pago_id = pago.id

    with app_engine.begin() as conn:
        _set_org(conn, org)
        row = conn.execute(
            text("SELECT estado, monto_pagado FROM cuota WHERE id=:id"), {"id": str(c1)}
        ).one()
        # No había saldo: el efectivo recibido (100) queda como crédito.
        credito = conn.execute(
            text("SELECT COALESCE(SUM(saldo),0) FROM credito WHERE inscripcion_id=:i"),
            {"i": str(abono_fixture["inscripcion"])},
        ).scalar_one()
        monto_pago = conn.execute(
            text("SELECT monto FROM pago WHERE id=:id"), {"id": str(pago_id)}
        ).scalar_one()

    assert row.estado == "PAGADO"
    assert row.monto_pagado == Decimal("100.00")  # sin doble abono
    assert credito == Decimal("100.00")
    assert monto_pago == Decimal("0.00")  # nada se aplicó a cuotas → todo a crédito


# =========================================================================== #
# CON BD — criterio 10: QR full sin regresión (todo PAGADO, sin crédito)
# =========================================================================== #
@pytest.mark.db
def test_qr_full_sin_regresion(app_engine: Engine, abono_fixture: dict) -> None:
    """QR por el total: crear + confirmar → todas PAGADO, sin crédito, saldo 0."""
    from app.services import pagos as pagos_svc

    org = abono_fixture["org"]
    insc = abono_fixture["inscripcion"]
    c1, c2 = abono_fixture["c1"], abono_fixture["c2"]
    qr_ref = f"qr_ab_{uuid.uuid4().hex}"

    with Session(app_engine, expire_on_commit=False) as db:
        _set_org(db, org)
        pago = pagos_svc.crear_pago_qr(db, org_id=org, cuota_ids=[c1, c2], qr_ref=qr_ref)
        db.commit()
        pago_id = pago.id
        assert pago.monto == Decimal("200.00")

    # Confirmar vía webhook por el total.
    with Session(app_engine, expire_on_commit=False) as db:
        res = pagos_svc.procesar_webhook(
            db, transaccion_id=f"tx_{uuid.uuid4().hex}", referencia=qr_ref, monto=Decimal("200.00")
        )
        db.commit()
    assert res == "confirmado"

    with app_engine.begin() as conn:
        _set_org(conn, org)
        estados = conn.execute(
            text(
                "SELECT estado, monto_pagado FROM cuota WHERE inscripcion_id=:i ORDER BY vence_el"
            ),
            {"i": str(insc)},
        ).all()
        credito = conn.execute(
            text("SELECT COALESCE(SUM(saldo),0) FROM credito WHERE inscripcion_id=:i"),
            {"i": str(insc)},
        ).scalar_one()
        pago_row = conn.execute(
            text("SELECT estado, credito_aplicado FROM pago WHERE id=:id"), {"id": str(pago_id)}
        ).one()

    assert [e.estado for e in estados] == ["PAGADO", "PAGADO"]
    assert all(e.monto_pagado == Decimal("100.00") for e in estados)
    assert credito == Decimal("0.00")
    assert pago_row.estado == "CONFIRMADO"
    assert pago_row.credito_aplicado == Decimal("0.00")


# =========================================================================== #
# CON BD — criterio 11: recibo de un pago parcial real (Aplicado/Saldo + crédito)
# =========================================================================== #
@pytest.mark.db
def test_recibo_pago_parcial(app_engine: Engine, abono_fixture: dict) -> None:
    from app.models.organizacion import Organizacion
    from app.models.pago import Pago
    from app.services import pagos as pagos_svc

    org = abono_fixture["org"]
    c1, c2 = abono_fixture["c1"], abono_fixture["c2"]

    with Session(app_engine, expire_on_commit=False) as db:
        _set_org(db, org)
        pago = pagos_svc.registrar_pago_efectivo(
            db,
            org_id=org,
            cuota_ids=[c1, c2],
            registrado_por=abono_fixture["usuario"],
            monto_recibido=Decimal("150.00"),
        )
        db.commit()
        pago_id = pago.id

    with Session(app_engine, expire_on_commit=False) as db:
        _set_org(db, org)
        pago_obj = db.get(Pago, pago_id)
        org_obj = db.get(Organizacion, org)
        assert pago_obj is not None and org_obj is not None
        data = pagos_svc.construir_comprobante_data(db, pago=pago_obj, org=org_obj)

    # 1ª cuota saldada, 2ª parcial.
    saldos = sorted(linea.saldo_restante for linea in data.cuotas)
    assert saldos == [Decimal("0.00"), Decimal("50.00")]
    aplicados = sorted(
        linea.monto_aplicado for linea in data.cuotas if linea.monto_aplicado is not None
    )
    assert aplicados == [Decimal("50.00"), Decimal("100.00")]

    out = PdfComprobanteService().render_pdf(data)
    assert out[:4] == b"%PDF"
