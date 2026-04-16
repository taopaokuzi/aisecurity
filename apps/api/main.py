from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI

from .settings import get_api_settings


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def build_health_payload(started_at: str | None = None) -> dict[str, str]:
    settings = get_api_settings()
    payload = {
        "status": "ok",
        "service": settings.service_name,
        "version": settings.version,
        "environment": settings.environment,
        "timestamp": utc_now(),
    }
    if started_at is not None:
        payload["started_at"] = started_at
    return payload


def create_app() -> FastAPI:
    settings = get_api_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.started_at = utc_now()
        yield

    app = FastAPI(
        title="aisecurity API",
        version=settings.version,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url=None,
    )

    @app.get("/", tags=["system"])
    async def root() -> dict[str, object]:
        return {
            "service": settings.service_name,
            "status": "ok",
            "docs": "/docs",
            "health": "/health",
        }

    @app.get("/health", tags=["system"])
    async def health() -> dict[str, str]:
        started_at = getattr(app.state, "started_at", None)
        return build_health_payload(started_at=started_at)

    return app


app = create_app()
