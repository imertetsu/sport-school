"""Tests del OCR de comprobantes (`app.services.ocr`) — epic pagos-qr-comprobante.

El OCR es **best-effort**: parsea el texto crudo de Tesseract con regex conservadores.
Estos tests ejercitan los **parsers** directamente sobre texto (no necesitan el binario
de Tesseract ni BD) y verifican el **fail-closed** de `extraer_campos` cuando no hay OCR.

Espejo en espíritu de `parseCedula.ts`: ante baja confianza ⇒ `None` (nunca revienta).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.services import ocr


# --------------------------------------------------------------------------- #
# Monto
# --------------------------------------------------------------------------- #
def test_monto_etiqueta_bs() -> None:
    assert ocr._parse_monto("Pago por Bs 250.00 confirmado") == Decimal("250.00")


def test_monto_con_miles_y_coma_decimal() -> None:
    assert ocr._parse_monto("Total Bs 1.250,50") == Decimal("1250.50")


def test_monto_sin_decimales_no_se_toma() -> None:
    # Un entero suelto (p.ej. un nº de operación) NO es un monto: conservador.
    assert ocr._parse_monto("Operacion 123456 exitosa") is None


def test_monto_ilegible_none() -> None:
    assert ocr._parse_monto("transferencia realizada") is None


# --------------------------------------------------------------------------- #
# Nº de transacción / operación
# --------------------------------------------------------------------------- #
def test_transaccion_etiquetada() -> None:
    assert ocr._parse_transaccion("Nro. de transaccion: 987654321") == "987654321"


def test_operacion_etiquetada() -> None:
    assert ocr._parse_transaccion("Operacion N 1002003004") == "1002003004"


def test_transaccion_sin_etiqueta_none() -> None:
    # Sin etiqueta, un nº suelto no es fiable: conservador.
    assert ocr._parse_transaccion("su pago de 123456789 fue") is None


# --------------------------------------------------------------------------- #
# Fecha
# --------------------------------------------------------------------------- #
def test_fecha_numerica_ddmmyyyy() -> None:
    assert ocr._parse_fecha("Fecha: 25/06/2026 14:32") == date(2026, 6, 25)


def test_fecha_con_mes_texto() -> None:
    assert ocr._parse_fecha("12 de junio de 2026") == date(2026, 6, 12)


def test_fecha_implausible_none() -> None:
    assert ocr._parse_fecha("ref 99/99/2026") is None


def test_fecha_ausente_none() -> None:
    assert ocr._parse_fecha("comprobante de pago") is None


# --------------------------------------------------------------------------- #
# extraer_campos (orquestador best-effort, fail-closed)
# --------------------------------------------------------------------------- #
def test_extraer_campos_imagen_vacia_todo_none() -> None:
    out = ocr.extraer_campos(b"")
    assert out == {"monto": None, "transaccion_id": None, "fecha": None, "texto_crudo": ""}


def test_extraer_campos_media_ilegible_no_revienta() -> None:
    # Bytes que NO son una imagen válida ⇒ Tesseract/PIL falla ⇒ fail-closed (todo None).
    out = ocr.extraer_campos(b"esto-no-es-una-imagen")
    assert out["monto"] is None
    assert out["transaccion_id"] is None
    assert out["fecha"] is None
    assert out["texto_crudo"] == ""


def test_extraer_campos_desde_texto_via_parsers(monkeypatch) -> None:
    """Simula que Tesseract leyó un comprobante: los parsers extraen los 3 campos.

    Parchea `_ocr_texto` (no necesitamos el binario en CI/dev): así verificamos el
    pipeline completo `texto -> {monto, transaccion_id, fecha}` de forma determinista.
    """
    texto = (
        "BANCO XYZ\n"
        "Pago QR exitoso\n"
        "Monto: Bs 350.00\n"
        "Nro. de transaccion: 5566778899\n"
        "Fecha: 25/06/2026 10:15\n"
    )
    monkeypatch.setattr(ocr, "_ocr_texto", lambda _img: texto)

    out = ocr.extraer_campos(b"\x89PNG-falsos-bytes")
    assert out["monto"] == Decimal("350.00")
    assert out["transaccion_id"] == "5566778899"
    assert out["fecha"] == date(2026, 6, 25)
    assert "BANCO XYZ" in out["texto_crudo"]
