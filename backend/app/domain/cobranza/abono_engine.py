"""Motor de abonos (pagos parciales) — dominio PURO sin I/O (C2, RF-ABO-04).

Distribuye un monto disponible (crédito previo + efectivo recibido) sobre los
saldos de cuotas ordenados FIFO: cada cuota recibe `min(restante, saldo)`; el
remanente final (sobrepago) queda aparte para convertirse en crédito.

NO importa SQLAlchemy, FastAPI ni adaptadores (import-linter lo verifica). El
servicio de aplicación (con I/O) traduce filas de BD a/desde estas estructuras y
aplica el estado destino por cuota (RF-ABO-05) — el motor solo reparte dinero.

Usa `Decimal` (nunca float) y no pierde centavos: la suma de aplicaciones más el
remanente es siempre igual al `monto_disponible` (acotado por Σ saldos).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal


@dataclass(frozen=True)
class ResultadoAbono:
    """Resultado puro de distribuir un abono FIFO sobre saldos de cuotas.

    - `aplicaciones[i]` = monto asignado a la cuota i (en el orden FIFO de entrada).
    - `remanente` = sobrepago tras cubrir todos los saldos (→ crédito).

    Invariante: `sum(aplicaciones) + remanente == min(monto_disponible, Σ saldos) +
    max(0, monto_disponible - Σ saldos)` = `monto_disponible` (cuando es ≥ 0).
    """

    aplicaciones: list[Decimal] = field(default_factory=list)
    remanente: Decimal = Decimal("0")


def distribuir_abono(
    monto_disponible: Decimal, saldos_cuotas_fifo: list[Decimal]
) -> ResultadoAbono:
    """Reparte `monto_disponible` sobre `saldos_cuotas_fifo` (ya en orden FIFO).

    Cada cuota recibe `min(restante, saldo)`; el dinero que sobra tras cubrir todos
    los saldos es el `remanente`. No muta la entrada. `monto_disponible` < 0 se trata
    como 0 (sin aplicaciones, sin remanente negativo).
    """
    restante = monto_disponible if monto_disponible > Decimal("0") else Decimal("0")
    aplicaciones: list[Decimal] = []
    for saldo in saldos_cuotas_fifo:
        saldo_pos = saldo if saldo > Decimal("0") else Decimal("0")
        aplicado = restante if restante < saldo_pos else saldo_pos
        aplicaciones.append(aplicado)
        restante -= aplicado
    return ResultadoAbono(aplicaciones=aplicaciones, remanente=restante)
