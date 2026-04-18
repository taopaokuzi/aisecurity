#!/usr/bin/env python3
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

import psycopg


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_PYTHON_BIN = ROOT_DIR / ".venv" / "bin" / "python"
PGEMBED_BIN_DIR = (
    ROOT_DIR
    / ".venv"
    / "lib"
    / "python3.12"
    / "site-packages"
    / "pgembed"
    / "pginstall"
    / "bin"
)
PGEMBED_LIB_DIR = PGEMBED_BIN_DIR.parent / "lib"


@dataclass(frozen=True)
class DatabaseUrls:
    test: str
    admin: str


class EmbeddedPostgres:
    def __init__(self) -> None:
        self.pgdata = Path(tempfile.mkdtemp(prefix="task018-pgdata-", dir="/tmp"))
        self.log_file = self.pgdata.parent / f"{self.pgdata.name}.log"
        self.port = self._find_free_port()
        self._env = os.environ.copy()
        existing_library_path = self._env.get("LD_LIBRARY_PATH", "")
        self._env["LD_LIBRARY_PATH"] = (
            f"{PGEMBED_LIB_DIR}:{existing_library_path}"
            if existing_library_path
            else str(PGEMBED_LIB_DIR)
        )

    @property
    def urls(self) -> DatabaseUrls:
        return DatabaseUrls(
            test=f"postgresql+psycopg://postgres@127.0.0.1:{self.port}/aisecurity_test",
            admin=f"postgresql+psycopg://postgres@127.0.0.1:{self.port}/postgres",
        )

    def start(self) -> None:
        self._run(
            [
                str(PGEMBED_BIN_DIR / "initdb"),
                "-D",
                str(self.pgdata),
                "--auth=trust",
                "--auth-local=trust",
                "--encoding=utf8",
                "-U",
                "postgres",
            ]
        )
        self._run(
            [
                str(PGEMBED_BIN_DIR / "pg_ctl"),
                "-D",
                str(self.pgdata),
                "-l",
                str(self.log_file),
                "-o",
                f"-h 127.0.0.1 -p {self.port}",
                "-w",
                "start",
            ]
        )
        wait_for_database(self.urls.admin, timeout_seconds=15)

    def stop(self) -> None:
        pg_ctl = PGEMBED_BIN_DIR / "pg_ctl"
        if pg_ctl.exists():
            subprocess.run(
                [
                    str(pg_ctl),
                    "-D",
                    str(self.pgdata),
                    "-w",
                    "stop",
                    "-m",
                    "fast",
                ],
                cwd=ROOT_DIR,
                env=self._env,
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
        shutil.rmtree(self.pgdata, ignore_errors=True)
        self.log_file.unlink(missing_ok=True)

    def _run(self, command: list[str]) -> None:
        result = subprocess.run(
            command,
            cwd=ROOT_DIR,
            env=self._env,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(result.stdout.strip() or "embedded postgres command failed")

    @staticmethod
    def _find_free_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            return int(sock.getsockname()[1])


def build_urls(*, host: str, port: str, user: str, password: str) -> DatabaseUrls:
    return DatabaseUrls(
        test=f"postgresql+psycopg://{user}:{password}@{host}:{port}/aisecurity_test",
        admin=f"postgresql+psycopg://{user}:{password}@{host}:{port}/postgres",
    )


def wait_for_database(
    database_url: str,
    *,
    timeout_seconds: float,
    quiet: bool = False,
) -> bool:
    deadline = time.time() + timeout_seconds
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            with psycopg.connect(_psycopg_database_url(database_url), connect_timeout=2) as connection:
                with connection.cursor() as cursor:
                    cursor.execute("select 1")
                    cursor.fetchone()
            return True
        except Exception as exc:  # pragma: no cover - runtime probe
            last_error = exc
            time.sleep(0.5)
    if quiet:
        return False
    raise RuntimeError(f"database not ready: {last_error}")


def _psycopg_database_url(database_url: str) -> str:
    return database_url.replace("postgresql+psycopg://", "postgresql://", 1)


def resolve_database_urls() -> tuple[DatabaseUrls, str, EmbeddedPostgres | None]:
    explicit_test_url = os.getenv("TEST_DATABASE_URL")
    explicit_admin_url = os.getenv("TEST_ADMIN_DATABASE_URL")
    mode = os.getenv("TASK_018_DB_MODE", "auto").strip().lower() or "auto"

    if explicit_test_url or explicit_admin_url:
        if not (explicit_test_url and explicit_admin_url):
            raise RuntimeError(
                "TEST_DATABASE_URL and TEST_ADMIN_DATABASE_URL must be provided together"
            )
        urls = DatabaseUrls(test=explicit_test_url, admin=explicit_admin_url)
        wait_for_database(urls.admin, timeout_seconds=20)
        return urls, "explicit-env", None

    host = os.getenv("POSTGRES_HOST", "127.0.0.1")
    port = os.getenv("POSTGRES_PORT", "5432")
    user = os.getenv("POSTGRES_USER", "aisecurity")
    password = os.getenv("POSTGRES_PASSWORD", "aisecurity")
    external_urls = build_urls(host=host, port=port, user=user, password=password)

    if mode in {"auto", "external"} and wait_for_database(
        external_urls.admin, timeout_seconds=3, quiet=True
    ):
        return external_urls, f"external:{host}:{port}", None

    if mode == "external":
        raise RuntimeError(
            f"external postgres is not reachable at {host}:{port}; "
            "set TEST_DATABASE_URL/TEST_ADMIN_DATABASE_URL or unset TASK_018_DB_MODE=external"
        )

    if not PGEMBED_BIN_DIR.exists():
        raise RuntimeError("embedded postgres binaries are not available")

    embedded = EmbeddedPostgres()
    embedded.start()
    return embedded.urls, f"embedded:127.0.0.1:{embedded.port}", embedded


def main() -> int:
    python_bin = Path(os.getenv("PYTHON_BIN", str(DEFAULT_PYTHON_BIN)))
    if not python_bin.exists():
        raise RuntimeError(f"python executable not found: {python_bin}")

    embedded: EmbeddedPostgres | None = None
    urls, runtime_label, embedded = resolve_database_urls()
    print(f"[task-018] database runtime: {runtime_label}")
    print(f"[task-018] TEST_DATABASE_URL={urls.test}")
    print(f"[task-018] TEST_ADMIN_DATABASE_URL={urls.admin}")

    env = os.environ.copy()
    env["TEST_DATABASE_URL"] = urls.test
    env["TEST_ADMIN_DATABASE_URL"] = urls.admin

    command = [
        str(python_bin),
        "-m",
        "unittest",
        "tests.integration.test_feishu_flow_integration",
        "tests.e2e.test_permission_workflows_e2e",
        "-v",
    ]
    try:
        result = subprocess.run(command, cwd=ROOT_DIR, env=env, check=False)
        return result.returncode
    finally:
        if embedded is not None:
            embedded.stop()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # pragma: no cover - script entrypoint
        print(f"[task-018] ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
