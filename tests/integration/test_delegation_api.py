from __future__ import annotations

import json
import os
import socket
import threading
import time
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timezone

from sqlalchemy import create_engine, delete, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker
import uvicorn

from apps.api.dependencies import get_db_session
from apps.api.main import create_app
from packages.infrastructure.db import Base
from packages.infrastructure.db.models import (
    AgentIdentityRecord,
    AuditRecordRecord,
    DelegationCredentialRecord,
    UserRecord,
)

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+psycopg://aisecurity:aisecurity@postgres:5432/aisecurity_test",
)
ADMIN_DATABASE_URL = os.getenv(
    "TEST_ADMIN_DATABASE_URL",
    "postgresql+psycopg://aisecurity:aisecurity@postgres:5432/postgres",
)


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


class DelegationApiIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_test_database()
        cls.engine = create_engine(TEST_DATABASE_URL, future=True)
        cls.session_factory = sessionmaker(
            bind=cls.engine,
            autoflush=False,
            expire_on_commit=False,
            class_=Session,
        )
        Base.metadata.drop_all(cls.engine)
        Base.metadata.create_all(cls.engine)
        cls.app = create_app()

        def override_get_db_session():
            session = cls.session_factory()
            try:
                yield session
                session.commit()
            except Exception:
                session.rollback()
                raise
            finally:
                session.close()

        cls.app.dependency_overrides[get_db_session] = override_get_db_session
        cls.port = cls._find_free_port()
        cls.server = uvicorn.Server(
            uvicorn.Config(
                cls.app,
                host="127.0.0.1",
                port=cls.port,
                log_level="warning",
            )
        )
        cls.server_thread = threading.Thread(target=cls.server.run, daemon=True)
        cls.server_thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.port}"
        cls._wait_for_server_ready()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.should_exit = True
        cls.server_thread.join(timeout=5)
        cls.app.dependency_overrides.clear()
        cls.engine.dispose()

    def setUp(self) -> None:
        self._truncate_tables()
        self._seed_identity_data()

    def test_post_delegations_creates_record_and_audit_event(self) -> None:
        status_code, payload = self._request(
            "POST",
            "/delegations",
            headers=self._headers("req_trace_101"),
            json_body={
                "agent_id": "agent_perm_assistant_v1",
                "task_scope": "permission_self_service",
                "scope": {
                    "resource_types": ["report", "doc"],
                    "allowed_actions": ["read", "request_edit"],
                },
                "expire_at": "2026-04-24T09:20:00Z",
            },
        )

        self.assertEqual(status_code, 200)
        delegation_id = payload["data"]["delegation_id"]
        self.assertTrue(delegation_id.startswith("dlg_"))
        self.assertEqual(payload["data"]["delegation_status"], "Active")

        with self.session_factory() as session:
            delegation = session.get(DelegationCredentialRecord, delegation_id)
            self.assertIsNotNone(delegation)
            assert delegation is not None
            self.assertEqual(delegation.user_id, "user_001")
            self.assertEqual(delegation.agent_id, "agent_perm_assistant_v1")
            self.assertEqual(delegation.delegation_status, "Active")
            self.assertEqual(
                delegation.scope_json,
                {
                    "resource_types": ["report", "doc"],
                    "allowed_actions": ["read", "request_edit"],
                },
            )

            audit_record = session.scalar(
                select(AuditRecordRecord)
                .where(AuditRecordRecord.event_type == "delegation.created")
                .order_by(AuditRecordRecord.created_at.desc())
            )
            self.assertIsNotNone(audit_record)
            assert audit_record is not None
            self.assertEqual(audit_record.actor_id, "user_001")
            self.assertEqual(audit_record.metadata_json["delegation_id"], delegation_id)

    def test_post_delegations_rejects_disabled_agent(self) -> None:
        with self.session_factory.begin() as session:
            agent = session.get(AgentIdentityRecord, "agent_perm_assistant_v1")
            assert agent is not None
            agent.agent_status = "Disabled"

        status_code, payload = self._request(
            "POST",
            "/delegations",
            headers=self._headers("req_trace_102"),
            json_body={
                "agent_id": "agent_perm_assistant_v1",
                "task_scope": "permission_self_service",
                "scope": {
                    "resource_types": ["report"],
                    "allowed_actions": ["read"],
                },
                "expire_at": "2026-04-24T09:20:00Z",
            },
        )

        self.assertEqual(status_code, 409)
        self.assertEqual(payload["error"]["code"], "AGENT_DISABLED")

    def test_post_delegations_rejects_invalid_expire_at(self) -> None:
        status_code, payload = self._request(
            "POST",
            "/delegations",
            headers=self._headers("req_trace_103"),
            json_body={
                "agent_id": "agent_perm_assistant_v1",
                "task_scope": "permission_self_service",
                "scope": {
                    "resource_types": ["report"],
                    "allowed_actions": ["read"],
                },
                "expire_at": "2026-04-16T09:20:00Z",
            },
        )

        self.assertEqual(status_code, 400)
        self.assertEqual(payload["error"]["code"], "DELEGATION_EXPIRE_AT_INVALID")

    def test_get_delegation_returns_existing_record(self) -> None:
        _, create_payload = self._request(
            "POST",
            "/delegations",
            headers=self._headers("req_trace_104"),
            json_body={
                "agent_id": "agent_perm_assistant_v1",
                "task_scope": "permission_self_service",
                "scope": {
                    "resource_types": ["report"],
                    "allowed_actions": ["read"],
                },
                "expire_at": "2026-04-24T09:20:00Z",
            },
        )
        delegation_id = create_payload["data"]["delegation_id"]

        status_code, payload = self._request(
            "GET",
            f"/delegations/{delegation_id}",
            headers=self._headers("req_trace_105"),
        )

        self.assertEqual(status_code, 200)
        self.assertEqual(payload["data"]["delegation_id"], delegation_id)
        self.assertEqual(payload["data"]["user_id"], "user_001")
        self.assertEqual(payload["data"]["agent_id"], "agent_perm_assistant_v1")
        self.assertEqual(payload["data"]["task_scope"], "permission_self_service")
        self.assertEqual(payload["data"]["delegation_status"], "Active")

    def _truncate_tables(self) -> None:
        with self.session_factory.begin() as session:
            for model in (
                AuditRecordRecord,
                DelegationCredentialRecord,
                AgentIdentityRecord,
                UserRecord,
            ):
                session.execute(delete(model))

    def _seed_identity_data(self) -> None:
        now = datetime(2026, 4, 17, 8, 0, tzinfo=timezone.utc)
        with self.session_factory.begin() as session:
            session.add(
                UserRecord(
                    user_id="user_001",
                    employee_no="E001",
                    display_name="Alice",
                    email="alice@example.com",
                    department_id="dept_001",
                    department_name="Security",
                    manager_user_id=None,
                    user_status="Active",
                    identity_source="SSO",
                    created_at=now,
                    updated_at=now,
                )
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

    def _headers(self, request_id: str) -> dict[str, str]:
        return {
            "X-Request-Id": request_id,
            "X-User-Id": "user_001",
        }

    def _request(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str],
        json_body: dict[str, object] | None = None,
    ) -> tuple[int, dict[str, object]]:
        request_headers = dict(headers)
        request_data: bytes | None = None
        if json_body is not None:
            request_headers["Content-Type"] = "application/json"
            request_data = json.dumps(json_body).encode("utf-8")

        request = urllib.request.Request(
            url=f"{self.base_url}{path}",
            data=request_data,
            headers=request_headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read().decode("utf-8"))

    @classmethod
    def _find_free_port(cls) -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            return sock.getsockname()[1]

    @classmethod
    def _wait_for_server_ready(cls) -> None:
        deadline = time.time() + 10
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(f"{cls.base_url}/health", timeout=1) as response:
                    if response.status == 200:
                        return
            except Exception:
                time.sleep(0.1)
        raise RuntimeError("Delegation API test server did not become ready in time")


if __name__ == "__main__":
    unittest.main()
