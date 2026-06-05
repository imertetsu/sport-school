"""Tasks Celery (esqueleto).

Placeholder del cron diario. SIN lógica de cuotas todavía: solo deja traza. Cuando
se implemente (epic de cobranza) debe ser **idempotente**: re-ejecutar no duplica
cuotas (SRS §4.4).
"""

from __future__ import annotations

import logging

from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="app.workers.tasks.cron_diario_cuotas")
def cron_diario_cuotas() -> str:
    """Placeholder del cron diario. TODO(epic-cobranza): generar cuotas, recordatorios,
    marcar vencidos y alertar morosidad de forma idempotente.
    """
    logger.info("cron_diario_cuotas: placeholder (sin lógica de cuotas en este epic)")
    return "noop"
