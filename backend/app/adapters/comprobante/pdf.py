"""Adaptador de comprobante PDF con **fpdf2** — implementa `ComprobanteService` (C5).

Renderiza un recibo de pago **con marca**: banda de cabecera, emblema con las
iniciales de la escuela, título "RECIBO DE PAGO", datos del deportista, detalle de
cuotas cubiertas, total destacado y pie de agradecimiento + leyenda legal.

Sin I/O de BD: recibe `ComprobanteData` (dominio) y devuelve bytes; el router lo
sirve on-the-fly en `GET …/comprobantes/{id}.pdf` y en el recibo público tokenizado.

Tipografía: fuentes *core* de fpdf2 (Helvetica) en codificación **latin-1**, que sí
cubre acentos y ñ del español — así el recibo muestra "MÉTODO", "Categoría", etc.
No embebemos TTF (evita un binario en el repo y que el runtime Linux tenga la fuente).
`_latin1` degrada solo lo que latin-1 no cubre (em-dash, comillas tipográficas…).
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from pathlib import Path

from fpdf import FPDF

from app.domain.ports.invoice import (
    ComprobanteData,
    ComprobanteService,
    KardexData,
)

# Logo de la app (LATINOSPORT), recortado. Vive en app/assets/ y se empaqueta en la
# imagen. Si faltara, el render degrada sin romper (branding opcional).
_LOGO_PATH = Path(__file__).resolve().parents[2] / "assets" / "logo_latinosport.png"
_LOGO_W_PX, _LOGO_H_PX = 1004, 699  # tamaño del PNG recortado (para el aspect ratio)
_APP_NOMBRE = "LATINOSPORT"

# --------------------------------------------------------------------------- #
# Paleta de marca (navy + verde, como el recibo de referencia)
# --------------------------------------------------------------------------- #
_NAVY = (26, 54, 93)  # #1A365D — banda de cabecera / encabezados de tabla
_GREEN = (124, 179, 66)  # #7CB342 — emblema, badge, total pagado
_INK = (33, 37, 41)  # texto principal
_MUTED = (108, 117, 125)  # etiquetas / texto secundario
_LIGHT = (247, 249, 251)  # relleno de filas alternas
_WHITE = (255, 255, 255)
_HEADER_TXT = (219, 228, 240)  # texto tenue sobre la banda navy

_HEADER_H = 46.0  # alto de la banda de cabecera (mm)
_ML = 15.0  # margen izquierdo (mm)
_CONTENT_W = 180.0  # ancho de contenido (210 - 2*15)

_MESES = (
    "",
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
)
_METODO_LABEL = {"EFECTIVO": "Efectivo", "QR": "QR"}


class PdfComprobanteService(ComprobanteService):
    """Genera el recibo como PDF A4 en memoria, con la marca de la escuela."""

    def render_pdf(self, data: ComprobanteData) -> bytes:
        pdf = FPDF(orientation="P", unit="mm", format="A4")
        pdf.set_margins(_ML, 12, _ML)
        pdf.set_auto_page_break(auto=True, margin=15)
        pdf.add_page()

        self._cabecera(pdf, data)
        self._datos_deportista(pdf, data)
        self._detalle_pago(pdf, data)
        self._pie(pdf, data.emisor)

        return bytes(pdf.output())

    # ------------------------------------------------------------------ #
    # KARDEX de pagos (estado de cuenta imprimible del deportista)
    # ------------------------------------------------------------------ #
    def render_kardex_pdf(self, data: KardexData) -> bytes:
        pdf = FPDF(orientation="P", unit="mm", format="A4")
        pdf.set_margins(_ML, 12, _ML)
        pdf.set_auto_page_break(auto=True, margin=18)
        pdf.add_page()

        self._cabecera_kardex(pdf, data)
        self._tabla_kardex(pdf, data)
        self._pie(pdf, data.emisor)

        return bytes(pdf.output())

    def _cabecera_kardex(self, pdf: FPDF, data: KardexData) -> None:
        pdf.set_fill_color(*_NAVY)
        pdf.rect(0, 0, 210, _HEADER_H, "F")

        # Emblema con iniciales de la escuela.
        pdf.set_fill_color(*_GREEN)
        pdf.ellipse(19, 13, 20, 20, "F")
        pdf.set_text_color(*_WHITE)
        pdf.set_font("Helvetica", "B", 15)
        pdf.set_xy(19, 13)
        pdf.cell(20, 20, _latin1(_iniciales(data.org_nombre)), align="C")

        pdf.set_font("Helvetica", "B", 15)
        pdf.set_xy(43, 15)
        pdf.cell(62, 9, _latin1(_encoge(data.org_nombre, 24)))
        pdf.set_text_color(*_HEADER_TXT)
        pdf.set_font("Helvetica", "B", 8)
        pdf.set_xy(43, 25)
        pdf.cell(62, 5, _latin1(f"Gestionado con {_APP_NOMBRE}"))

        # Título "KARDEX DE PAGOS" + fecha de emisión (derecha).
        pdf.set_text_color(*_WHITE)
        pdf.set_font("Helvetica", "B", 21)
        pdf.set_xy(105, 11)
        pdf.cell(90, 12, "KARDEX DE PAGOS", align="R")
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(*_HEADER_TXT)
        pdf.set_xy(105, 30)
        pdf.cell(90, 5, _latin1(f"Emitido el {_fecha_larga(data.fecha_emision)}"), align="R")

        pdf.set_text_color(*_INK)
        pdf.set_y(_HEADER_H + 8)

        # Datos del deportista + resumen (total pagado / nº de pagos).
        self._titulo_seccion(pdf, "ESTADO DE CUENTA DEL DEPORTISTA")
        self._fila_dato(pdf, "Deportista", data.deportista_nombre)
        self._fila_dato(pdf, "Pagos registrados", str(data.num_pagos))
        self._fila_dato(
            pdf, "Total pagado", f"{data.total_pagado:.2f} {_latin1(data.moneda)}"
        )
        pdf.ln(3)

    def _tabla_kardex(self, pdf: FPDF, data: KardexData) -> None:
        self._titulo_seccion(pdf, "HISTORIAL DE PAGOS")
        moneda = _latin1(data.moneda)

        if not data.filas:
            pdf.set_x(_ML)
            pdf.set_font("Helvetica", "I", 10)
            pdf.set_text_color(*_MUTED)
            pdf.cell(_CONTENT_W, 8, "Sin pagos registrados aun.", align="C")
            pdf.ln(8)
            return

        # Orden: Recibo | Cuota | Vencimiento | Fecha de pago | Metodo | Monto.
        cols = (
            ("Recibo", 26, "L"),
            ("Cuota", 35, "L"),
            ("Vencimiento", 33, "L"),
            ("Fecha de pago", 33, "L"),
            ("Metodo", 18, "L"),
            (f"Monto ({moneda})", 35, "R"),
        )
        pdf.set_x(_ML)
        pdf.set_fill_color(*_NAVY)
        pdf.set_text_color(*_WHITE)
        pdf.set_font("Helvetica", "B", 8.5)
        for titulo, w, align in cols:
            pdf.cell(w, 8, _latin1(titulo), align=align, fill=True)
        pdf.ln(8)

        pdf.set_font("Helvetica", "", 8.5)
        for i, f in enumerate(data.filas):
            fill = i % 2 == 1
            if fill:
                pdf.set_fill_color(*_LIGHT)
            pdf.set_x(_ML)
            pdf.set_text_color(*_INK)
            pdf.cell(26, 7.5, _latin1(f.numero_recibo), align="L", fill=fill)
            pdf.cell(35, 7.5, _latin1(f.cuota), align="L", fill=fill)
            pdf.set_text_color(*_MUTED)
            pdf.cell(33, 7.5, _latin1(f.vence), align="L", fill=fill)
            pdf.set_text_color(*_INK)
            pdf.cell(33, 7.5, _latin1(f.fecha_pago), align="L", fill=fill)
            pdf.set_text_color(*_MUTED)
            pdf.cell(18, 7.5, _latin1(f.metodo), align="L", fill=fill)
            pdf.set_text_color(*_INK)
            pdf.cell(35, 7.5, f"{f.monto:.2f}", align="R", fill=fill)
            pdf.ln(7.5)

        # Total pagado (banda verde).
        pdf.set_x(_ML)
        pdf.set_fill_color(*_GREEN)
        pdf.set_text_color(*_WHITE)
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(145, 10, "  TOTAL PAGADO", align="L", fill=True)
        pdf.cell(35, 10, f"{data.total_pagado:.2f}", align="R", fill=True)
        pdf.ln(10)

    # ------------------------------------------------------------------ #
    # Banda de cabecera: emblema + escuela + título + folio/fecha
    # ------------------------------------------------------------------ #
    def _cabecera(self, pdf: FPDF, data: ComprobanteData) -> None:
        pdf.set_fill_color(*_NAVY)
        pdf.rect(0, 0, 210, _HEADER_H, "F")

        # Emblema circular con las iniciales de la escuela (sin logo de archivo).
        pdf.set_fill_color(*_GREEN)
        pdf.ellipse(19, 13, 20, 20, "F")
        pdf.set_text_color(*_WHITE)
        pdf.set_font("Helvetica", "B", 15)
        pdf.set_xy(19, 13)
        pdf.cell(20, 20, _latin1(_iniciales(data.org_nombre)), align="C")

        # Nombre de la escuela, centrado verticalmente junto al emblema.
        pdf.set_font("Helvetica", "B", 15)
        pdf.set_xy(43, 15)
        pdf.cell(62, 9, _latin1(_encoge(data.org_nombre, 24)))

        # Nombre de la app (marca de la plataforma) debajo del nombre de la escuela.
        pdf.set_text_color(*_HEADER_TXT)
        pdf.set_font("Helvetica", "B", 8)
        pdf.set_xy(43, 25)
        pdf.cell(62, 5, _latin1(f"Gestionado con {_APP_NOMBRE}"))
        pdf.set_text_color(*_WHITE)

        # Título "RECIBO DE PAGO" + badge de concepto (derecha).
        pdf.set_text_color(*_WHITE)
        pdf.set_font("Helvetica", "B", 21)
        pdf.set_xy(105, 9)
        pdf.cell(90, 12, "RECIBO DE PAGO", align="R")

        pdf.set_fill_color(*_GREEN)
        pdf.rect(150, 23, 45, 6.5, "F")
        pdf.set_font("Helvetica", "B", 8)
        pdf.set_xy(150, 23)
        pdf.cell(45, 6.5, "MENSUALIDAD", align="C")

        # Folio (N° de recibo) + fecha, alineados a la derecha.
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(*_HEADER_TXT)
        pdf.set_xy(105, 32)
        pdf.cell(45, 5, "N° RECIBO", align="L")
        pdf.set_text_color(*_WHITE)
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(45, 5, _latin1(data.numero_recibo), align="R")

        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(*_HEADER_TXT)
        pdf.set_xy(105, 38)
        pdf.cell(45, 5, "FECHA", align="L")
        pdf.set_text_color(*_WHITE)
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(45, 5, _latin1(_fecha_larga(data.fecha)), align="R")

        pdf.set_text_color(*_INK)
        pdf.set_y(_HEADER_H + 8)

    # ------------------------------------------------------------------ #
    # Datos del deportista + método de pago
    # ------------------------------------------------------------------ #
    def _datos_deportista(self, pdf: FPDF, data: ComprobanteData) -> None:
        self._titulo_seccion(pdf, "DATOS DEL DEPORTISTA")
        self._fila_dato(pdf, "Deportista", data.deportista_nombre)
        metodo = _METODO_LABEL.get(data.metodo, data.metodo)
        self._fila_dato(pdf, "Método de pago", metodo)
        pdf.ln(4)

    # ------------------------------------------------------------------ #
    # Detalle de pago: tabla de cuotas + total + crédito
    # ------------------------------------------------------------------ #
    def _detalle_pago(self, pdf: FPDF, data: ComprobanteData) -> None:
        self._titulo_seccion(pdf, "DETALLE DE PAGO")
        moneda = _latin1(data.moneda)

        # Encabezado de tabla (navy, texto blanco). "Vence" es más ancho porque
        # ahora muestra la fecha en largo ("12 de Febrero de 2026").
        cols = (
            ("Período", 38, "L"),
            ("Vence", 48, "L"),
            (f"Monto ({moneda})", 32, "R"),
            ("Aplicado", 31, "R"),
            ("Saldo", 31, "R"),
        )
        pdf.set_x(_ML)
        pdf.set_fill_color(*_NAVY)
        pdf.set_text_color(*_WHITE)
        pdf.set_font("Helvetica", "B", 9)
        for titulo, w, align in cols:
            pdf.cell(w, 8, _latin1(titulo), align=align, fill=True)
        pdf.ln(8)

        # Filas de cuotas (relleno alterno para legibilidad).
        pdf.set_font("Helvetica", "", 9)
        for i, linea in enumerate(data.cuotas):
            aplicado = linea.monto_aplicado if linea.monto_aplicado is not None else linea.monto
            fill = i % 2 == 1
            if fill:
                pdf.set_fill_color(*_LIGHT)
            pdf.set_x(_ML)
            pdf.set_text_color(*_INK)
            pdf.cell(38, 7.5, _latin1(linea.periodo_inicio), align="L", fill=fill)
            pdf.set_text_color(*_MUTED)
            pdf.cell(48, 7.5, _latin1(linea.vence_el), align="L", fill=fill)
            pdf.set_text_color(*_INK)
            pdf.cell(32, 7.5, f"{linea.monto:.2f}", align="R", fill=fill)
            pdf.cell(31, 7.5, f"{aplicado:.2f}", align="R", fill=fill)
            pdf.cell(31, 7.5, f"{linea.saldo_restante:.2f}", align="R", fill=fill)
            pdf.ln(7.5)

        # Total pagado (banda verde destacada).
        pdf.set_x(_ML)
        pdf.set_fill_color(*_GREEN)
        pdf.set_text_color(*_WHITE)
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(112, 10, "  TOTAL PAGADO", align="L", fill=True)
        pdf.cell(68, 10, f"{data.monto_total:.2f} {moneda}  ", align="R", fill=True)
        pdf.ln(10)

        # Crédito aplicado / saldo a favor generado (Abonos). Defaults 0 ⇒ no aparece.
        if data.credito_aplicado > Decimal("0") or data.credito_generado > Decimal("0"):
            pdf.ln(2)
            pdf.set_font("Helvetica", "", 9)
            pdf.set_text_color(*_MUTED)
            if data.credito_aplicado > Decimal("0"):
                pdf.set_x(_ML)
                pdf.cell(112, 6, "Crédito aplicado", align="L")
                pdf.cell(68, 6, f"-{data.credito_aplicado:.2f} {moneda}", align="R")
                pdf.ln(6)
            if data.credito_generado > Decimal("0"):
                pdf.set_x(_ML)
                pdf.cell(112, 6, "Saldo a favor generado", align="L")
                pdf.cell(68, 6, f"{data.credito_generado:.2f} {moneda}", align="R")
                pdf.ln(6)

    # ------------------------------------------------------------------ #
    # Pie: agradecimiento
    # ------------------------------------------------------------------ #
    def _pie(self, pdf: FPDF, emisor: str) -> None:
        pdf.ln(12)
        pdf.set_text_color(*_NAVY)
        pdf.set_font("Helvetica", "I", 13)
        pdf.set_x(_ML)
        pdf.cell(_CONTENT_W, 8, "Gracias por confiar en nuestro equipo", align="C")
        pdf.ln(10)
        _logo_centrado(pdf, w=42.0)
        pdf.set_text_color(*_MUTED)
        pdf.set_font("Helvetica", "", 8)
        pdf.set_x(_ML)
        pdf.cell(_CONTENT_W, 5, _latin1(emisor), align="C")

    # ------------------------------------------------------------------ #
    # Helpers de layout
    # ------------------------------------------------------------------ #
    def _titulo_seccion(self, pdf: FPDF, titulo: str) -> None:
        """Encabezado de sección con barra de acento verde a la izquierda."""
        y = pdf.get_y()
        pdf.set_fill_color(*_GREEN)
        pdf.rect(_ML, y + 0.5, 2.6, 5, "F")
        pdf.set_text_color(*_NAVY)
        pdf.set_font("Helvetica", "B", 11)
        pdf.set_xy(_ML + 5, y)
        pdf.cell(_CONTENT_W - 5, 6, _latin1(titulo))
        pdf.ln(9)

    def _fila_dato(self, pdf: FPDF, etiqueta: str, valor: str) -> None:
        """Fila etiqueta (muted) + valor (ink) del bloque de datos."""
        pdf.set_x(_ML)
        pdf.set_text_color(*_MUTED)
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(40, 6.5, _latin1(etiqueta.upper()))
        pdf.set_text_color(*_INK)
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(_CONTENT_W - 40, 6.5, _latin1(valor))
        pdf.ln(6.5)


# --------------------------------------------------------------------------- #
# Utilidades de texto
# --------------------------------------------------------------------------- #
_LATIN1_MAP = {
    "—": "-",  # em dash
    "–": "-",  # en dash
    "‘": "'",  # comilla simple izq.
    "’": "'",  # comilla simple der.
    "“": '"',  # comilla doble izq.
    "”": '"',  # comilla doble der.
    "…": "...",  # puntos suspensivos
    " ": " ",  # espacio duro
}


def _latin1(text: str) -> str:
    """Sanitiza a latin-1 (cubre acentos/ñ del español); degrada lo que no cabe.

    Las fuentes core de fpdf2 usan latin-1, que SÍ incluye á/é/í/ó/ú/ñ/¿/¡. Solo
    reemplazamos caracteres fuera de latin-1 (guiones largos, comillas tipográficas)
    por equivalentes ASCII; cualquier otro cae a "?" en vez de romper el render.
    """
    for uni, ascii_ in _LATIN1_MAP.items():
        text = text.replace(uni, ascii_)
    return text.encode("latin-1", "replace").decode("latin-1")


def _encoge(text: str, largo: int) -> str:
    """Recorta a `largo` caracteres con puntos suspensivos si se pasa (una sola línea)."""
    text = text.strip()
    return text if len(text) <= largo else text[: largo - 1].rstrip() + "…"


def _iniciales(nombre: str) -> str:
    """Iniciales de la escuela para el emblema (1-2 letras)."""
    palabras = [p for p in nombre.split() if p]
    if not palabras:
        return "?"
    if len(palabras) == 1:
        return palabras[0][:2].upper()
    return (palabras[0][0] + palabras[1][0]).upper()


def _fecha_larga(dt: datetime) -> str:
    """Fecha en español largo con mes en Título: `25 de Mayo de 2026`."""
    return f"{dt.day} de {_MESES[dt.month].capitalize()} de {dt.year}"


def _logo_centrado(pdf: FPDF, *, w: float) -> None:
    """Dibuja el logo de la app centrado en la Y actual (no-op si falta el archivo).

    El logo tiene fondo claro; se pinta sobre el área blanca del pie (se integra).
    """
    if not _LOGO_PATH.exists():
        return
    h = w * _LOGO_H_PX / _LOGO_W_PX
    pdf.image(str(_LOGO_PATH), x=(210 - w) / 2, y=pdf.get_y(), w=w)
    pdf.set_y(pdf.get_y() + h + 2)
