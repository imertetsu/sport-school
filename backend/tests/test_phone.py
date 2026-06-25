"""Tests del normalizador de teléfono boliviano -> E.164-sin-`+` (`app.core.phone`).

Sin BD: función pura. Cubre el contrato que consume el adaptador Meta (Meta Cloud
API exige dígitos con código de país, sin `+` ni espacios).
"""

from __future__ import annotations

import pytest
from app.core.phone import normalize_bo_phone


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        # +591 con espacio -> quita + y espacios
        ("+591 76123456", "59176123456"),
        # 8 dígitos (móvil boliviano típico) -> antepone 591
        ("76123456", "59176123456"),
        # ya con 591 y espacios internos
        ("591 76123456", "59176123456"),
        ("591 7 612-3456", "59176123456"),
        # guiones y paréntesis
        ("7612-3456", "59176123456"),
        ("(591) 76123456", "59176123456"),
        ("+591-7612-3456", "59176123456"),
        # ya correcto -> idempotente
        ("59176123456", "59176123456"),
        # internacional (epic whatsapp-multitenant): Perú / Alemania
        ("+51 987654321", "51987654321"),  # Perú: ya con código 51
        ("+49 1512 3456789", "4915123456789"),  # Alemania: ya con código 49 (13 dígitos)
    ],
)
def test_normaliza_validos(raw: str, expected: str) -> None:
    assert normalize_bo_phone(raw) == expected


def test_idempotente_internacional() -> None:
    """Un número ya internacional (51/49) se devuelve sin cambios (idempotente)."""
    assert normalize_bo_phone("51987654321") == "51987654321"
    assert normalize_bo_phone("4915123456789") == "4915123456789"


def test_default_country_code_es_keyword_only_y_opcional() -> None:
    """El 2º parámetro es keyword-only y opcional (compat con call-sites de 1 arg).

    La regla de prefijo aplica a un número LOCAL de exactamente 8 dígitos: con el
    default (591) → BO; con `default_country_code="51"` se prefija ese código.
    """
    assert normalize_bo_phone("76123456") == "59176123456"
    assert normalize_bo_phone("12345678", default_country_code="51") == "5112345678"


def test_idempotente() -> None:
    once = normalize_bo_phone("+591 76123456")
    assert once is not None
    assert normalize_bo_phone(once) == once


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "",
        "   ",
        "abc",
        "123",  # demasiado corto
        "1234567",  # 7 dígitos, no es 8 ni empieza por 591
        "591",  # solo el código de país (3 dígitos, no E.164 plausible)
        "5911234",  # empieza por 591 pero demasiado corto (7 dígitos)
        "5917612345678901",  # 16 dígitos: pasa el máximo E.164 (15) -> None
        "++--()",  # sin dígitos tras limpiar
    ],
)
def test_invalidos_devuelven_none(raw: str | None) -> None:
    assert normalize_bo_phone(raw) is None
