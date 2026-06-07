"""Digest de deudores al entrenador por WhatsApp (epic Recordatorio de deudores).

Para cada entrenador ACTIVO y cada sucursal donde trabaja, arma la lista de
**deudores** (deportista con ≥1 cuota `VENCIDO` impaga) de esa sucursal y se la envía por
WhatsApp: una plantilla pre-aprobada `resumen_deudores` con el resumen + un mensaje de
texto libre con el detalle multilínea.

Definición de deudor (CONTRATO 2): join `cuota → inscripcion → deportista`, `cuota.estado
= 'VENCIDO'`, `deportista.sucursal_id = :sucursal`, saldo = `SUM(monto - monto_pagado)`,
agrupado por deportista. NO se reimplementa la lógica de vencimiento: el cron
`cobranza_diaria` ya marca `VENCIDO`.

**Idempotencia (CONTRATO 1/5):** una fila `recordatorio_deudores` por
`(entrenador_id, sucursal_id, periodo)` (UNIQUE). El INSERT usa
`ON CONFLICT DO NOTHING` (mismo patrón que `recordatorio_pago`): re-correr el cron el
mismo período ISO NO reenvía. Solo se llama al puerto cuando el INSERT efectivamente
inserta (no había fila previa).

Casos borde (sin llamar al puerto):
- Entrenador sin teléfono → fila `FALLIDO`, `destino=NULL`.
- Sucursal sin deudores → fila `SIN_DEUDORES`.
- Entrenador sin sucursales asignadas → nada.

Corre bajo el `app.current_org` ya fijado por el caller (RLS); **NO commitea** (sigue
la tx del caller: el endpoint o la task del cron).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import NamedTuple

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.domain.ports.whatsapp import (
    WhatsAppPort,
    WhatsAppTemplateMessage,
    WhatsAppTextMessage,
)
from app.models.cuota import Cuota
from app.models.deportista import Deportista
from app.models.entrenador import Entrenador
from app.models.entrenador_sucursal import EntrenadorSucursal
from app.models.inscripcion import Inscripcion
from app.models.recordatorio_deudores import RecordatorioDeudores
from app.models.sucursal import Sucursal
from app.models.usuario import Usuario

logger = logging.getLogger(__name__)

# Plantilla pre-aprobada (RNF-07) del resumen de deudores.
_TEMPLATE_RESUMEN = "resumen_deudores"
_LANG_CODE = "es"


@dataclass(frozen=True)
class Deudor:
    """Un deudor (deportista con ≥1 cuota vencida) de una sucursal."""

    deportista_id: uuid.UUID
    nombre: str
    num_cuotas_vencidas: int
    monto_adeudado: Decimal


class SucursalDigestResult(NamedTuple):
    """Resultado del digest de UNA sucursal de un entrenador.

    `enviado_ahora` distingue un envío real en ESTA llamada (fila recién insertada,
    estado `ENVIADO`) de un período ya procesado (idempotencia: `ON CONFLICT`). El
    conteo `enviados` se basa en `enviado_ahora`, no en `estado`: re-correr el mismo
    período NO vuelve a contar (ni a llamar al puerto).
    """

    sucursal_id: uuid.UUID
    sucursal_nombre: str
    num_deudores: int
    monto_total: Decimal
    estado: str  # ENVIADO | FALLIDO | SIN_DEUDORES
    enviado_ahora: bool = False


def _nombre_completo(ap_paterno: str | None, ap_materno: str | None, nombres: str) -> str:
    """`ap_paterno ap_materno nombres` (helper compartido con `recordatorios.py`)."""
    partes = [ap_paterno, ap_materno, nombres]
    return " ".join(p for p in partes if p).strip() or nombres


def deudores_de_sucursal(db: Session, *, sucursal_id: uuid.UUID) -> list[Deudor]:
    """Deudores de una sucursal (CONTRATO 2), ordenados por monto adeudado desc.

    Corre bajo el `app.current_org` del caller (RLS): **sin** `WHERE org_id`. Un
    deudor = deportista con ≥1 `cuota.estado='VENCIDO'`; saldo = `SUM(monto -
    monto_pagado)` (NO `monto`); `num_cuotas_vencidas` = `COUNT(cuota)`.
    """
    monto_adeudado = func.sum(Cuota.monto - Cuota.monto_pagado)
    num_cuotas = func.count(Cuota.id)
    stmt = (
        select(
            Deportista.id,
            Deportista.ap_paterno,
            Deportista.ap_materno,
            Deportista.nombres,
            num_cuotas.label("num_cuotas_vencidas"),
            monto_adeudado.label("monto_adeudado"),
        )
        .select_from(Cuota)
        .join(Inscripcion, Inscripcion.id == Cuota.inscripcion_id)
        .join(Deportista, Deportista.id == Inscripcion.deportista_id)
        .where(Cuota.estado == "VENCIDO", Deportista.sucursal_id == sucursal_id)
        .group_by(Deportista.id, Deportista.ap_paterno, Deportista.ap_materno, Deportista.nombres)
        .order_by(monto_adeudado.desc())
    )
    deudores: list[Deudor] = []
    for row in db.execute(stmt).all():
        deudores.append(
            Deudor(
                deportista_id=row.id,
                nombre=_nombre_completo(row.ap_paterno, row.ap_materno, row.nombres),
                num_cuotas_vencidas=int(row.num_cuotas_vencidas),
                monto_adeudado=Decimal(row.monto_adeudado),
            )
        )
    return deudores


def _detalle_multilinea(deudores: list[Deudor]) -> str:
    """Texto libre con el detalle de morosos (un deudor por línea)."""
    return "\n".join(
        f"- {d.nombre}: {d.num_cuotas_vencidas} cuotas, Bs {d.monto_adeudado:.2f}" for d in deudores
    )


def _insert_idempotente(
    db: Session,
    *,
    org_id: uuid.UUID,
    entrenador_id: uuid.UUID,
    sucursal_id: uuid.UUID,
    periodo: str,
    origen: str,
    destino: str | None,
    num_deudores: int,
    monto_total: Decimal,
    estado: str,
) -> uuid.UUID | None:
    """INSERT ON CONFLICT DO NOTHING en `recordatorio_deudores` (patrón idempotente).

    Devuelve el `id` insertado, o `None` si ya existía la fila
    `(entrenador_id, sucursal_id, periodo)`. Mismo enfoque que `recordatorio_pago`.
    """
    stmt = (
        pg_insert(RecordatorioDeudores)
        .values(
            org_id=org_id,
            entrenador_id=entrenador_id,
            sucursal_id=sucursal_id,
            periodo=periodo,
            origen=origen,
            canal="WHATSAPP",
            destino=destino,
            num_deudores=num_deudores,
            monto_total=monto_total,
            estado=estado,
        )
        .on_conflict_do_nothing(index_elements=["entrenador_id", "sucursal_id", "periodo"])
        .returning(RecordatorioDeudores.id)
    )
    inserted = db.execute(stmt).scalar_one_or_none()
    db.flush()
    return inserted


def enviar_digest_sucursal(
    db: Session,
    *,
    org_id: uuid.UUID,
    entrenador: Entrenador,
    sucursal_id: uuid.UUID,
    sucursal_nombre: str,
    periodo: str,
    origen: str,
    port: WhatsAppPort,
) -> SucursalDigestResult:
    """Envía (idempotentemente) el digest de UNA sucursal a un entrenador.

    Flujo:
    1. Consulta los deudores de la sucursal (CONTRATO 2).
    2. Calcula `estado` de negocio: sin teléfono → `FALLIDO`; sin deudores →
       `SIN_DEUDORES`; con deudores y teléfono → `ENVIADO`.
    3. INSERT idempotente de la fila. Ya existía (mismo período) ⇒ NO reenvía.
    4. Solo si se insertó (era nuevo) y estado=`ENVIADO`, llama al puerto: plantilla
       `resumen_deudores` + `send_text` con el detalle. En la MISMA tx del caller (no
       commitea aquí).
    """
    telefono = entrenador.telefono or None
    deudores = deudores_de_sucursal(db, sucursal_id=sucursal_id)
    num_deudores = len(deudores)
    monto_total = sum((d.monto_adeudado for d in deudores), Decimal("0"))

    if telefono is None:
        estado = "FALLIDO"
        destino: str | None = None
    elif num_deudores == 0:
        estado = "SIN_DEUDORES"
        destino = telefono
    else:
        estado = "ENVIADO"
        destino = telefono

    inserted_id = _insert_idempotente(
        db,
        org_id=org_id,
        entrenador_id=entrenador.id,
        sucursal_id=sucursal_id,
        periodo=periodo,
        origen=origen,
        destino=destino,
        num_deudores=num_deudores,
        monto_total=monto_total,
        estado=estado,
    )

    # Ya existía (mismo período) o no hay nada que enviar (sin teléfono / sin
    # deudores): no se llama al puerto. La fila queda auditada igual (idempotente).
    if inserted_id is None or estado != "ENVIADO":
        return SucursalDigestResult(
            sucursal_id=sucursal_id,
            sucursal_nombre=sucursal_nombre,
            num_deudores=num_deudores,
            monto_total=monto_total,
            estado=estado,
        )

    # `estado == "ENVIADO"` ⇒ había teléfono y deudores (rama de arriba). Lo afirmamos
    # para que el tipo de `telefono` quede acotado a `str` en las llamadas al puerto.
    assert telefono is not None

    # 2 mensajes (CONTRATO 3): plantilla pre-aprobada + detalle como texto libre.
    plantilla = WhatsAppTemplateMessage(
        to=telefono,
        template_name=_TEMPLATE_RESUMEN,
        lang_code=_LANG_CODE,
        body_params=[
            entrenador.nombres,
            sucursal_nombre,
            str(num_deudores),
            f"Bs {monto_total:.2f}",
        ],
        header_image=None,
    )
    res_plantilla = port.send_template(plantilla)
    res_detalle = port.send_text(
        WhatsAppTextMessage(to=telefono, body=_detalle_multilinea(deudores))
    )

    fila = db.get(RecordatorioDeudores, inserted_id)
    enviado_ahora = True
    if fila is not None:
        if res_plantilla.ok:
            fila.provider_message_id = res_plantilla.provider_message_id
        else:
            # El envío falló: queda registrado como FALLIDO (no se pierde el intento).
            fila.estado = "FALLIDO"
            estado = "FALLIDO"
            enviado_ahora = False
            logger.warning(
                "digest deudores ent=%s suc=%s envío falló: %s",
                entrenador.id,
                sucursal_id,
                res_plantilla.error or res_detalle.error,
            )
        db.flush()

    return SucursalDigestResult(
        sucursal_id=sucursal_id,
        sucursal_nombre=sucursal_nombre,
        num_deudores=num_deudores,
        monto_total=monto_total,
        estado=estado,
        enviado_ahora=enviado_ahora,
    )


def enviar_digest_entrenador(
    db: Session,
    *,
    org_id: uuid.UUID,
    entrenador: Entrenador,
    periodo: str,
    origen: str,
    port: WhatsAppPort,
) -> list[SucursalDigestResult]:
    """Envía el digest de un entrenador para TODAS sus sucursales asignadas.

    Itera las sucursales del entrenador (join `entrenador_sucursal ⨝ sucursal`, bajo
    RLS) y delega cada una en `enviar_digest_sucursal`. Sin sucursales ⇒ lista vacía.
    """
    sucursales = db.execute(
        select(EntrenadorSucursal.sucursal_id, Sucursal.nombre)
        .join(Sucursal, Sucursal.id == EntrenadorSucursal.sucursal_id)
        .where(EntrenadorSucursal.entrenador_id == entrenador.id)
        .order_by(Sucursal.nombre)
    ).all()

    resultados: list[SucursalDigestResult] = []
    for sucursal_id, sucursal_nombre in sucursales:
        resultados.append(
            enviar_digest_sucursal(
                db,
                org_id=org_id,
                entrenador=entrenador,
                sucursal_id=sucursal_id,
                sucursal_nombre=sucursal_nombre,
                periodo=periodo,
                origen=origen,
                port=port,
            )
        )
    return resultados


def enviar_digests_org(
    db: Session,
    *,
    org_id: uuid.UUID,
    periodo: str,
    origen: str,
    port: WhatsAppPort,
) -> int:
    """Envía el digest a TODOS los entrenadores ACTIVOS de la org (CONTRATO 5).

    Itera los entrenadores cuyo `usuario.activo=true` (excluye dados de baja) y, por
    cada uno, su digest en todas sus sucursales asignadas. Devuelve cuántos digests se
    enviaron **en esta llamada** (`enviado_ahora`): re-correr el mismo período no
    vuelve a contar (idempotente). Corre bajo el `app.current_org` ya fijado por el
    caller (RLS); **NO commitea** (lo hace la task del cron).
    """
    entrenadores = (
        db.execute(
            select(Entrenador)
            .join(Usuario, Usuario.id == Entrenador.usuario_id)
            .where(Usuario.activo.is_(True))
            .order_by(Entrenador.nombres)
        )
        .scalars()
        .all()
    )

    enviados = 0
    for entrenador in entrenadores:
        resultados = enviar_digest_entrenador(
            db,
            org_id=org_id,
            entrenador=entrenador,
            periodo=periodo,
            origen=origen,
            port=port,
        )
        enviados += sum(1 for r in resultados if r.enviado_ahora)
    return enviados
