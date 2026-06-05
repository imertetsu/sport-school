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
    """Una cuota cubierta por el pago, para el detalle del comprobante (C5)."""

    periodo_inicio: str
    vence_el: str
    monto: Decimal


@dataclass(frozen=True)
class ComprobanteData:
    """Datos de negocio para renderizar un comprobante (C5), sin acoplar a la BD.

    El adaptador concreto convierte esto en un PDF. Es una estructura de dominio:
    sin SQLAlchemy ni FastAPI.
    """

    numero: str
    org_nombre: str
    moneda: str
    alumno_nombre: str
    metodo: str
    fecha: datetime
    monto_total: Decimal
    cuotas: list[CuotaLinea] = field(default_factory=list)


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
