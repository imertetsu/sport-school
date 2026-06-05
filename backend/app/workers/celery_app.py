"""App Celery (broker/backend Redis desde el entorno).

Esqueleto para este epic: registra las tasks y deja un beat schedule placeholder
para el cron diario. La lógica de cuotas/recordatorios llega en un epic posterior
(SRS §4.4) y debe ser idempotente.
"""

from __future__ import annotations

from celery import Celery

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

# Beat schedule placeholder. La task aún no hace nada (sin lógica de cuotas).
celery_app.conf.beat_schedule = {
    "cron-diario-cuotas": {
        "task": "app.workers.tasks.cron_diario_cuotas",
        "schedule": 24 * 60 * 60,  # diario; refinar (crontab) en el epic de cobranza
    },
}

# Importa las tasks para que queden registradas en el worker.
celery_app.autodiscover_tasks(["app.workers"])

import app.workers.tasks  # noqa: E402,F401  (registra las tasks)
