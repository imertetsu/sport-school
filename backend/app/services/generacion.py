"""Servicio de generación de cuotas (C2/C4/C6) — orquesta el motor puro + BD.

Idempotente: respeta `UNIQUE(inscripcion_id, periodo_inicio)`. Genera la primera
cuota de cada inscripción ACTIVA sin cuotas, y la siguiente cuando la última ya
venció. Re-correr no duplica (la unicidad lo garantiza; además chequeamos antes).

Corre SIEMPRE con `app.current_org` ya fijado por el llamador (RLS): trabaja solo
sobre la org del contexto.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.cobranza.cuota_engine import (
    InscripcionConfig,
    OrgConfig,
    PeriodoCuota,
    primera_cuota,
    siguiente_cuota,
)
from app.models.cuota import Cuota
from app.models.inscripcion import Inscripcion
from app.models.organizacion import Organizacion


def _org_config(org: Organizacion) -> OrgConfig:
    return OrgConfig(
        modo_cobro_default=org.modo_cobro_default,
        dia_corte_fijo=org.dia_corte_fijo,
        prorratea_primer_periodo=org.prorratea_primer_periodo,
    )


def _insc_config(insc: Inscripcion) -> InscripcionConfig:
    return InscripcionConfig(
        fecha_inscripcion=insc.fecha_inscripcion,
        monto_mensual=insc.monto_mensual,
        modo_cobro=insc.modo_cobro,
        dia_corte=insc.dia_corte,
    )


def _insertar_si_no_existe(
    db: Session, *, org_id: uuid.UUID, inscripcion_id: uuid.UUID, periodo: PeriodoCuota
) -> bool:
    """Inserta la cuota si no existe ya (idempotencia por periodo_inicio). Devuelve
    True si la creó."""
    existe = db.execute(
        select(Cuota.id).where(
            Cuota.inscripcion_id == inscripcion_id,
            Cuota.periodo_inicio == periodo.periodo_inicio,
        )
    ).first()
    if existe is not None:
        return False
    db.add(
        Cuota(
            org_id=org_id,
            inscripcion_id=inscripcion_id,
            periodo_inicio=periodo.periodo_inicio,
            periodo_fin=periodo.periodo_fin,
            vence_el=periodo.vence_el,
            monto=periodo.monto,
            estado="PENDIENTE",
            es_prorrateo=periodo.es_prorrateo,
        )
    )
    db.flush()
    return True


def generar_cuotas_org(db: Session, *, org_id: uuid.UUID, hoy: date | None = None) -> int:
    """Genera primeras/siguientes cuotas vencidas de la org del contexto.

    Devuelve cuántas cuotas se crearon. Idempotente.
    """
    hoy = hoy or date.today()

    org = db.execute(select(Organizacion).where(Organizacion.id == org_id)).scalar_one_or_none()
    if org is None:
        return 0
    org_cfg = _org_config(org)

    inscripciones = (
        db.execute(select(Inscripcion).where(Inscripcion.estado == "ACTIVA")).scalars().all()
    )

    creadas = 0
    for insc in inscripciones:
        insc_cfg = _insc_config(insc)

        ultima = (
            db.execute(
                select(Cuota)
                .where(Cuota.inscripcion_id == insc.id)
                .order_by(Cuota.periodo_inicio.desc())
            )
            .scalars()
            .first()
        )

        if ultima is None:
            # Primera cuota.
            periodo = primera_cuota(insc_cfg, org_cfg)
            if _insertar_si_no_existe(db, org_id=org_id, inscripcion_id=insc.id, periodo=periodo):
                creadas += 1
            continue

        # Genera tantas "siguientes" como períodos hayan vencido hasta hoy
        # (cota de seguridad para no entrar en bucle si los datos son raros).
        ultimo_inicio = ultima.periodo_inicio
        ultimo_vence = ultima.vence_el
        for _ in range(120):  # máx 10 años de catch-up
            if ultimo_vence > hoy:
                break
            periodo = siguiente_cuota(
                insc_cfg,
                org_cfg,
                ultimo_periodo_inicio=ultimo_inicio,
                ultimo_vence_el=ultimo_vence,
            )
            if periodo.periodo_inicio == ultimo_inicio:
                break  # no avanza -> evita bucle infinito
            if _insertar_si_no_existe(db, org_id=org_id, inscripcion_id=insc.id, periodo=periodo):
                creadas += 1
            ultimo_inicio = periodo.periodo_inicio
            ultimo_vence = periodo.vence_el

    return creadas


# --------------------------------------------------------------------------- #
# Alta retroactiva: rellenar cuotas desde la fecha de inscripción
# --------------------------------------------------------------------------- #
def _periodos_hasta_corriente(
    insc_cfg: InscripcionConfig, org_cfg: OrgConfig, hoy: date
) -> list[PeriodoCuota]:
    """Secuencia PURA de períodos: de la primera cuota a la corriente (la que vence en
    el futuro). Sin BD → testeable en aislamiento. Genera "siguientes" mientras la
    última ya venció; corta con una cota de seguridad y si el motor no avanza.
    """
    periodos = [primera_cuota(insc_cfg, org_cfg)]
    for _ in range(600):  # cota de seguridad (~50 años de catch-up)
        ultimo = periodos[-1]
        if ultimo.vence_el > hoy:
            break
        siguiente = siguiente_cuota(
            insc_cfg,
            org_cfg,
            ultimo_periodo_inicio=ultimo.periodo_inicio,
            ultimo_vence_el=ultimo.vence_el,
        )
        if siguiente.periodo_inicio == ultimo.periodo_inicio:
            break  # no avanza -> evita bucle infinito
        periodos.append(siguiente)
    return periodos


def _generar_cadena_completa(
    db: Session,
    *,
    org_id: uuid.UUID,
    insc: Inscripcion,
    org_cfg: OrgConfig,
    hoy: date,
) -> int:
    """Genera TODA la cadena de cuotas de una inscripción: de la primera (según su
    `fecha_inscripcion`) hasta la corriente (la que vence en el futuro).

    Idempotente por `UNIQUE(inscripcion_id, periodo_inicio)`: salta las que ya existen
    y **no reescribe** su monto. A diferencia de `generar_cuotas_org` (que avanza desde
    la ÚLTIMA cuota), esto RELLENA desde el inicio — para altas retroactivas.
    """
    creadas = 0
    for periodo in _periodos_hasta_corriente(_insc_config(insc), org_cfg, hoy):
        if _insertar_si_no_existe(db, org_id=org_id, inscripcion_id=insc.id, periodo=periodo):
            creadas += 1
    return creadas


def generar_cuotas_historicas(
    db: Session, *, inscripcion_id: uuid.UUID, hoy: date | None = None
) -> int:
    """Rellena las cuotas mensuales de UNA inscripción desde su `fecha_inscripcion`
    hasta el período corriente (alta retroactiva de un alumno inscrito en el pasado).

    Idempotente (no duplica ni reescribe existentes). Solo inscripciones ACTIVA. Corre
    bajo el `app.current_org` fijado por el llamador (RLS). Devuelve cuántas creó.
    """
    hoy = hoy or date.today()
    insc = db.execute(
        select(Inscripcion).where(Inscripcion.id == inscripcion_id)
    ).scalar_one_or_none()
    if insc is None or insc.estado != "ACTIVA":
        return 0
    org = db.execute(
        select(Organizacion).where(Organizacion.id == insc.org_id)
    ).scalar_one_or_none()
    if org is None:
        return 0
    return _generar_cadena_completa(
        db, org_id=insc.org_id, insc=insc, org_cfg=_org_config(org), hoy=hoy
    )


def reajustar_monto_cuotas_futuras(
    db: Session, *, inscripcion_id: uuid.UUID, nuevo_monto: Decimal, hoy: date | None = None
) -> int:
    """Aplica `nuevo_monto` a las cuotas de la inscripción del período corriente en
    adelante que aún NO tienen pago aplicado.

    Regla "el cambio de cuota aplica hacia adelante": solo toca cuotas
    PENDIENTE/VENCIDO con `monto_pagado == 0` y `vence_el >= hoy`. NO toca pagadas,
    parciales ni períodos ya vencidos (conservan el monto con el que se cobraron/vencen).
    Devuelve cuántas cuotas actualizó.
    """
    hoy = hoy or date.today()
    monto = nuevo_monto.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    cuotas = (
        db.execute(
            select(Cuota).where(
                Cuota.inscripcion_id == inscripcion_id,
                Cuota.monto_pagado == 0,
                Cuota.vence_el >= hoy,
                Cuota.estado.in_(("PENDIENTE", "VENCIDO")),
            )
        )
        .scalars()
        .all()
    )
    actualizadas = 0
    for cuota in cuotas:
        if cuota.monto != monto:
            cuota.monto = monto
            actualizadas += 1
    if actualizadas:
        db.flush()
    return actualizadas
