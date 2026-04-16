from __future__ import annotations

import uvicorn

from .settings import get_api_settings


def main() -> None:
    settings = get_api_settings()
    uvicorn.run(
        "apps.api.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()
