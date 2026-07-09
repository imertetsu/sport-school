"""Puertos de facturación/comprobantes (PDF local; SIN en fase 2).

El núcleo define las interfaces; los adaptadores (`app.adapters.comprobante`) las
implementan. `ComprobanteService` es el puerto del comprobante PDF de este epic
(C5); `InvoiceProvider` queda como esqueleto para la factura electrónica SIN.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class CuotaLinea:
    """Una cuota cubierta por el pago, para el detalle del comprobante (C5).

    Abonos (RF-ABO): `monto_aplicado` es lo que este pago aplicó a la cuota y
    `saldo_restante` el saldo tras aplicarlo. Defaults: `monto_aplicado = monto`,
    `saldo_restante = 0` ⇒ el comprobante QR (pago total) luce igual que hoy.
    """

    periodo_inicio: str
    vence_el: str
    monto: Decimal
    monto_aplicado: Decimal | None = None
    saldo_restante: Decimal = Decimal("0")


@dataclass(frozen=True)
class ComprobanteData:
    """Datos de negocio para renderizar un comprobante (C5), sin acoplar a la BD.

    El adaptador concreto convierte esto en un PDF. Es una estructura de dominio:
    sin SQLAlchemy ni FastAPI.

    Abonos (RF-ABO): `credito_aplicado` (crédito previo consumido) y
    `credito_generado` (saldo a favor generado por el sobrepago) van al pie del
    comprobante. Defaults 0 ⇒ el comprobante QR luce igual que hoy.

    Recibo (epic Recibo): `numero_recibo` (correlativo `REC-NNNNNN` por org) y
    `emisor` (branding "SnapCoding - LatinoSport") van a la cabecera del PDF. El
    constructor (`construir_comprobante_data`) los llena explícitamente; los defaults
    solo existen para no romper dataclass ordering ni constructores de tests.
    """

    numero: str
    org_nombre: str
    moneda: str
    deportista_nombre: str
    metodo: str
    fecha: datetime
    monto_total: Decimal
    cuotas: list[CuotaLinea] = field(default_factory=list)
    credito_aplicado: Decimal = Decimal("0")
    credito_generado: Decimal = Decimal("0")
    numero_recibo: str = "—"
    emisor: str = "SnapCoding - LatinoSport"
    # Disciplina de la inscripción cobrada (un pago aplica a cuotas de UNA
    # inscripción ⇒ una disciplina). None si no se pudo resolver.
    disciplina: str | None = None


@dataclass(frozen=True)
class KardexCuotaLinea:
    """Una fila del kardex: UNA cuota pagada, con su vencimiento y cuándo se pagó.

    Un pago que cubrió varios meses produce VARIAS filas (una por cuota), todas con el
    mismo recibo. Fechas ya formateadas como "5 junio 2026" (el constructor las arma);
    el adaptador PDF solo las pinta. `monto` = lo aplicado a ESA cuota (no el total del
    pago).
    """

    numero_recibo: str
    cuota: str  # MES en que vence la cuota, en mayúsculas, p.ej. "JULIO"
    vence: str  # vencimiento completo de la cuota, p.ej. "6 julio 2026"
    fecha_pago: str  # cuándo se pagó, p.ej. "2 julio 2026"
    metodo: str
    monto: Decimal


@dataclass(frozen=True)
class KardexData:
    """Datos para el KARDEX de pagos de un deportista (estado de cuenta imprimible).

    Consolidado de TODOS sus pagos confirmados, desglosado **una fila por cuota**
    (mes). Estructura de dominio (sin BD/HTTP); el adaptador la convierte en PDF.
    """

    org_nombre: str
    moneda: str
    deportista_nombre: str
    fecha_emision: datetime
    total_pagado: Decimal
    num_pagos: int
    filas: list[KardexCuotaLinea] = field(default_factory=list)
    emisor: str = "SnapCoding - LatinoSport"


@runtime_checkable
class ComprobanteService(Protocol):
    """Genera el comprobante PDF de un pago confirmado (C5)."""

    def render_pdf(self, data: ComprobanteData) -> bytes:
        """Renderiza el comprobante y devuelve el PDF en bytes.

        Debe ser determinista respecto a `data` (mismo pago ⇒ mismo comprobante);
        el llamador garantiza no emitir dos veces para el mismo pago.
        """
        ...

    def render_kardex_pdf(self, data: KardexData) -> bytes:
        """Renderiza el kardex de pagos de un deportista (estado de cuenta) en bytes."""
        ...


@runtime_checkable
class InvoiceProvider(Protocol):
    """Emite comprobantes/facturas para un pago."""

    def issue(self, *, payment_id: str) -> bytes:
        """Emite el comprobante y devuelve el documento (p.ej. PDF en bytes).

        TODO(epic-cobranza): implementar en el adaptador concreto. La emisión
        debe ser idempotente respecto al pago (no duplicar comprobantes).
        """
        ...
