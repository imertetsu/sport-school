"""Schemas de Egresos (contrato C2).

Formas de request/response **espejo exacto** de C2; frontend-dev tipa contra
ellas. Dinero como `Decimal`; fechas como `date`. La regla de negocio `monto > 0`
y `categoria_gasto` no vacío se valida aquí (=> 422 en la API); el server es la
fuente de verdad (el frontend no es la única barrera).
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from pydantic import BaseModel, field_validator

# Métodos de pago aceptados. MISMOS literales que `pago.metodo` para que el panel
# desglose ingresos y egresos con el mismo vocabulario (CHECK ck_egreso_metodo).
METODOS_EGRESO: tuple[str, ...] = ("EFECTIVO", "QR")


# --------------------------------------------------------------------------- #
# Sub-objetos anidados
# --------------------------------------------------------------------------- #
class SucursalRefEgreso(BaseModel):
    """Sucursal embebida en un item de egreso (`{id, nombre}`) (C2)."""

    id: uuid.UUID
    nombre: str


# --------------------------------------------------------------------------- #
# Alta (POST /egresos)
# --------------------------------------------------------------------------- #
class EgresoCreate(BaseModel):
    """Body de `POST /egresos` (C2).

    `registrado_por` NO se acepta del cliente (lo fija el servidor con el usuario
    del token, auditoría RNF-03). `monto > 0` y `categoria_gasto` no vacío -> 422.
    `sucursal_id` opcional: si falta, el egreso es a nivel org (`sucursal: null`).
    """

    sucursal_id: uuid.UUID | None = None
    categoria_gasto: str
    monto: Decimal
    fecha: date
    # Default EFECTIVO: los clientes viejos que no envíen el campo siguen andando
    # y caen en el mismo supuesto que el backfill de 0027.
    metodo: str = "EFECTIVO"
    descripcion: str | None = None

    @field_validator("metodo")
    @classmethod
    def _metodo_valido(cls, v: str) -> str:
        v = (v or "").strip().upper()
        if v not in METODOS_EGRESO:
            raise ValueError(f"metodo debe ser uno de {', '.join(METODOS_EGRESO)}")
        return v

    @field_validator("categoria_gasto")
    @classmethod
    def _categoria_no_vacia(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("categoria_gasto no puede estar vacío")
        return v.strip()

    @field_validator("monto")
    @classmethod
    def _monto_positivo(cls, v: Decimal) -> Decimal:
        if v <= 0:
            raise ValueError("monto debe ser mayor que 0")
        return v

    @field_validator("descripcion")
    @classmethod
    def _descripcion_normalizada(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        return v or None


# --------------------------------------------------------------------------- #
# Listado (GET /egresos)
# --------------------------------------------------------------------------- #
class EgresoItem(BaseModel):
    """Item de `GET /egresos` y respuesta de `POST /egresos` (C2).

    `sucursal` es null si el egreso es a nivel org. `descripcion` y
    `registrado_por_nombre` pueden ser null.
    """

    id: uuid.UUID
    fecha: date
    categoria_gasto: str
    monto: Decimal
    metodo: str  # EFECTIVO | QR
    sucursal: SucursalRefEgreso | None = None
    descripcion: str | None = None
    registrado_por_nombre: str | None = None


class EgresosPage(BaseModel):
    """`GET /egresos` -> `{items, total, page, page_size, total_monto}` (C2).

    `total` = conteo de filas que matchean el filtro. `total_monto` = suma de
    `monto` de TODOS los egresos que matchean el filtro (no solo la página).
    """

    items: list[EgresoItem]
    total: int
    page: int
    page_size: int
    total_monto: Decimal


# --------------------------------------------------------------------------- #
# Resumen por categoría (GET /egresos/resumen) — opcional (C2)
# --------------------------------------------------------------------------- #
class ResumenCategoria(BaseModel):
    """Item de `GET /egresos/resumen` (C2): gasto agrupado por categoría."""

    categoria_gasto: str
    total: Decimal
