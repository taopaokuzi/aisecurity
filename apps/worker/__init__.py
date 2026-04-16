"""Celery runtime entry for the aisecurity worker service."""

from .celery_app import celery_app, create_celery_app

__all__ = ["celery_app", "create_celery_app"]
