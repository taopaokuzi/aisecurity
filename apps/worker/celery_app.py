from __future__ import annotations

from celery import Celery

from .settings import get_worker_settings
from .tasks import register_tasks


def create_celery_app() -> Celery:
    settings = get_worker_settings()
    celery_app = Celery(
        "aisecurity.worker",
        broker=settings.broker_url,
        backend=settings.result_backend,
    )
    celery_app.conf.update(
        accept_content=["json"],
        beat_schedule={
            "grant-lifecycle-reconcile-hourly": {
                "task": "worker.grants.lifecycle.reconcile",
                "schedule": 3600.0,
            }
        },
        broker_connection_retry_on_startup=True,
        enable_utc=True,
        result_serializer="json",
        task_default_queue=settings.queue_name,
        task_ignore_result=False,
        task_serializer="json",
        timezone="UTC",
        worker_prefetch_multiplier=1,
        worker_service_name=settings.service_name,
        worker_version=settings.version,
        worker_environment=settings.environment,
    )
    register_tasks(celery_app)
    return celery_app


celery_app = create_celery_app()
