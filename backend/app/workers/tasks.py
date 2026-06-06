"""Tasks Celery de cobranza (contrato C6).

`cobranza_diaria` (1×/día, idempotente):
1. Genera la siguiente cuota de cada inscripción ACTIVA cuyo período venció (motor C2).
2. Marca VENCIDO las PENDIENTE con `vence_el < hoy`.
3. Recordatorio N días antes de `vence_el` (NotificationService Noop).
4. Alerta de morosidad para vencidas (NotificationService Noop).

Idempotencia:
- (1) por `UNIQUE(inscripcion_id, periodo_inicio)` (no duplica cuotas).
- (2) por marca de estado (solo PENDIENTE -> VENCIDO; re-correr no cambia nada).
- (3)/(4) son Noop hoy; el adaptador real deberá deduplicar por (cuota, tipo, día).

El worker no tiene "request con org": itera TODAS las orgs y fija
`app.current_org` por org en su transacción (RLS), igual que el seed.
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import select, text, update

from app.core.config import settings
from app.core.db import SessionLocal
from app.models.alumno import Alumno
from app.models.cuota import Cuota
from app.models.inscripcion import Inscripcion
from app.models.organizacion import Organizacion
from app.services import horarios as horarios_svc
from app.services.deps import get_notification_service
from app.services.generacion import generar_cuotas_org
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)

# Días antes del vencimiento para el recordatorio (C6).
RECORDATORIO_DIAS_ANTES = 3


def _set_org(db, org_id: uuid.UUID) -> None:
    db.execute(text("SELECT set_config('app.current_org', :org, true)"), {"org": str(org_id)})


def _procesar_org(db, *, org_id: uuid.UUID, hoy: date) -> int:
    """Procesa una org (contexto ya fijado). Devuelve cuántas cuotas creó."""
    notifier = get_notification_service()

    # 1) Generación incremental idempotente.
    creadas = generar_cuotas_org(db, org_id=org_id, hoy=hoy)

    # 2) Marcar VENCIDO (idempotente). Abonos: también las PARCIAL con vence_el < hoy
    #    (precedencia de vencido sobre parcial, RF-ABO-05). Re-correr no cambia nada.
    db.execute(
        update(Cuota)
        .where(Cuota.estado.in_(("PENDIENTE", "PARCIAL")), Cuota.vence_el < hoy)
        .values(estado="VENCIDO")
    )
    db.flush()

    # 3) Recordatorio N días antes (Noop). PENDIENTE que vence en exactamente N días.
    objetivo = hoy + timedelta(days=RECORDATORIO_DIAS_ANTES)
    por_recordar = (
        db.execute(select(Cuota).where(Cuota.estado == "PENDIENTE", Cuota.vence_el == objetivo))
        .scalars()
        .all()
    )
    for cuota in por_recordar:
        alumno = _alumno_de_cuota(db, cuota)
        notifier.send(
            to=str(alumno.id) if alumno else str(cuota.id),
            template="recordatorio_cuota",
            variables={"cuota_id": str(cuota.id), "vence_el": cuota.vence_el.isoformat()},
        )

    # 4) Alerta de morosidad para vencidas (Noop).
    vencidas = db.execute(select(Cuota).where(Cuota.estado == "VENCIDO")).scalars().all()
    for cuota in vencidas:
        alumno = _alumno_de_cuota(db, cuota)
        notifier.send(
            to=str(alumno.id) if alumno else str(cuota.id),
            template="alerta_morosidad",
            variables={"cuota_id": str(cuota.id), "vence_el": cuota.vence_el.isoformat()},
        )

    return creadas


def _alumno_de_cuota(db, cuota: Cuota) -> Alumno | None:
    insc = db.execute(
        select(Inscripcion).where(Inscripcion.id == cuota.inscripcion_id)
    ).scalar_one_or_none()
    if insc is None:
        return None
    return db.execute(select(Alumno).where(Alumno.id == insc.alumno_id)).scalar_one_or_none()


@celery_app.task(name="app.workers.tasks.cobranza_diaria")
def cobranza_diaria() -> dict[str, int]:
    """Cron diario idempotente de cobranza (C6). Itera todas las orgs."""
    hoy = datetime.now(UTC).date()
    db = SessionLocal()
    total_creadas = 0
    orgs_procesadas = 0
    try:
        # organizacion no tiene RLS -> se listan sin contexto.
        org_ids = db.execute(select(Organizacion.id)).scalars().all()
        for org_id in org_ids:
            _set_org(db, org_id)
            total_creadas += _procesar_org(db, org_id=org_id, hoy=hoy)
            orgs_procesadas += 1
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("cobranza_diaria falló")
        raise
    finally:
        db.close()

    logger.info("cobranza_diaria OK: orgs=%s cuotas_creadas=%s", orgs_procesadas, total_creadas)
    return {"orgs": orgs_procesadas, "cuotas_creadas": total_creadas}


# --------------------------------------------------------------------------- #
# Programación de clases (C3) — generación de sesiones + recordatorio
# --------------------------------------------------------------------------- #
@celery_app.task(name="app.workers.tasks.generar_sesiones_programadas")
def generar_sesiones_programadas() -> dict[str, int]:
    """Cron 1×/día: genera sesiones de la ventana por cada horario activo (C3).

    Idempotente (reutiliza el get-or-create de Asistencia; UNIQUE de `sesion`).
    Itera TODAS las orgs fijando `app.current_org` por org (RLS), como cobranza.
    """
    hoy = datetime.now(UTC).date()
    db = SessionLocal()
    total_creadas = 0
    orgs_procesadas = 0
    try:
        org_ids = db.execute(select(Organizacion.id)).scalars().all()
        for org_id in org_ids:
            _set_org(db, org_id)
            total_creadas += horarios_svc.generar_sesiones_programadas(
                db, org_id, hoy=hoy, dias_ventana=settings.generar_sesiones_dias
            )
            orgs_procesadas += 1
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("generar_sesiones_programadas falló")
        raise
    finally:
        db.close()

    logger.info(
        "generar_sesiones_programadas OK: orgs=%s sesiones_creadas=%s",
        orgs_procesadas,
        total_creadas,
    )
    return {"orgs": orgs_procesadas, "sesiones_creadas": total_creadas}


@celery_app.task(name="app.workers.tasks.recordatorios_clase")
def recordatorios_clase() -> dict[str, int]:
    """Cron cada hora: recordatorio N horas antes de cada clase (C3).

    Idempotente vía `sesion.recordatorio_enviado_en` (no reenvía). Itera TODAS las
    orgs fijando `app.current_org` por org (RLS). Notifica (Noop) a los tutores.
    """
    ahora = datetime.now(UTC)
    db = SessionLocal()
    total_notificadas = 0
    orgs_procesadas = 0
    try:
        org_ids = db.execute(select(Organizacion.id)).scalars().all()
        for org_id in org_ids:
            _set_org(db, org_id)
            total_notificadas += horarios_svc.enviar_recordatorios_clase(
                db, org_id, ahora=ahora, horas=settings.recordatorio_clase_horas
            )
            orgs_procesadas += 1
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("recordatorios_clase falló")
        raise
    finally:
        db.close()

    logger.info(
        "recordatorios_clase OK: orgs=%s notificadas=%s",
        orgs_procesadas,
        total_notificadas,
    )
    return {"orgs": orgs_procesadas, "notificadas": total_notificadas}
