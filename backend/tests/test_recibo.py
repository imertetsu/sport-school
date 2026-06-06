"""Tests del epic Recibo (comprobante no-fiscal con cabecera + correlativo por org).

Cubre:
- PDF/`ComprobanteData`: emisor de marca, N° de recibo y leyenda legal (sin BD).
- Numeración correlativa por org (`REC-000001`, `REC-000002`), independencia entre
  orgs, idempotencia (re-confirmar no reasigna ni incrementa) y RLS de
  `recibo_contador` — todo `@pytest.mark.db` (requiere Postgres migrado con 0010).

Patrón de las pruebas BD: `owner_engine` siembra (saltando RLS) y una `Session`
sobre `app_engine` (rol `latinosport_app`, NOBYPASSRLS) ejercita el servicio bajo
RLS real, fijando `app.current_org` como en producción.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from app.adapters.comprobante.pdf import PdfComprobanteService
from app.core.config import settings
from app.domain.ports.invoice import ComprobanteData
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session


# --------------------------------------------------------------------------- #
# Sin BD: ComprobanteData + PDF (emisor, número, leyenda)
# --------------------------------------------------------------------------- #
def _pdf_text(pdf_bytes: bytes) -> str:
    """Extrae el texto del PDF descomprimiendo los streams FlateDecode.

    fpdf2 comprime los content streams (zlib), así que el texto no aparece en los
    bytes crudos; aquí descomprimimos cada stream para poder asertar su contenido.
    """
    import re
    import zlib

    partes: list[str] = []
    for match in re.finditer(rb"stream\r?\n(.*?)\r?\nendstream", pdf_bytes, re.DOTALL):
        raw = match.group(1)
        try:
            partes.append(zlib.decompress(raw).decode("latin-1", "ignore"))
        except zlib.error:
            partes.append(raw.decode("latin-1", "ignore"))
    return "\n".join(partes)


def _comprobante_data(numero_recibo: str = "REC-000007") -> ComprobanteData:
    return ComprobanteData(
        numero=str(uuid.uuid4()),
        org_nombre="Escuela de Prueba",
        moneda="BOB",
        alumno_nombre="Juan Perez",
        metodo="EFECTIVO",
        fecha=datetime(2026, 6, 6, 10, 30, tzinfo=UTC),
        monto_total=Decimal("250.00"),
        numero_recibo=numero_recibo,
        emisor=settings.recibo_emisor,
    )


def test_comprobante_data_lleva_emisor_y_numero_recibo() -> None:
    data = _comprobante_data("REC-000042")
    assert data.emisor == "SnapCoding - LatinoSport"
    assert data.numero_recibo == "REC-000042"


def test_comprobante_data_emisor_default_es_marca() -> None:
    """Aunque el constructor llena `emisor`, el default del dominio es la marca."""
    data = ComprobanteData(
        numero="x",
        org_nombre="Org",
        moneda="BOB",
        alumno_nombre="A",
        metodo="QR",
        fecha=datetime(2026, 1, 1, tzinfo=UTC),
        monto_total=Decimal("0"),
    )
    assert data.emisor == "SnapCoding - LatinoSport"
    assert data.numero_recibo == "—"


def test_pdf_incluye_emisor_numero_y_leyenda() -> None:
    pdf_bytes = PdfComprobanteService().render_pdf(_comprobante_data("REC-000007"))
    assert pdf_bytes[:4] == b"%PDF"
    texto = _pdf_text(pdf_bytes)
    # Cabecera de marca + N° de recibo + leyenda legal en el contenido del PDF.
    assert "SnapCoding - LatinoSport" in texto
    assert "REC-000007" in texto
    # _ascii() degrada la "á" de "válido" a "?"; aceptamos esa forma latin-1.
    assert "Documento no v" in texto and "lido como factura" in texto


def test_pdf_conserva_aplicado_saldo_y_credito_de_abonos() -> None:
    from app.domain.ports.invoice import CuotaLinea

    data = ComprobanteData(
        numero=str(uuid.uuid4()),
        org_nombre="Escuela",
        moneda="BOB",
        alumno_nombre="Ana",
        metodo="EFECTIVO",
        fecha=datetime(2026, 6, 6, tzinfo=UTC),
        monto_total=Decimal("100.00"),
        cuotas=[
            CuotaLinea(
                periodo_inicio="2026-06-01",
                vence_el="2026-06-30",
                monto=Decimal("250.00"),
                monto_aplicado=Decimal("100.00"),
                saldo_restante=Decimal("150.00"),
            )
        ],
        credito_aplicado=Decimal("0"),
        credito_generado=Decimal("20.00"),
        numero_recibo="REC-000003",
    )
    pdf_bytes = PdfComprobanteService().render_pdf(data)
    texto = _pdf_text(pdf_bytes)
    # Columnas Aplicado/Saldo y pie de crédito de Abonos siguen presentes.
    assert "Aplicado" in texto and "Saldo" in texto
    assert "Saldo a favor generado" in texto


# --------------------------------------------------------------------------- #
# Con BD: correlativo por org, independencia, idempotencia, RLS
# --------------------------------------------------------------------------- #
def _sembrar_org_con_cuota(conn, *, org: uuid.UUID, monto: Decimal) -> uuid.UUID:
    """Siembra org + sucursal + alumno + inscripción + 1 cuota PENDIENTE. -> cuota_id."""
    suc = uuid.uuid4()
    al = uuid.uuid4()
    insc = uuid.uuid4()
    cuota = uuid.uuid4()
    conn.execute(
        text(
            "INSERT INTO organizacion (id, nombre, pais, moneda, modo_cobro_default, "
            "prorratea_primer_periodo, created_at, updated_at) "
            "VALUES (:id,'Org Recibo (test)','BO','BOB','ANIVERSARIO',true,now(),now()) "
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
            "INSERT INTO alumno (id, org_id, sucursal_id, nombres, created_at, updated_at) "
            "VALUES (:id,:org,:suc,'Alumno Recibo',now(),now())"
        ),
        {"id": str(al), "org": str(org), "suc": str(suc)},
    )
    conn.execute(
        text(
            "INSERT INTO inscripcion (id, org_id, alumno_id, fecha_inscripcion, "
            "monto_mensual, estado, created_at, updated_at) "
            "VALUES (:id,:org,:al,:f,:m,'ACTIVA',now(),now())"
        ),
        {"id": str(insc), "org": str(org), "al": str(al), "f": date(2025, 1, 10), "m": monto},
    )
    conn.execute(
        text(
            "INSERT INTO cuota (id, org_id, inscripcion_id, periodo_inicio, periodo_fin, "
            "vence_el, monto, estado, es_prorrateo, generada_en) "
            "VALUES (:id,:org,:insc,:pi,:pf,:v,:m,'PENDIENTE',false,now())"
        ),
        {
            "id": str(cuota),
            "org": str(org),
            "insc": str(insc),
            "pi": date(2025, 1, 10),
            "pf": date(2025, 2, 10),
            "v": date(2025, 2, 10),
            "m": monto,
        },
    )
    return cuota


@pytest.fixture()
def recibo_fixture(owner_engine: Engine) -> Iterator[dict]:
    """Dos orgs, cada una con una cuota PENDIENTE confirmable por efectivo.

    Devuelve ids; limpia al final (incluye `recibo_contador`).
    """
    org_a = uuid.uuid4()
    org_b = uuid.uuid4()
    monto = Decimal("250.00")
    user_a = uuid.uuid4()
    user_b = uuid.uuid4()

    with owner_engine.begin() as conn:
        cuota_a = _sembrar_org_con_cuota(conn, org=org_a, monto=monto)
        cuota_b = _sembrar_org_con_cuota(conn, org=org_b, monto=monto)
        # Una segunda cuota en org A para el segundo recibo correlativo.
        cuota_a2 = _sembrar_org_con_cuota(conn, org=org_a, monto=monto)
        for org_id, uid in ((org_a, user_a), (org_b, user_b)):
            conn.execute(
                text(
                    "INSERT INTO usuario (id, org_id, email, password_hash, role, nombre, "
                    "activo, created_at, updated_at) "
                    "VALUES (:id,:org,:email,'x','ADMIN','Admin Test',true,now(),now())"
                ),
                {"id": str(uid), "org": str(org_id), "email": f"admin_{uid.hex}@t.test"},
            )

    yield {
        "org_a": org_a,
        "org_b": org_b,
        "cuota_a": cuota_a,
        "cuota_a2": cuota_a2,
        "cuota_b": cuota_b,
        "user_a": user_a,
        "user_b": user_b,
        "monto": monto,
    }

    with owner_engine.begin() as conn:
        for org_id in (org_a, org_b):
            conn.execute(text("DELETE FROM pago_cuota WHERE org_id = :o"), {"o": str(org_id)})
            conn.execute(text("DELETE FROM pago WHERE org_id = :o"), {"o": str(org_id)})
            conn.execute(text("DELETE FROM credito WHERE org_id = :o"), {"o": str(org_id)})
            conn.execute(text("DELETE FROM cuota WHERE org_id = :o"), {"o": str(org_id)})
            conn.execute(text("DELETE FROM inscripcion WHERE org_id = :o"), {"o": str(org_id)})
            conn.execute(text("DELETE FROM alumno WHERE org_id = :o"), {"o": str(org_id)})
            conn.execute(text("DELETE FROM usuario WHERE org_id = :o"), {"o": str(org_id)})
            conn.execute(text("DELETE FROM sucursal WHERE org_id = :o"), {"o": str(org_id)})
            conn.execute(text("DELETE FROM recibo_contador WHERE org_id = :o"), {"o": str(org_id)})
            conn.execute(text("DELETE FROM organizacion WHERE id = :o"), {"o": str(org_id)})


def _confirmar_efectivo(app_engine: Engine, *, org: uuid.UUID, cuota: uuid.UUID, user: uuid.UUID):
    from app.services import pagos as pagos_svc

    with Session(app_engine) as db:
        db.execute(text("SELECT set_config('app.current_org', :o, true)"), {"o": str(org)})
        pago = pagos_svc.registrar_pago_efectivo(
            db, org_id=org, cuota_ids=[cuota], registrado_por=user
        )
        db.flush()
        numero = pago.numero_recibo
        db.commit()
    return numero


@pytest.mark.db
def test_correlativo_por_org_y_independencia(app_engine: Engine, recibo_fixture: dict) -> None:
    org_a = recibo_fixture["org_a"]
    org_b = recibo_fixture["org_b"]

    n_a1 = _confirmar_efectivo(
        app_engine, org=org_a, cuota=recibo_fixture["cuota_a"], user=recibo_fixture["user_a"]
    )
    n_a2 = _confirmar_efectivo(
        app_engine, org=org_a, cuota=recibo_fixture["cuota_a2"], user=recibo_fixture["user_a"]
    )
    n_b1 = _confirmar_efectivo(
        app_engine, org=org_b, cuota=recibo_fixture["cuota_b"], user=recibo_fixture["user_b"]
    )

    # Correlativo por org A.
    assert n_a1 == "REC-000001"
    assert n_a2 == "REC-000002"
    # Org B arranca su propia serie en 000001 (independencia multi-tenant).
    assert n_b1 == "REC-000001"


@pytest.mark.db
def test_idempotencia_no_reasigna_ni_incrementa(app_engine: Engine, recibo_fixture: dict) -> None:
    """Re-confirmar el mismo pago no cambia su número ni avanza el contador."""
    from app.services import pagos as pagos_svc

    org = recibo_fixture["org_a"]
    cuota = recibo_fixture["cuota_a"]
    user = recibo_fixture["user_a"]

    with Session(app_engine) as db:
        db.execute(text("SELECT set_config('app.current_org', :o, true)"), {"o": str(org)})
        pago = pagos_svc.registrar_pago_efectivo(
            db, org_id=org, cuota_ids=[cuota], registrado_por=user
        )
        db.flush()
        numero1 = pago.numero_recibo
        # Re-asignar explícitamente: idempotente por la guarda `numero_recibo is not None`.
        pagos_svc._asignar_numero_recibo(db, pago)
        numero2 = pago.numero_recibo
        db.commit()

    assert numero1 == "REC-000001"
    assert numero2 == numero1, "Re-asignar no debe cambiar el número"

    with app_engine.begin() as conn:
        conn.execute(text("SELECT set_config('app.current_org', :o, true)"), {"o": str(org)})
        ultimo = conn.execute(
            text("SELECT ultimo_numero FROM recibo_contador WHERE org_id = :o"),
            {"o": str(org)},
        ).scalar_one()
    assert ultimo == 1, "El contador no debe incrementarse en una re-asignación"


@pytest.mark.db
def test_rls_recibo_contador_sin_contexto_cero_filas(
    app_engine: Engine, recibo_fixture: dict
) -> None:
    """Fail-closed: sin `app.current_org`, `recibo_contador` no devuelve filas."""
    org = recibo_fixture["org_a"]
    # Genera una fila de contador para la org.
    _confirmar_efectivo(
        app_engine, org=org, cuota=recibo_fixture["cuota_a"], user=recibo_fixture["user_a"]
    )

    with app_engine.connect() as conn:
        count = conn.execute(text("SELECT count(*) FROM recibo_contador")).scalar_one()
    assert count == 0, "Sin contexto de tenant, recibo_contador debe devolver 0 filas"


@pytest.mark.db
def test_rls_recibo_contador_aisla_entre_orgs(app_engine: Engine, recibo_fixture: dict) -> None:
    """Con org A fijada se ve su contador pero no el de B."""
    org_a = recibo_fixture["org_a"]
    org_b = recibo_fixture["org_b"]
    _confirmar_efectivo(
        app_engine, org=org_a, cuota=recibo_fixture["cuota_a"], user=recibo_fixture["user_a"]
    )
    _confirmar_efectivo(
        app_engine, org=org_b, cuota=recibo_fixture["cuota_b"], user=recibo_fixture["user_b"]
    )

    with app_engine.begin() as conn:
        conn.execute(text("SELECT set_config('app.current_org', :o, true)"), {"o": str(org_a)})
        rows = conn.execute(text("SELECT org_id FROM recibo_contador")).scalars().all()
    org_ids = {str(r) for r in rows}
    assert str(org_a) in org_ids
    assert str(org_b) not in org_ids
