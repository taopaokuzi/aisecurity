from __future__ import annotations

import json
from datetime import datetime, timezone

from .celery_app import celery_app
from .settings import get_worker_settings
from .tasks import REGISTERED_TASKS


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def build_health_payload() -> dict[str, object]:
    settings = get_worker_settings()
    registered = sorted(name for name in celery_app.tasks.keys() if name.startswith("worker."))
    status = "ok" if all(name in registered for name in REGISTERED_TASKS) else "degraded"
    return {
        "status": status,
        "service": settings.service_name,
        "version": settings.version,
        "environment": settings.environment,
        "broker_url": settings.broker_url,
        "result_backend": settings.result_backend,
        "registered_tasks": registered,
        "timestamp": utc_now(),
    }


def main() -> None:
    payload = build_health_payload()
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    raise SystemExit(0 if payload["status"] == "ok" else 1)


if __name__ == "__main__":
    main()
