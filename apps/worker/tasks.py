from __future__ import annotations

from datetime import datetime, timezone

from celery import Celery


REGISTERED_TASKS = (
    "worker.ping",
    "worker.runtime_summary",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def register_tasks(celery_app: Celery) -> None:
    if "worker.ping" not in celery_app.tasks:

        @celery_app.task(name="worker.ping")
        def ping() -> dict[str, str]:
            return {
                "status": "ok",
                "service": celery_app.conf.worker_service_name,
                "timestamp": utc_now(),
            }

    if "worker.runtime_summary" not in celery_app.tasks:

        @celery_app.task(name="worker.runtime_summary")
        def runtime_summary() -> dict[str, str]:
            return {
                "service": celery_app.conf.worker_service_name,
                "broker_url": celery_app.conf.broker_url,
                "result_backend": celery_app.conf.result_backend,
                "queue_name": celery_app.conf.task_default_queue,
                "timestamp": utc_now(),
            }
