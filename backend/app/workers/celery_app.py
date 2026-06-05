"""App Celery (broker/backend Redis desde el entorno).

Registra las tasks de cobranza y agenda el cron diario `cobranza_diaria` (C6),
que es idempotente (no duplica cuotas ni reenvía recordatorios).
"""

from __future__ import annotations

from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

celery_app = Celery(
    "cantera",
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
celery_app.conf.beat_schedule = {
    "cobranza-diaria": {
        "task": "app.workers.tasks.cobranza_diaria",
        "schedule": crontab(hour=6, minute=0),
    },
}

# Importa las tasks para que queden registradas en el worker.
celery_app.autodiscover_tasks(["app.workers"])

import app.workers.tasks  # noqa: E402,F401  (registra las tasks)
