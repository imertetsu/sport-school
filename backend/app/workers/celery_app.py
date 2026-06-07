"""App Celery (broker/backend Redis desde el entorno).

Registra las tasks de cobranza y agenda:
- el cron diario `cobranza_diaria` (C6), idempotente (no duplica cuotas ni reenvía);
- el cron diario `generar_sesiones_programadas` (C3, Programación de clases), que
  genera las sesiones futuras de cada horario (idempotente, reutiliza Asistencia);
- el cron horario `recordatorios_clase` (C3), recordatorio N horas antes de cada
  clase (idempotente vía `sesion.recordatorio_enviado_en`);
- el cron semanal `recordatorio_deudores_semanal` (epic Recordatorio de deudores),
  lunes 07:00 UTC, digest de deudores a cada entrenador (idempotente por semana ISO).
"""

from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

celery_app = Celery(
    "latinosport",
    broker=settings.redis_url,
    backend=settings.redis_url,
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
)

# Cron diario de cobranza (C6): genera cuotas, marca VENCIDO, recordatorios y
# alertas de morosidad. Crontab a las 06:00 UTC; idempotente al re-correr.
# Programación de clases (C3): generación 1×/día (05:00 UTC) + recordatorio cada
# hora (minuto 0). Ambas iteran todas las orgs fijando contexto; idempotentes.
celery_app.conf.beat_schedule = {
    "cobranza-diaria": {
        "task": "app.workers.tasks.cobranza_diaria",
        "schedule": crontab(hour=6, minute=0),
    },
    "generar-sesiones-programadas": {
        "task": "app.workers.tasks.generar_sesiones_programadas",
        "schedule": crontab(hour=5, minute=0),
    },
    "recordatorios-clase": {
        "task": "app.workers.tasks.recordatorios_clase",
        "schedule": crontab(minute=0),
    },
    # Recordatorio de deudores al entrenador: lunes 07:00 UTC, idempotente por semana
    # ISO (no reenvía si se re-corre la misma semana).
    "recordatorio-deudores-semanal": {
        "task": "app.workers.tasks.recordatorio_deudores_semanal",
        "schedule": crontab(day_of_week=1, hour=7, minute=0),
    },
}

# Importa las tasks para que queden registradas en el worker.
celery_app.autodiscover_tasks(["app.workers"])

import app.workers.tasks  # noqa: E402,F401  (registra las tasks)
