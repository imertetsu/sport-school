"""Normalización de teléfonos a E.164-sin-`+` para la Meta Cloud API.

La Graph API de Meta exige el destinatario en formato E.164 **sin** `+` ni
espacios: dígitos con código de país, p.ej. `59176123456`. Los servicios guardan
el teléfono "humano" (tal como lo tecleó el usuario: `+591 76123456`, `76123456`,
con guiones/paréntesis) en sus registros/logs; solo el adaptador de Meta debe
formatear para la red. Esta función centraliza esa conversión.

Bolivia es el primer (y por ahora único) mercado, así que el único código de país
soportado es `591`. El diseño deja sitio para extender a otros países sin
sobre-ingeniería: cuando llegue un segundo mercado, se parametrizará el prefijo
y el largo nacional esperado (probablemente recibiendo el país/`org` del llamador).
"""

from __future__ import annotations

import re

_BO_COUNTRY_CODE = "591"
_BO_NATIONAL_LEN = 8  # móvil/fijo boliviano: 8 dígitos sin código de país
# Largo plausible del número COMPLETO con código de país (591 + 8 = 11). Se deja
# un rango por si algún día hay numeraciones de 7-8 dígitos; fuera de eso, basura.
_FULL_MIN_LEN = len(_BO_COUNTRY_CODE) + 7
_FULL_MAX_LEN = len(_BO_COUNTRY_CODE) + 9

_NON_DIGIT_RE = re.compile(r"\D")


def normalize_bo_phone(raw: str | None) -> str | None:
    """Normaliza un teléfono boliviano a E.164-sin-`+` (solo dígitos).

    Reglas:
      - Quita espacios, guiones, paréntesis y un `+` inicial (de hecho, descarta
        cualquier carácter no numérico).
      - Si ya empieza por ``591`` y el largo total es plausible (10-12 dígitos),
        se usa tal cual. Esto hace la función **idempotente**: un número ya
        normalizado se devuelve sin cambios.
      - Si quedan exactamente 8 dígitos (móvil/fijo boliviano típico), se antepone
        ``591``.
      - En cualquier otro caso (vacío/``None``, no numérico, demasiado corto o
        largo) devuelve ``None`` en vez de reventar; el llamador decide qué hacer
        (el adaptador Meta reporta ``ok=False`` sin pegar a la red).

    Ejemplos:
      - ``"+591 76123456"`` -> ``"59176123456"``
      - ``"76123456"``      -> ``"59176123456"``
      - ``"591 7 612-3456"``-> ``"59176123456"``
      - ``"(591) 76123456"``-> ``"59176123456"``
      - ``"59176123456"``   -> ``"59176123456"`` (idempotente)
      - ``""`` / ``None``   -> ``None``
      - ``"abc"`` / ``"123"`` (muy corto) / cadena muy larga -> ``None``
    """
    if not raw:
        return None

    digits = _NON_DIGIT_RE.sub("", raw)
    if not digits:
        return None

    if digits.startswith(_BO_COUNTRY_CODE):
        if _FULL_MIN_LEN <= len(digits) <= _FULL_MAX_LEN:
            return digits
        return None

    if len(digits) == _BO_NATIONAL_LEN:
        return _BO_COUNTRY_CODE + digits

    return None
