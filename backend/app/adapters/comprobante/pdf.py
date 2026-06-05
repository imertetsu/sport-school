"""Adaptador de comprobante PDF con **fpdf2** — implementa `ComprobanteService` (C5).

Renderiza un PDF con: nombre de la org, alumno, cuota(s) cubiertas, monto,
método, fecha y número de comprobante. Sin I/O de BD: recibe `ComprobanteData`
(dominio) y devuelve bytes; el router lo sirve on-the-fly en
`GET …/comprobantes/{id}.pdf`.
"""

from __future__ import annotations

from fpdf import FPDF

from app.domain.ports.invoice import ComprobanteData, ComprobanteService


class PdfComprobanteService(ComprobanteService):
    """Genera el comprobante como PDF A4 en memoria."""

    def render_pdf(self, data: ComprobanteData) -> bytes:
        pdf = FPDF(orientation="P", unit="mm", format="A4")
        pdf.set_auto_page_break(auto=True, margin=15)
        pdf.add_page()

        # Encabezado: organización + título.
        pdf.set_font("Helvetica", "B", 16)
        pdf.cell(0, 10, _ascii(data.org_nombre), new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 8, "Comprobante de pago", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(0, 6, f"Nro: {_ascii(data.numero)}", new_x="LMARGIN", new_y="NEXT")
        pdf.cell(
            0, 6, f"Fecha: {data.fecha.strftime('%Y-%m-%d %H:%M')}", new_x="LMARGIN", new_y="NEXT"
        )
        pdf.cell(0, 6, f"Metodo: {_ascii(data.metodo)}", new_x="LMARGIN", new_y="NEXT")
        pdf.ln(4)

        # Datos del alumno.
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(0, 7, "Alumno", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 10)
        pdf.cell(0, 6, _ascii(data.alumno_nombre), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(4)

        # Tabla de cuotas cubiertas.
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(0, 7, "Cuotas cubiertas", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "B", 9)
        pdf.cell(60, 7, "Periodo (inicio)", border=1)
        pdf.cell(60, 7, "Vence", border=1)
        pdf.cell(40, 7, f"Monto ({_ascii(data.moneda)})", border=1, new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 9)
        for linea in data.cuotas:
            pdf.cell(60, 7, _ascii(linea.periodo_inicio), border=1)
            pdf.cell(60, 7, _ascii(linea.vence_el), border=1)
            pdf.cell(40, 7, f"{linea.monto:.2f}", border=1, new_x="LMARGIN", new_y="NEXT")

        # Total.
        pdf.ln(2)
        pdf.set_font("Helvetica", "B", 11)
        pdf.cell(120, 8, "Total", border=0)
        pdf.cell(
            40,
            8,
            f"{data.monto_total:.2f} {_ascii(data.moneda)}",
            border=0,
            new_x="LMARGIN",
            new_y="NEXT",
        )

        out = pdf.output()
        return bytes(out)


def _ascii(text: str) -> str:
    """fpdf2 con fuentes core (Helvetica) usa latin-1; degradamos a ASCII seguro
    para no romper con tildes/ñ (suficiente para el comprobante de dev)."""
    return text.encode("ascii", "replace").decode("ascii")
