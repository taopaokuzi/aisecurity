"""FastAPI runtime entry for the aisecurity API service."""

from .main import app, create_app

__all__ = ["app", "create_app"]
