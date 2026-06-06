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
    """

    numero: str
    org_nombre: str
    moneda: str
    alumno_nombre: str
    metodo: str
    fecha: datetime
    monto_total: Decimal
    cuotas: list[CuotaLinea] = field(default_factory=list)
    credito_aplicado: Decimal = Decimal("0")
    credito_generado: Decimal = Decimal("0")


@runtime_checkable
class ComprobanteService(Protocol):
    """Genera el comprobante PDF de un pago confirmado (C5)."""

    def render_pdf(self, data: ComprobanteData) -> bytes:
        """Renderiza el comprobante y devuelve el PDF en bytes.

        Debe ser determinista respecto a `data` (mismo pago ⇒ mismo comprobante);
        el llamador garantiza no emitir dos veces para el mismo pago.
        """
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
