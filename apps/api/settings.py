from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class ApiSettings:
    service_name: str
    version: str
    environment: str
    host: str
    port: int


@lru_cache(maxsize=1)
def get_api_settings() -> ApiSettings:
    return ApiSettings(
        service_name=os.getenv("API_SERVICE_NAME", "aisecurity-api"),
        version=os.getenv("APP_VERSION", "0.1.0"),
        environment=os.getenv("APP_ENV", "development"),
        host=os.getenv("API_HOST", "0.0.0.0"),
        port=int(os.getenv("API_PORT", "8000")),
    )
