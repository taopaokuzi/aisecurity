from __future__ import annotations

from .celery_app import celery_app
from .settings import get_worker_settings


def main() -> None:
    settings = get_worker_settings()
    celery_app.worker_main(
        [
            "worker",
            "--loglevel",
            settings.log_level,
            "--pool",
            "solo",
        ]
    )


if __name__ == "__main__":
    main()
