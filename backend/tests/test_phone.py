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
    ],
)
def test_normaliza_validos(raw: str, expected: str) -> None:
    assert normalize_bo_phone(raw) == expected


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
        "591",  # solo el código de país
        "5911234",  # empieza por 591 pero demasiado corto
        "591761234567890",  # empieza por 591 pero demasiado largo
        "++--()",  # sin dígitos tras limpiar
    ],
)
def test_invalidos_devuelven_none(raw: str | None) -> None:
    assert normalize_bo_phone(raw) is None
