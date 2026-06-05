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
