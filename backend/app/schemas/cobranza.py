"""Schemas de Cobranza (contrato C4).

Formas de request/response **espejo exacto** de C4; frontend-dev tipa contra
ellas. Dinero como `Decimal`; fechas como `date`/`datetime`.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


# --------------------------------------------------------------------------- #
# Generación
# --------------------------------------------------------------------------- #
class GenerarOut(BaseModel):
    """`POST /cobranza/generar` -> `{creadas:n}`."""

    creadas: int


# --------------------------------------------------------------------------- #
# Cuotas (lista paginada)
# --------------------------------------------------------------------------- #
class DeportistaRef(BaseModel):
    id: uuid.UUID
    nombre_completo: str


class SucursalNombre(BaseModel):
    nombre: str


class CategoriaNombre(BaseModel):
    nombre: str


class CuotaItem(BaseModel):
    """Item de `GET /cobranza/cuotas` (C4).

    Abonos: `monto_pagado` (acumulado aplicado) y `saldo` (= monto - monto_pagado).
    `estado` puede ser `PARCIAL`.
    """

    id: uuid.UUID
    deportista: DeportistaRef
    sucursal: SucursalNombre | None = None
    categoria: CategoriaNombre | None = None
    periodo_inicio: date
    vence_el: date
    monto: Decimal
    monto_pagado: Decimal = Decimal("0")
    saldo: Decimal = Decimal("0")
    estado: str
    ultimo_metodo: str | None = None


class CuotasPage(BaseModel):
    """`GET /cobranza/cuotas` -> `{items, total, page, page_size}` (C4)."""

    items: list[CuotaItem]
    total: int
    page: int
    page_size: int


class CuotaMontoIn(BaseModel):
    """`PATCH /cobranza/cuotas/{id}` -> nuevo monto de una cuota SIN pago.

    Permite corregir la tarifa de un mes puntual (p. ej. la cuota subió a mitad de
    año y las cuotas viejas quedaron con el monto inicial).
    """

    monto: Decimal = Field(..., gt=0)


class CuotaMontoOut(BaseModel):
    """Respuesta del PATCH de monto: refleja el estado de la cuota tras el cambio."""

    id: uuid.UUID
    monto: Decimal
    monto_pagado: Decimal
    saldo: Decimal
    estado: str


class EnviarComprobanteOut(BaseModel):
    """`POST /cobranza/pagos/{id}/enviar-whatsapp` -> resultado del envío.

    `motivo` ∈ {ok, sin_deportista, sin_telefono, sin_whatsapp, error_envio}. El front gatea
    antes por el estado de la sesión (CONECTADA); estos motivos cubren los fallos del envío
    en sí. `detalle` trae el error crudo del gateway (diagnóstico).
    """

    enviado: bool
    motivo: str
    provider_message_id: str | None = None
    detalle: str | None = None


# --------------------------------------------------------------------------- #
# Panel (KPIs + morosidad)
# --------------------------------------------------------------------------- #
class IngresosMes(BaseModel):
    # `monto` = total del mes; `efectivo` + `qr` = desglose por método de cobro.
    monto: Decimal
    efectivo: Decimal = Decimal("0")
    qr: Decimal = Decimal("0")


class DeportistasActivos(BaseModel):
    count: int
    sucursales: int
    disciplinas: int


class CuotasAgg(BaseModel):
    count: int
    monto: Decimal


class MorosidadItem(BaseModel):
    deportista_id: uuid.UUID
    nombre_completo: str
    categoria: str | None = None
    monto: Decimal
    dias_mora: int
    # Desglose para el recordatorio: meses vencidos (MAYÚSCULAS, cronológico) y la
    # fecha de vencimiento más antigua.
    meses: list[str] = Field(default_factory=list)
    vence_mas_antiguo: date | None = None


class PanelOut(BaseModel):
    """`GET /cobranza/panel` (C4).

    Abonos: `cuotas_pendientes`/`cuotas_vencidas` suman **saldos** (no montos
    nominales); morosidad por saldo. `credito_total` = Σ `credito.saldo` de la org.
    """

    ingresos_mes: IngresosMes
    deportistas_activos: DeportistasActivos
    cuotas_pendientes: CuotasAgg
    cuotas_vencidas: CuotasAgg
    morosidad: list[MorosidadItem]
    credito_total: Decimal = Decimal("0")


# --------------------------------------------------------------------------- #
# Pagos
# --------------------------------------------------------------------------- #
class PagoEfectivoIn(BaseModel):
    """`POST /cobranza/pagos/efectivo` — registro de pago MANUAL (C3 + abonos).

    `monto_recibido` opcional (efectivo de caja). `None` ⇒ paga el total (Σ saldos).
    Si se envía debe ser `> 0`; un excedente sobre Σ saldos queda como crédito.

    `metodo` = cómo pagó el tutor a mano: `EFECTIVO` (default) o `QR` (transferencia).
    `fecha_pago` = fecha real del pago (permite cargar meses viejos con su fecha); `None`
    ⇒ hoy. Afecta a "Ingresos del mes"/reportes, que agrupan por `pagado_en`.
    """

    cuota_ids: list[uuid.UUID] = Field(..., min_length=1)
    monto_recibido: Decimal | None = Field(default=None, gt=0)
    metodo: Literal["EFECTIVO", "QR"] = "EFECTIVO"
    fecha_pago: date | None = None


class PagoQrIn(BaseModel):
    """`POST /cobranza/pagos/qr` (C3)."""

    cuota_ids: list[uuid.UUID] = Field(..., min_length=1)


class CuotaAplicada(BaseModel):
    """Detalle por cuota de un pago efectivo con abono (RF-ABO)."""

    cuota_id: uuid.UUID
    monto_aplicado: Decimal
    saldo_restante: Decimal
    estado: str


class PagoOut(BaseModel):
    """Polling `GET /cobranza/pagos/{id}` (C3) + respuesta de pago efectivo (abonos).

    `monto` = efectivo de caja. `credito_aplicado` = crédito previo consumido;
    `credito_generado` = saldo a favor generado por el sobrepago. `cuotas_aplicadas`
    detalla qué recibió cada cuota. Defaults `0`/`[]` ⇒ el polling QR no se rompe.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    estado: str
    metodo: str
    monto: Decimal
    comprobante_url: str | None = None
    numero_recibo: str | None = None
    credito_aplicado: Decimal = Decimal("0")
    credito_generado: Decimal = Decimal("0")
    cuotas_aplicadas: list[CuotaAplicada] = Field(default_factory=list)


class QrOut(BaseModel):
    """Respuesta de `POST /cobranza/pagos/qr` (C3): QR + monto esperado."""

    pago_id: uuid.UUID
    estado: str
    monto: Decimal
    qr_ref: str
    qr_payload: str
    qr_png_data_url: str


class WebhookIn(BaseModel):
    """Body de `POST /webhooks/openbcb` (C3)."""

    transaccion_id: str
    referencia: str
    monto: Decimal


# --------------------------------------------------------------------------- #
# Anulación de pago + lista de pagos (epic anular-pago, C4/C5)
# --------------------------------------------------------------------------- #
class AnularPagoIn(BaseModel):
    """Body de `POST /cobranza/pagos/{pago_id}/anular`. Motivo obligatorio."""

    motivo: str = Field(..., min_length=1)


class CuotaRevertida(BaseModel):
    """Cuota cuyo abono se deshizo al anular: saldo y estado recomputado."""

    cuota_id: uuid.UUID
    saldo_restante: Decimal
    estado: str


class PagoAnuladoOut(BaseModel):
    """Respuesta de `POST /cobranza/pagos/{pago_id}/anular`.

    `credito_revertido` = crédito que la anulación deshizo (lo que el pago generó
    menos lo que consumió). `cuotas_revertidas` lista cada cuota vuelta a cobrable.
    """

    id: uuid.UUID
    estado: str
    motivo_anulacion: str
    anulado_en: datetime
    credito_revertido: Decimal
    cuotas_revertidas: list[CuotaRevertida]


class CuotaCubierta(BaseModel):
    """Cuota que un pago cubrió (para el historial por deportista): su período, la fecha
    en que vencía y el monto aplicado a ESA cuota. Permite mostrar una fila por cuota
    (mes) con "qué mes se pagó, cuándo vencía y cuánto"."""

    periodo_inicio: date
    vence_el: date
    monto_aplicado: Decimal


class PagoListItem(BaseModel):
    """Item de `GET /cobranza/pagos` (lista buscable, punto de acceso a "Anular").

    `anulable = (registrado_por is not None and estado == 'CONFIRMADO')`: solo los pagos
    registrados A MANO (efectivo o QR/transferencia) son anulables; el QR automático por
    webhook (sin `registrado_por`) no lo es. `fecha` = `pagado_en` (fecha real del cobro,
    editable al registrar), con fallback a `created_at`.
    `deportista_nombre` va en MAYÚSCULAS (datos de deportista ya almacenados así).
    `cuotas` = las cuotas que este pago cubrió (con su vencimiento), para el historial
    por deportista.
    """

    id: uuid.UUID
    fecha: datetime
    metodo: str
    estado: str
    monto: Decimal
    deportista_nombre: str | None = None
    sucursal_nombre: str | None = None
    numero_recibo: str | None = None
    anulable: bool
    motivo_anulacion: str | None = None
    anulado_en: datetime | None = None
    cuotas: list[CuotaCubierta] = Field(default_factory=list)


class PagosListOut(BaseModel):
    """`GET /cobranza/pagos` -> `{items, total, page, page_size}`."""

    items: list[PagoListItem]
    total: int
    page: int
    page_size: int


# --------------------------------------------------------------------------- #
# Recordatorios WhatsApp (epic WhatsApp Cobro)
# --------------------------------------------------------------------------- #
class RecordatorioIn(BaseModel):
    """Body opcional de `POST /cobranza/cuotas/{cuota_id}/recordatorio`.

    `forzar=True` reenvía aunque ya exista un recordatorio de ese tipo/ciclo.
    """

    forzar: bool = False


class RecordatorioOut(BaseModel):
    """Respuesta de `POST /cobranza/cuotas/{cuota_id}/recordatorio`.

    `motivo` ∈ {"ok", "ya_enviado", "sin_telefono", "error_envio"}.
    """

    enviado: bool
    cuota_id: uuid.UUID
    provider_message_id: str | None = None
    motivo: str | None = None
