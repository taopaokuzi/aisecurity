from __future__ import annotations

import argparse
import json
import os
import sys
import tomllib
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = ROOT_DIR / "config"
DEFAULT_ENV = "dev"
ENV_ALIASES = {
    "dev": "dev",
    "development": "dev",
    "local": "dev",
    "prod": "prod",
    "production": "prod",
    "test": "test",
    "testing": "test",
}

ENV_TO_PATH = {
    "APP_VERSION": ("app", "version"),
    "LOG_LEVEL": ("app", "log_level"),
    "APP_EXTERNAL_MODE": ("app", "external_mode"),
    "API_SERVICE_NAME": ("api", "service_name"),
    "API_HOST": ("api", "host"),
    "API_PORT": ("api", "port"),
    "WORKER_SERVICE_NAME": ("worker", "service_name"),
    "WORKER_LOG_LEVEL": ("worker", "log_level"),
    "CELERY_QUEUE_NAME": ("worker", "queue_name"),
    "WEB_SERVICE_NAME": ("web", "service_name"),
    "WEB_PORT": ("web", "port"),
    "NEXT_PUBLIC_API_BASE_URL": ("web", "next_public_api_base_url"),
    "POSTGRES_HOST": ("database", "host"),
    "POSTGRES_PORT": ("database", "port"),
    "POSTGRES_DB": ("database", "name"),
    "POSTGRES_USER": ("database", "user"),
    "POSTGRES_PASSWORD": ("database", "password"),
    "REDIS_HOST": ("redis", "host"),
    "REDIS_PORT": ("redis", "port"),
    "REDIS_DB": ("redis", "db"),
    "SSO_MODE": ("integrations", "sso", "mode"),
    "SSO_BASE_URL": ("integrations", "sso", "base_url"),
    "SSO_CLIENT_ID": ("integrations", "sso", "client_id"),
    "SSO_CLIENT_SECRET": ("integrations", "sso", "client_secret"),
    "FEISHU_MODE": ("integrations", "feishu", "mode"),
    "FEISHU_APP_ID": ("integrations", "feishu", "app_id"),
    "FEISHU_APP_SECRET": ("integrations", "feishu", "app_secret"),
    "FEISHU_APPROVAL_BASE_URL": ("integrations", "feishu", "approval_base_url"),
    "FEISHU_PERMISSION_BASE_URL": ("integrations", "feishu", "permission_base_url"),
    "FEISHU_CALLBACK_SIGNING_SECRET": (
        "integrations",
        "feishu",
        "callback_signing_secret",
    ),
    "MOCK_FEISHU_BASE_URL": ("integrations", "feishu", "mock_base_url"),
    "LLM_PROVIDER": ("llm", "provider"),
    "LLM_BASE_URL": ("llm", "base_url"),
    "LLM_API_KEY": ("llm", "api_key"),
    "LLM_MODEL": ("llm", "model"),
    "LLM_TIMEOUT_SECONDS": ("llm", "timeout_seconds"),
    "LLM_PROMPT_DIR": ("llm", "prompt_dir"),
    "SIGNING_SECRET": ("security", "signing_secret"),
    "AUDIT_HASH_SECRET": ("security", "audit_hash_secret"),
}


def normalize_env_name(value: str | None) -> str:
    normalized = (value or DEFAULT_ENV).strip().lower()
    if not normalized:
        return DEFAULT_ENV
    return ENV_ALIASES.get(normalized, normalized)


def load_toml_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("rb") as handle:
        loaded = tomllib.load(handle)
    return loaded if isinstance(loaded, dict) else {}


def load_dotenv_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}

    loaded: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line.removeprefix("export ").strip()
        key, separator, value = line.partition("=")
        if not separator:
            continue
        loaded[key.strip()] = value.strip().strip('"').strip("'")
    return loaded


def deep_merge(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in overlay.items():
        existing = merged.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            merged[key] = deep_merge(existing, value)
        else:
            merged[key] = value
    return merged


def get_nested(data: dict[str, Any], path: tuple[str, ...], default: Any = None) -> Any:
    cursor: Any = data
    for part in path:
        if not isinstance(cursor, dict) or part not in cursor:
            return default
        cursor = cursor[part]
    return cursor


def set_nested(data: dict[str, Any], path: tuple[str, ...], value: Any) -> None:
    cursor = data
    for part in path[:-1]:
        cursor = cursor.setdefault(part, {})
    cursor[path[-1]] = value


def stringify(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def build_database_url(settings: dict[str, Any]) -> str:
    database = settings["database"]
    scheme = database.get("scheme", "postgresql+psycopg")
    return (
        f"{scheme}://{database['user']}:{database['password']}"
        f"@{database['host']}:{database['port']}/{database['name']}"
    )


def build_redis_url(host: str, port: Any, db: Any, scheme: str = "redis") -> str:
    return f"{scheme}://{host}:{port}/{db}"


def load_settings(env_name: str | None = None) -> tuple[dict[str, Any], str]:
    file_env = load_dotenv_file(ROOT_DIR / ".env")
    effective_env = normalize_env_name(
        env_name
        or os.getenv("APP_ENV")
        or os.getenv("CONFIG_PROFILE")
        or file_env.get("APP_ENV")
        or file_env.get("CONFIG_PROFILE")
    )
    settings = deep_merge(
        load_toml_file(CONFIG_DIR / "settings.base.toml"),
        load_toml_file(CONFIG_DIR / f"settings.{effective_env}.toml"),
    )
    set_nested(settings, ("app", "env"), effective_env)

    for env_key, path in ENV_TO_PATH.items():
        file_override = file_env.get(env_key)
        shell_override = os.getenv(env_key)
        if file_override is not None and file_override != "":
            set_nested(settings, path, file_override)
        if shell_override is not None and shell_override != "":
            set_nested(settings, path, shell_override)

    return settings, effective_env


def load_runtime_env(env_name: str | None = None) -> dict[str, str]:
    settings, effective_env = load_settings(env_name=env_name)
    file_env = load_dotenv_file(ROOT_DIR / ".env")
    app = settings.setdefault("app", {})
    api = settings.setdefault("api", {})
    worker = settings.setdefault("worker", {})
    web = settings.setdefault("web", {})
    database = settings.setdefault("database", {})
    redis = settings.setdefault("redis", {})
    celery = settings.setdefault("celery", {})
    llm = settings.setdefault("llm", {})
    sso = get_nested(settings, ("integrations", "sso"), {}) or {}
    feishu = get_nested(settings, ("integrations", "feishu"), {}) or {}
    security = settings.setdefault("security", {})

    database_url = (
        os.getenv("DATABASE_URL")
        or file_env.get("DATABASE_URL")
        or database.get("url")
        or build_database_url(settings)
    )
    redis_url = (
        os.getenv("REDIS_URL")
        or file_env.get("REDIS_URL")
        or redis.get("url")
        or build_redis_url(
            host=database_value(redis, "host", "127.0.0.1"),
            port=database_value(redis, "port", 6379),
            db=database_value(redis, "db", 0),
            scheme=database_value(redis, "scheme", "redis"),
        )
    )
    celery_broker_url = (
        os.getenv("CELERY_BROKER_URL")
        or file_env.get("CELERY_BROKER_URL")
        or celery.get("broker_url")
        or redis_url
    )
    celery_result_backend = (
        os.getenv("CELERY_RESULT_BACKEND")
        or file_env.get("CELERY_RESULT_BACKEND")
        or celery.get("result_backend")
        or build_redis_url(
            host=database_value(redis, "host", "127.0.0.1"),
            port=database_value(redis, "port", 6379),
            db=database_value(celery, "result_db", 1),
            scheme=database_value(redis, "scheme", "redis"),
        )
    )

    runtime_env = {
        "APP_NAME": stringify(app.get("name", "aisecurity")),
        "APP_VERSION": stringify(app.get("version", "0.1.0")),
        "APP_ENV": effective_env,
        "CONFIG_PROFILE": effective_env,
        "LOG_LEVEL": stringify(app.get("log_level", "INFO")),
        "APP_EXTERNAL_MODE": stringify(app.get("external_mode", "mock")),
        "API_SERVICE_NAME": stringify(api.get("service_name", "aisecurity-api")),
        "API_HOST": stringify(api.get("host", "0.0.0.0")),
        "API_PORT": stringify(api.get("port", 8000)),
        "WORKER_SERVICE_NAME": stringify(worker.get("service_name", "aisecurity-worker")),
        "WORKER_LOG_LEVEL": stringify(worker.get("log_level", app.get("log_level", "INFO"))),
        "CELERY_QUEUE_NAME": stringify(worker.get("queue_name", "aisecurity.default")),
        "WEB_SERVICE_NAME": stringify(web.get("service_name", "aisecurity-web")),
        "WEB_PORT": stringify(web.get("port", 3000)),
        "NEXT_PUBLIC_API_BASE_URL": stringify(
            web.get("next_public_api_base_url", "http://localhost:8000")
        ),
        "POSTGRES_HOST": stringify(database.get("host", "postgres")),
        "POSTGRES_PORT": stringify(database.get("port", 5432)),
        "POSTGRES_DB": stringify(database.get("name", "aisecurity")),
        "POSTGRES_USER": stringify(database.get("user", "aisecurity")),
        "POSTGRES_PASSWORD": stringify(database.get("password", "aisecurity")),
        "DATABASE_URL": stringify(database_url),
        "REDIS_HOST": stringify(redis.get("host", "redis")),
        "REDIS_PORT": stringify(redis.get("port", 6379)),
        "REDIS_DB": stringify(redis.get("db", 0)),
        "REDIS_URL": stringify(redis_url),
        "CELERY_BROKER_URL": stringify(celery_broker_url),
        "CELERY_RESULT_BACKEND": stringify(celery_result_backend),
        "SSO_MODE": stringify(sso.get("mode", "stub")),
        "SSO_BASE_URL": stringify(sso.get("base_url", "http://stub-sso:8080")),
        "SSO_CLIENT_ID": stringify(sso.get("client_id", "stub-client-id")),
        "SSO_CLIENT_SECRET": stringify(sso.get("client_secret", "stub-client-secret")),
        "FEISHU_MODE": stringify(feishu.get("mode", "mock")),
        "FEISHU_APP_ID": stringify(feishu.get("app_id", "mock-app-id")),
        "FEISHU_APP_SECRET": stringify(feishu.get("app_secret", "mock-app-secret")),
        "FEISHU_APPROVAL_BASE_URL": stringify(
            feishu.get("approval_base_url", "http://mock-feishu:8080/approval")
        ),
        "FEISHU_PERMISSION_BASE_URL": stringify(
            feishu.get("permission_base_url", "http://mock-feishu:8080/permission")
        ),
        "FEISHU_CALLBACK_SIGNING_SECRET": stringify(
            feishu.get("callback_signing_secret", "mock-callback-secret")
        ),
        "MOCK_FEISHU_BASE_URL": stringify(feishu.get("mock_base_url", "http://mock-feishu:8080")),
        "LLM_PROVIDER": stringify(llm.get("provider", "stub")),
        "LLM_BASE_URL": stringify(llm.get("base_url", "https://api.openai.com/v1")),
        "LLM_API_KEY": stringify(llm.get("api_key", "")),
        "LLM_MODEL": stringify(llm.get("model", "gpt-4.1-mini")),
        "LLM_TIMEOUT_SECONDS": stringify(llm.get("timeout_seconds", 30)),
        "LLM_PROMPT_DIR": stringify(llm.get("prompt_dir", "packages/prompts/templates")),
        "SIGNING_SECRET": stringify(security.get("signing_secret", "dev-signing-secret")),
        "AUDIT_HASH_SECRET": stringify(security.get("audit_hash_secret", "dev-audit-hash-secret")),
    }

    for source in (file_env, os.environ):
        for key, value in source.items():
            if key in runtime_env and value != "":
                runtime_env[key] = value

    return runtime_env


def database_value(values: dict[str, Any], key: str, default: Any) -> Any:
    return values.get(key, default)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Layered runtime configuration loader.")
    subparsers = parser.add_subparsers(dest="mode")

    show_parser = subparsers.add_parser("show", help="Print the resolved runtime environment.")
    show_parser.add_argument("--env", dest="env_name", default=None)
    show_parser.add_argument("--format", choices=("dotenv", "json"), default="dotenv")

    exec_parser = subparsers.add_parser("exec", help="Run a command with resolved settings.")
    exec_parser.add_argument("--env", dest="env_name", default=None)
    exec_parser.add_argument("command", nargs=argparse.REMAINDER)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    arguments = list(sys.argv[1:] if argv is None else argv)
    if not arguments:
        arguments = ["show"]
    args = parser.parse_args(arguments)

    if args.mode == "exec":
        command = list(args.command)
        if command and command[0] == "--":
            command = command[1:]
        if not command:
            parser.error("exec mode requires a command after '--'")
        runtime_env = {**os.environ, **load_runtime_env(env_name=args.env_name)}
        os.execvpe(command[0], command, runtime_env)
        raise SystemExit(0)

    runtime_env = load_runtime_env(env_name=getattr(args, "env_name", None))
    if getattr(args, "format", "dotenv") == "json":
        print(json.dumps(runtime_env, ensure_ascii=False, indent=2, sort_keys=True))
        return

    for key in sorted(runtime_env):
        print(f"{key}={runtime_env[key]}")


if __name__ == "__main__":
    main()
