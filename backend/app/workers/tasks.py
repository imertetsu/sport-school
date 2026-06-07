"""Tasks Celery de cobranza (contrato C6).

`cobranza_diaria` (1×/día, idempotente):
1. Genera la siguiente cuota de cada inscripción ACTIVA cuyo período venció (motor C2).
2. Marca VENCIDO las PENDIENTE con `vence_el < hoy`.
3. Recordatorio PROXIMO_VENCIMIENTO N días antes de `vence_el` (WhatsApp + QR de cobro).
4. Recordatorio de MOROSIDAD para vencidas (WhatsApp + QR de cobro).

Idempotencia:
- (1) por `UNIQUE(inscripcion_id, periodo_inicio)` (no duplica cuotas).
- (2) por marca de estado (solo PENDIENTE -> VENCIDO; re-correr no cambia nada).
- (3)/(4) deduplican en `recordatorio_pago` por `UNIQUE(cuota_id, tipo, ciclo)`
  (ciclo = `vence_el` para próximo vencimiento, `YYYY-MM` para morosidad): re-correr
  el cron el mismo día/mes NO reenvía ni genera un segundo QR.

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
from app.models.cuota import Cuota
from app.models.organizacion import Organizacion
from app.services import horarios as horarios_svc
from app.services import recordatorio_deudores as deudores_svc
from app.services.deps import get_whatsapp_port
from app.services.generacion import generar_cuotas_org
from app.services.recordatorios import enviar_recordatorio_cuota
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


def _set_org(db, org_id: uuid.UUID) -> None:
    db.execute(text("SELECT set_config('app.current_org', :org, true)"), {"org": str(org_id)})


def _procesar_org(db, *, org_id: uuid.UUID, hoy: date) -> int:
    """Procesa una org (contexto ya fijado). Devuelve cuántas cuotas creó."""
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

    # 3) Recordatorio PROXIMO_VENCIMIENTO: PENDIENTE que vence en exactamente N días
    #    (`recordatorio_qr_dias_antes`). El envío adjunta un QR de cobro reconciliable
    #    y se deduplica en `recordatorio_pago` (cuota,tipo,ciclo): re-correr no reenvía.
    port = get_whatsapp_port()
    objetivo = hoy + timedelta(days=settings.recordatorio_qr_dias_antes)
    por_recordar = (
        db.execute(select(Cuota).where(Cuota.estado == "PENDIENTE", Cuota.vence_el == objetivo))
        .scalars()
        .all()
    )
    for cuota in por_recordar:
        enviar_recordatorio_cuota(db, cuota=cuota, tipo="PROXIMO_VENCIMIENTO", hoy=hoy, port=port)

    # 4) Recordatorio de MOROSIDAD para vencidas (máx. 1 por cuota por mes — dedup en
    #    `recordatorio_pago` con ciclo=YYYY-MM). También adjunta QR reconciliable.
    vencidas = db.execute(select(Cuota).where(Cuota.estado == "VENCIDO")).scalars().all()
    for cuota in vencidas:
        enviar_recordatorio_cuota(db, cuota=cuota, tipo="MOROSIDAD", hoy=hoy, port=port)

    return creadas


@celery_app.task(name="app.workers.tasks.cobranza_diaria")
def cobranza_diaria() -> dict[str, int]:
    """Cron diario idempotente de cobranza (C6). Itera todas las orgs."""
    hoy = datetime.now(UTC).date()
    db = SessionLocal()
    total_creadas = 0
    orgs_procesadas = 0
    try:
        # organizacion no tiene RLS -> se listan sin contexto. El cron PAUSA las
        # escuelas SUSPENDIDA (Epic Super Admin): solo se procesan las ACTIVA.
        org_ids = (
            db.execute(select(Organizacion.id).where(Organizacion.estado == "ACTIVA"))
            .scalars()
            .all()
        )
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
        # Pausa escuelas SUSPENDIDA (Epic Super Admin): solo orgs ACTIVA.
        org_ids = (
            db.execute(select(Organizacion.id).where(Organizacion.estado == "ACTIVA"))
            .scalars()
            .all()
        )
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
        # Pausa escuelas SUSPENDIDA (Epic Super Admin): solo orgs ACTIVA.
        org_ids = (
            db.execute(select(Organizacion.id).where(Organizacion.estado == "ACTIVA"))
            .scalars()
            .all()
        )
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


# --------------------------------------------------------------------------- #
# Recordatorio de deudores al entrenador (epic Recordatorio de deudores)
# --------------------------------------------------------------------------- #
@celery_app.task(name="app.workers.tasks.recordatorio_deudores_semanal")
def recordatorio_deudores_semanal() -> dict[str, int]:
    """Cron semanal (lunes 07:00 UTC): digest de deudores a cada entrenador (CONTRATO 5).

    Por cada org ACTIVA fija `app.current_org` (patrón `cobranza_diaria`) y llama a
    `enviar_digests_org` con `origen='CRON'`. Período = semana ISO (`%G-W%V`, p.ej.
    `2026-W23`): re-correr el cron la misma semana NO reenvía (INSERT idempotente
    `ON CONFLICT (entrenador_id, sucursal_id, periodo) DO NOTHING`). El servicio no
    commitea; el commit lo da esta task.
    """
    periodo = datetime.now(UTC).strftime("%G-W%V")
    db = SessionLocal()
    total_enviados = 0
    orgs_procesadas = 0
    port = get_whatsapp_port()
    try:
        # Pausa escuelas SUSPENDIDA (Epic Super Admin): solo orgs ACTIVA.
        org_ids = (
            db.execute(select(Organizacion.id).where(Organizacion.estado == "ACTIVA"))
            .scalars()
            .all()
        )
        for org_id in org_ids:
            _set_org(db, org_id)
            total_enviados += deudores_svc.enviar_digests_org(
                db, org_id=org_id, periodo=periodo, origen="CRON", port=port
            )
            orgs_procesadas += 1
        db.commit()
    except Exception:
        db.rollback()
        logger.exception("recordatorio_deudores_semanal falló")
        raise
    finally:
        db.close()

    logger.info(
        "recordatorio_deudores_semanal OK: orgs=%s enviados=%s",
        orgs_procesadas,
        total_enviados,
    )
    return {"orgs": orgs_procesadas, "enviados": total_enviados}
