from __future__ import annotations

import json
import os
import socket
import threading
import time
import urllib.error
import urllib.request
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from unittest import mock

import uvicorn
from celery import Celery
from sqlalchemy import create_engine, delete, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from apps.api.dependencies import get_db_session
from apps.api.main import create_app
from apps.worker.tasks import register_tasks
from packages.infrastructure.db import Base
from packages.infrastructure.db.models import (
    AccessGrantRecord,
    AgentIdentityRecord,
    ApprovalRecordRecord,
    AuditRecordRecord,
    ConnectorTaskRecord,
    DelegationCredentialRecord,
    NotificationTaskRecord,
    PermissionRequestEventRecord,
    PermissionRequestRecord,
    SessionContextRecord,
    UserRecord,
)
from tests.support.mock_feishu import (
    MockFeishuPermissionConnector,
    MockFeishuSessionConnector,
    create_mock_feishu_app,
)

CALLBACK_SECRET = "test-approval-secret"


def _host_resolves(host: str) -> bool:
    try:
        socket.getaddrinfo(host, None)
    except OSError:
        return False
    return True


def _default_postgres_host() -> str:
    configured_host = (os.getenv("POSTGRES_HOST") or "").strip()
    if configured_host:
        return configured_host
    if _host_resolves("postgres"):
        return "postgres"
    return "127.0.0.1"


def _default_database_url(database_name: str) -> str:
    host = _default_postgres_host()
    port = os.getenv("POSTGRES_PORT", "5432")
    user = os.getenv("POSTGRES_USER", "aisecurity")
    password = os.getenv("POSTGRES_PASSWORD", "aisecurity")
    return f"postgresql+psycopg://{user}:{password}@{host}:{port}/{database_name}"


TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL", _default_database_url("aisecurity_test"))
ADMIN_DATABASE_URL = os.getenv("TEST_ADMIN_DATABASE_URL", _default_database_url("postgres"))


def ensure_test_database() -> None:
    database_name = make_url(TEST_DATABASE_URL).database
    admin_engine = create_engine(ADMIN_DATABASE_URL, isolation_level="AUTOCOMMIT")
    try:
        with admin_engine.connect() as connection:
            exists = connection.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :database_name"),
                {"database_name": database_name},
            )
            if not exists:
                connection.execute(text(f'CREATE DATABASE "{database_name}"'))
    finally:
        admin_engine.dispose()


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        sock.listen(1)
        return int(sock.getsockname()[1])


def _wait_for_server_ready(base_url: str, timeout: float = 10.0) -> None:
    start = time.time()
    last_error: Exception | None = None
    while time.time() - start < timeout:
        try:
            with urllib.request.urlopen(f"{base_url}/health", timeout=1):
                return
        except Exception as exc:  # pragma: no cover - helper
            last_error = exc
            time.sleep(0.05)
    raise RuntimeError(f"Server did not become ready: {last_error}")


def json_request(
    *,
    method: str,
    url: str,
    payload: dict[str, object] | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, object]]:
    request = urllib.request.Request(
        url,
        data=(json.dumps(payload).encode("utf-8") if payload is not None else None),
        headers=headers or {},
        method=method,
    )
    if payload is not None and "Content-Type" not in request.headers:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            status_code = response.getcode()
            raw_body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        status_code = exc.code
        raw_body = exc.read().decode("utf-8")
    return status_code, (json.loads(raw_body) if raw_body else {})


@dataclass
class _RunningServer:
    server: uvicorn.Server
    thread: threading.Thread
    base_url: str


class FeishuFlowHarness:
    def __init__(self) -> None:
        self.engine = None
        self.session_factory = None
        self.app = None
        self.api_server: _RunningServer | None = None
        self.mock_server: _RunningServer | None = None
        self.celery_app = None
        self._patchers: list[mock._patch] = []
        self.api_base_url = ""
        self.mock_base_url = ""

    def start(self) -> None:
        ensure_test_database()
        os.environ["APPROVAL_CALLBACK_SECRET"] = CALLBACK_SECRET
        os.environ["APPROVAL_CALLBACK_ALLOWED_SOURCES"] = "127.0.0.1"
        os.environ["APPROVAL_CALLBACK_MAX_AGE_SECONDS"] = "300"
        os.environ["MOCK_FEISHU_APPROVAL_SECRET"] = CALLBACK_SECRET

        self.engine = create_engine(TEST_DATABASE_URL, future=True)
        self.session_factory = sessionmaker(
            bind=self.engine,
            autoflush=False,
            expire_on_commit=False,
            class_=Session,
        )
        Base.metadata.drop_all(self.engine)
        Base.metadata.create_all(self.engine)

        self.mock_server = self._start_server(create_mock_feishu_app())
        self.mock_base_url = self.mock_server.base_url
        self._start_patchers()

        self.app = create_app()

        def override_get_db_session():
            session = self.session_factory()
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise
            finally:
                session.close()

        self.app.dependency_overrides[get_db_session] = override_get_db_session
        self.api_server = self._start_server(self.app)
        self.api_base_url = self.api_server.base_url

        self.celery_app = Celery(
            "aisecurity.mock-feishu.test",
            broker="memory://",
            backend="cache+memory://",
        )
        self.celery_app.conf.update(
            worker_service_name="aisecurity-worker-test",
            task_default_queue="aisecurity.default",
        )
        register_tasks(self.celery_app)

    def stop(self) -> None:
        for patcher in reversed(self._patchers):
            patcher.stop()
        self._patchers.clear()
        if self.api_server is not None:
            self.api_server.server.should_exit = True
            self.api_server.thread.join(timeout=5)
        if self.mock_server is not None:
            self.mock_server.server.should_exit = True
            self.mock_server.thread.join(timeout=5)
        if self.app is not None:
            self.app.dependency_overrides.clear()
        if self.engine is not None:
            self.engine.dispose()

    def reset_state(self) -> None:
        os.environ["MOCK_FEISHU_PROVISION_SCENARIO"] = "applied"
        os.environ["MOCK_FEISHU_SESSION_REVOKE_SCENARIO"] = "success"
        with self.session_factory.begin() as session:
            for model in (
                AuditRecordRecord,
                ConnectorTaskRecord,
                NotificationTaskRecord,
                PermissionRequestEventRecord,
                SessionContextRecord,
                AccessGrantRecord,
                ApprovalRecordRecord,
                PermissionRequestRecord,
                DelegationCredentialRecord,
                AgentIdentityRecord,
                UserRecord,
            ):
                session.execute(delete(model))
        self.seed_identity_data()

    def seed_identity_data(self) -> None:
        now = datetime(2026, 4, 18, 0, 0, tzinfo=timezone.utc)
        with self.session_factory.begin() as session:
            session.add_all(
                [
                    UserRecord(
                        user_id="user_001",
                        employee_no="E001",
                        display_name="Alice",
                        email="alice@example.com",
                        department_id="dept_sales",
                        department_name="Sales",
                        manager_user_id="user_mgr_001",
                        user_status="Active",
                        identity_source="SSO",
                        created_at=now,
                        updated_at=now,
                    ),
                    UserRecord(
                        user_id="user_mgr_001",
                        employee_no="E101",
                        display_name="Manager",
                        email="manager@example.com",
                        department_id="dept_sales",
                        department_name="Sales",
                        manager_user_id="user_root_001",
                        user_status="Active",
                        identity_source="SSO",
                        created_at=now,
                        updated_at=now,
                    ),
                    UserRecord(
                        user_id="security_admin_001",
                        employee_no="E901",
                        display_name="Security Admin",
                        email="sec-admin@example.com",
                        department_id="dept_security",
                        department_name="Security",
                        manager_user_id="user_root_001",
                        user_status="Active",
                        identity_source="SSO",
                        created_at=now,
                        updated_at=now,
                    ),
                    UserRecord(
                        user_id="it_admin_001",
                        employee_no="E902",
                        display_name="IT Admin",
                        email="it-admin@example.com",
                        department_id="dept_it",
                        department_name="IT",
                        manager_user_id="user_root_001",
                        user_status="Active",
                        identity_source="SSO",
                        created_at=now,
                        updated_at=now,
                    ),
                ]
            )
            session.add(
                AgentIdentityRecord(
                    agent_id="agent_perm_assistant_v1",
                    agent_name="Permission Assistant",
                    agent_version="v1",
                    agent_type="first_party",
                    agent_status="Active",
                    capability_scope_json={
                        "resource_types": ["report", "doc"],
                        "allowed_actions": ["read", "request_edit"],
                    },
                    created_at=now,
                    updated_at=now,
                )
            )
            session.flush()
            session.add(
                DelegationCredentialRecord(
                    delegation_id="dlg_123",
                    user_id="user_001",
                    agent_id="agent_perm_assistant_v1",
                    task_scope="permission_self_service",
                    scope_json={
                        "resource_types": ["report", "doc"],
                        "allowed_actions": ["read", "request_edit"],
                    },
                    delegation_status="Active",
                    issued_at=now,
                    expire_at=now + timedelta(days=7),
                    revoked_at=None,
                    revocation_reason=None,
                    created_at=now,
                    updated_at=now,
                )
            )

    @contextmanager
    def session(self):
        db_session = self.session_factory()
        try:
            yield db_session
        finally:
            db_session.close()

    def api_request(
        self,
        *,
        method: str,
        path: str,
        payload: dict[str, object] | None = None,
        headers: dict[str, str] | None = None,
    ) -> tuple[int, dict[str, object]]:
        return json_request(
            method=method,
            url=f"{self.api_base_url}{path}",
            payload=payload,
            headers=headers,
        )

    def mock_request(
        self,
        *,
        method: str,
        path: str,
        payload: dict[str, object] | None = None,
    ) -> tuple[int, dict[str, object]]:
        return json_request(
            method=method,
            url=f"{self.mock_base_url}{path}",
            payload=payload,
            headers={"Content-Type": "application/json"},
        )

    def run_lifecycle_worker(self) -> dict[str, int]:
        task = self.celery_app.tasks["worker.grants.lifecycle.reconcile"]
        with mock.patch("apps.worker.tasks.session_scope", new=self._session_scope_override):
            return task.run()

    def run_revoke_worker(self, *, limit: int | None = 100) -> dict[str, int]:
        task = self.celery_app.tasks["worker.sessions.revoke.process_pending"]
        with mock.patch("apps.worker.tasks.session_scope", new=self._session_scope_override):
            return task.run(limit=limit)

    def latest_approval_for_request(self, request_id: str) -> ApprovalRecordRecord:
        with self.session() as session:
            record = session.scalar(
                select(ApprovalRecordRecord)
                .where(ApprovalRecordRecord.request_id == request_id)
                .order_by(ApprovalRecordRecord.created_at.desc())
            )
            if record is None:
                raise AssertionError(f"Missing approval record for request {request_id}")
            return record

    def _start_server(self, app) -> _RunningServer:
        port = _find_free_port()
        server = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
        )
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        base_url = f"http://127.0.0.1:{port}"
        _wait_for_server_ready(base_url)
        return _RunningServer(server=server, thread=thread, base_url=base_url)

    def _start_patchers(self) -> None:
        def permission_factory(*, now_provider=None):
            del now_provider
            return MockFeishuPermissionConnector(self.mock_base_url)

        def session_factory(*, now_provider=None):
            del now_provider
            return MockFeishuSessionConnector(self.mock_base_url)

        targets = [
            ("apps.api.grants.create_feishu_permission_connector", permission_factory),
            ("apps.api.grants.create_feishu_session_connector", session_factory),
            ("apps.api.sessions.create_feishu_session_connector", session_factory),
            ("apps.api.admin.create_feishu_permission_connector", permission_factory),
            ("apps.api.admin.create_feishu_session_connector", session_factory),
            ("apps.worker.tasks.create_feishu_permission_connector", permission_factory),
            ("apps.worker.tasks.create_feishu_session_connector", session_factory),
        ]
        for target, replacement in targets:
            patcher = mock.patch(target, new=replacement)
            patcher.start()
            self._patchers.append(patcher)

    @contextmanager
    def _session_scope_override(self, session_factory=None):
        del session_factory
        session = self.session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()
