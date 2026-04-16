from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class WorkerSettings:
    service_name: str
    version: str
    environment: str
    broker_url: str
    result_backend: str
    log_level: str
    queue_name: str


@lru_cache(maxsize=1)
def get_worker_settings() -> WorkerSettings:
    return WorkerSettings(
        service_name=os.getenv("WORKER_SERVICE_NAME", "aisecurity-worker"),
        version=os.getenv("APP_VERSION", "0.1.0"),
        environment=os.getenv("APP_ENV", "development"),
        broker_url=os.getenv("CELERY_BROKER_URL", "memory://"),
        result_backend=os.getenv("CELERY_RESULT_BACKEND", "cache+memory://"),
        log_level=os.getenv("WORKER_LOG_LEVEL", "info"),
        queue_name=os.getenv("CELERY_QUEUE_NAME", "aisecurity.default"),
    )
