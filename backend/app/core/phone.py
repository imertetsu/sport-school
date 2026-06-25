"""Normalización de teléfonos a E.164-sin-`+` para los adaptadores de WhatsApp.

La Graph API de Meta (y el sidecar no-oficial Baileys) exigen el destinatario en
formato E.164 **sin** `+` ni espacios: dígitos con código de país, p.ej.
`59176123456`. Los servicios guardan el teléfono "humano" (tal como lo tecleó el
usuario: `+591 76123456`, `76123456`, con guiones/paréntesis) en sus registros/logs;
solo el adaptador debe formatear para la red. Esta función centraliza esa conversión.

**Internacional** (epic whatsapp-multitenant): el primer mercado es Bolivia, pero las
escuelas ya envían a destinos de Perú/Alemania. La función reconoce un conjunto
**ampliable** de códigos de país conocidos; si el número ya empieza por uno de ellos y
tiene un largo E.164 plausible (8–15 dígitos), se respeta tal cual (idempotente). El
caso BO clásico se **preserva**: un número local de 8 dígitos (sin código de país) se
prefija con el ``default_country_code`` (``591`` por defecto).

El 2º parámetro es **keyword-only y opcional** para mantener compatibilidad total con
los call-sites de 1 arg (`meta.py`, `gateway.py`): la firma NO se renombra.
"""

from __future__ import annotations

import re

# Códigos de país CONOCIDOS (ampliable: añadir más a la tupla). Se prueban de más
# largo a más corto para evitar que un prefijo más corto "tape" a uno más largo
# (p.ej. asegurar que `591…` se reconozca como Bolivia y no como otra cosa).
_KNOWN_COUNTRY_CODES: tuple[str, ...] = ("591", "51", "49")

# Largo del número LOCAL boliviano (móvil/fijo, sin código de país): 8 dígitos.
_BO_NATIONAL_LEN = 8

# Largo E.164 plausible del número COMPLETO (con código de país). E.164 admite hasta
# 15 dígitos; el mínimo razonable que aceptamos es 8.
_E164_MIN_LEN = 8
_E164_MAX_LEN = 15

_NON_DIGIT_RE = re.compile(r"\D")


def _is_e164_plausible(digits: str) -> bool:
    """`True` si `digits` tiene un largo E.164 plausible (8–15 dígitos)."""
    return _E164_MIN_LEN <= len(digits) <= _E164_MAX_LEN


def normalize_bo_phone(raw: str | None, *, default_country_code: str = "591") -> str | None:
    """Normaliza un teléfono a E.164-sin-`+` (solo dígitos).

    Reglas:
      - Quita espacios, guiones, paréntesis y un `+` inicial (de hecho, descarta
        cualquier carácter no numérico).
      - Si ya empieza por un **código de país conocido** (``591``, ``51``, ``49``;
        ampliable) y el largo total es **E.164 plausible** (8–15 dígitos), se usa tal
        cual. Esto hace la función **idempotente**: un número ya normalizado se
        devuelve sin cambios.
      - Si **no** empieza por un código conocido pero quedan **exactamente 8 dígitos**
        (móvil/fijo boliviano típico), se antepone ``default_country_code`` (preserva
        el caso BO de 8 dígitos).
      - En cualquier otro caso (vacío/``None``, no numérico, demasiado corto <8 o
        largo >15) devuelve ``None`` en vez de reventar; el llamador decide qué hacer
        (el adaptador reporta ``ok=False`` sin pegar a la red).

    Ejemplos:
      - ``"+591 76123456"``    -> ``"59176123456"``
      - ``"76123456"``         -> ``"59176123456"`` (BO local de 8 dígitos)
      - ``"59176123456"``      -> ``"59176123456"`` (idempotente)
      - ``"+51 987654321"``    -> ``"51987654321"`` (Perú)
      - ``"+49 1512 3456789"`` -> ``"4915123456789"`` (Alemania)
      - ``""`` / ``None``      -> ``None``
      - ``"abc"`` / ``"123"`` (muy corto) / cadena muy larga -> ``None``
    """
    if not raw:
        return None

    digits = _NON_DIGIT_RE.sub("", raw)
    if not digits:
        return None

    # ¿Ya viene con un código de país conocido? Se respeta si es E.164 plausible.
    for code in _KNOWN_COUNTRY_CODES:
        if digits.startswith(code):
            return digits if _is_e164_plausible(digits) else None

    # Número local boliviano (8 dígitos): se prefija con el código por defecto.
    if len(digits) == _BO_NATIONAL_LEN:
        candidate = default_country_code + digits
        return candidate if _is_e164_plausible(candidate) else None

    return None
