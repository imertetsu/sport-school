"""OCR best-effort de un comprobante de pago (epic pagos-qr-comprobante, Fase 3).

`extraer_campos(imagen: bytes) -> dict` corre Tesseract (vía `pytesseract`, lang
`spa`) sobre la captura del comprobante y extrae, de forma **CONSERVADORA**, tres
campos pre-llenado: `monto`, `transaccion_id`, `fecha`. Espejo en espíritu del
parser de cédula del front (`frontend/src/components/ocr/parseCedula.ts`):

  - Es **best-effort**: NUNCA lanza. Si el binario de Tesseract falta o algo revienta,
    devuelve `{monto: None, transaccion_id: None, fecha: None, texto_crudo: ""}`.
  - Ante **baja confianza** deja el campo en `None` (mejor vacío que basura: el ADMIN
    completa a mano). El OCR solo PRE-LLENA; el admin siempre confirma (decisión v1).
  - Parseo por **regex** sobre el texto crudo; nada de heurísticas frágiles.

I/O acotada: `bytes -> dict`. No toca la BD. Vive en la capa de **servicios**
(`app.services`), no en el dominio — `pytesseract`/`PIL` aquí no rompen el contrato
import-linter (el dominio no importa este módulo; sí el servicio de comprobantes).
"""

from __future__ import annotations

import io
import logging
import re
from datetime import date
from decimal import Decimal, InvalidOperation

logger = logging.getLogger(__name__)

# Idioma de Tesseract: español (infra-dev instala `tesseract-ocr-spa`). Si el paquete
# de idioma faltara, pytesseract lanza y caemos al fallback (todo None) — best-effort.
_LANG = "spa"

# Meses en español (3 letras) para fechas "12 de junio de 2026" / "12 jun 2026".
_MESES: dict[str, int] = {
    "ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6,
    "jul": 7, "ago": 8, "sep": 9, "set": 9, "oct": 10, "nov": 11, "dic": 12,
}  # fmt: skip


def _vacio() -> dict:
    """Resultado fail-closed (sin campos leídos). El comprobante se guarda igual."""
    return {"monto": None, "transaccion_id": None, "fecha": None, "texto_crudo": ""}


def _ocr_texto(imagen: bytes) -> str:
    """Corre Tesseract sobre los bytes de la imagen. `""` si falla (best-effort).

    Imports diferidos de `pytesseract`/`PIL`: si el binario de Tesseract o el wrapper
    no están (p.ej. máquina dev sin instalarlo), NO se rompe el import del módulo ni
    el flujo del webhook — devolvemos cadena vacía y el comprobante queda sin OCR.
    """
    try:
        import pytesseract
        from PIL import Image

        with Image.open(io.BytesIO(imagen)) as img:
            return str(pytesseract.image_to_string(img, lang=_LANG))
    except Exception as exc:  # noqa: BLE001 - OCR best-effort: nunca revienta el flujo.
        logger.info(
            "OCR comprobante no disponible/falló (%s); se guarda sin OCR", type(exc).__name__
        )
        return ""


# --------------------------------------------------------------------------- #
# Monto
# --------------------------------------------------------------------------- #
# Importe con decimales precedido (idealmente) por "Bs"/"BOB"/"Bs." y separador de
# miles opcional. CONSERVADOR: exige parte decimal (.NN / ,NN), que es lo típico de un
# comprobante de pago; un entero suelto (un nº de operación) NO se toma como monto.
_MONTO_BS_RE = re.compile(
    r"(?:bs\.?|bob)\s*([0-9]{1,3}(?:[.\s][0-9]{3})*(?:[.,][0-9]{2})|[0-9]+[.,][0-9]{2})",
    re.IGNORECASE,
)
# Fallback sin etiqueta de moneda: un importe con 2 decimales aislado.
_MONTO_DEC_RE = re.compile(r"\b([0-9]{1,3}(?:[.\s][0-9]{3})*[.,][0-9]{2}|[0-9]+[.,][0-9]{2})\b")


def _parse_monto(texto: str) -> Decimal | None:
    """Primer importe plausible (con decimales). Prefiere el etiquetado "Bs"/"BOB".

    Normaliza separadores: el último `.`/`,` es el decimal; el resto (miles) se quita.
    Ante cualquier duda (sin match, valor no parseable o ≤ 0) ⇒ `None`.
    """
    m = _MONTO_BS_RE.search(texto)
    if m is None:
        m = _MONTO_DEC_RE.search(texto)
    if m is None:
        return None

    crudo = m.group(1).strip()
    # Quita espacios de miles; deja solo dígitos y el separador decimal final.
    crudo = crudo.replace(" ", "")
    # El separador decimal es el ÚLTIMO `.` o `,`. Lo aislamos y borramos los demás.
    sep_idx = max(crudo.rfind("."), crudo.rfind(","))
    if sep_idx == -1:
        return None
    entero = re.sub(r"[.,]", "", crudo[:sep_idx])
    decimal = crudo[sep_idx + 1 :]
    if not entero or not decimal.isdigit():
        return None
    try:
        valor = Decimal(f"{entero}.{decimal}")
    except InvalidOperation:
        return None
    return valor if valor > Decimal("0") else None


# --------------------------------------------------------------------------- #
# Nº de transacción / operación
# --------------------------------------------------------------------------- #
# Etiqueta ("transacción"/"operación"/"comprobante"/"nro de control"...) seguida de un
# grupo de dígitos (6+). CONSERVADOR: exige la etiqueta — un nº suelto no es fiable.
_TX_RE = re.compile(
    r"(?:n(?:ro|°|º|o)?\.?\s*(?:de\s+)?)?"
    r"(?:transacci[oó]n|operaci[oó]n|comprobante|control|autorizaci[oó]n|referencia)"
    r"[^0-9]{0,12}([0-9]{6,})",
    re.IGNORECASE,
)


def _parse_transaccion(texto: str) -> str | None:
    """Nº de transacción/operación etiquetado (≥6 dígitos). `None` si no hay etiqueta."""
    m = _TX_RE.search(texto)
    if m is None:
        return None
    return m.group(1)


# --------------------------------------------------------------------------- #
# Fecha
# --------------------------------------------------------------------------- #
_FECHA_NUM_RE = re.compile(r"\b([0-3]?\d)[\s./-]+([01]?\d)[\s./-]+((?:19|20)\d{2}|\d{2})\b")
_FECHA_MES_RE = re.compile(
    r"\b([0-3]?\d)\s*(?:de\s+)?([a-záéíóú]{3,12})\.?\s*(?:de\s+)?((?:19|20)\d{2})\b",
    re.IGNORECASE,
)


def _anio4(anio: str) -> int:
    """Expande un año de 2 dígitos a 4 (20xx) y deja los de 4 tal cual."""
    n = int(anio)
    return n if n >= 100 else 2000 + n


def _fecha_valida(anio: int, mes: int, dia: int) -> date | None:
    """Construye una `date` o devuelve `None` si los componentes no son plausibles."""
    if not (1 <= mes <= 12 and 1 <= dia <= 31 and 2000 <= anio <= 2100):
        return None
    try:
        return date(anio, mes, dia)
    except ValueError:
        return None


def _parse_fecha(texto: str) -> date | None:
    """Primera fecha plausible: `dd/mm/yyyy`/`dd-mm-yy` o `dd de <mes> de yyyy`.

    Asume orden día-mes-año (formato latinoamericano de los comprobantes). Ante
    componentes implausibles ⇒ `None`.
    """
    m = _FECHA_NUM_RE.search(texto)
    if m is not None:
        f = _fecha_valida(_anio4(m.group(3)), int(m.group(2)), int(m.group(1)))
        if f is not None:
            return f

    m = _FECHA_MES_RE.search(texto)
    if m is not None:
        mes = _MESES.get(m.group(2).lower()[:3])
        if mes is not None:
            f = _fecha_valida(int(m.group(3)), mes, int(m.group(1)))
            if f is not None:
                return f
    return None


def extraer_campos(imagen: bytes) -> dict:
    """Extrae `{monto, transaccion_id, fecha, texto_crudo}` de la captura (best-effort).

    NUNCA lanza: si el OCR falla (binario ausente, imagen corrupta) ⇒ todos `None` y
    `texto_crudo=""`. Parseo conservador: cada campo queda `None` ante baja confianza
    (el ADMIN lo completa a mano al confirmar). `texto_crudo` se guarda en
    `comprobante_pendiente.ocr_texto_crudo` para auditoría/depuración.
    """
    if not imagen:
        return _vacio()

    texto = _ocr_texto(imagen)
    if not texto:
        return _vacio()

    return {
        "monto": _parse_monto(texto),
        "transaccion_id": _parse_transaccion(texto),
        "fecha": _parse_fecha(texto),
        "texto_crudo": texto,
    }
