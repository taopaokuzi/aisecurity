from __future__ import annotations

import json
import os
import socket
import threading
import time
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

import uvicorn
from sqlalchemy import create_engine, delete, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from apps.api.dependencies import get_db_session
from apps.api.main import create_app
from packages.infrastructure.db import Base
from packages.infrastructure.db.models import (
    AccessGrantRecord,
    AgentIdentityRecord,
    AuditRecordRecord,
    ConnectorTaskRecord,
    DelegationCredentialRecord,
    PermissionRequestEventRecord,
    PermissionRequestRecord,
    SessionContextRecord,
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


class SessionRevokeApiIntegrationTests(unittest.TestCase):
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
        os.environ["FEISHU_CONNECTOR_PROVIDER"] = "stub"
        os.environ["FEISHU_SESSION_REVOKE_STUB_MODE"] = "success"
        self._truncate_tables()
        self._seed_identity_data()
        self._seed_active_request_grant_and_session()

    def test_post_sessions_revoke_marks_session_revoking_and_creates_revoke_task(self) -> None:
        status_code, payload = self._request(
            "POST",
            "/sessions/revoke",
            headers=self._headers("req_trace_session_revoke_001"),
            request_body=json.dumps(
                {
                    "global_session_id": "gs_api_001",
                    "reason": "Agent disabled by security admin",
                    "cascade_connector_sessions": True,
                }
            ).encode("utf-8"),
        )

        self.assertEqual(status_code, 200)
        self.assertEqual(payload["data"]["global_session_id"], "gs_api_001")
        self.assertEqual(payload["data"]["session_status"], "Revoking")

        with self.session_factory() as session:
            session_context = session.get(SessionContextRecord, "gs_api_001")
            grant = session.get(AccessGrantRecord, "grt_api_001")
            request_record = session.get(PermissionRequestRecord, "req_api_001")
            self.assertIsNotNone(session_context)
            self.assertIsNotNone(grant)
            self.assertIsNotNone(request_record)
            assert session_context is not None
            assert grant is not None
            assert request_record is not None

            self.assertEqual(session_context.session_status, "Revoking")
            self.assertEqual(grant.grant_status, "Revoking")
            self.assertEqual(request_record.grant_status, "Revoking")
            self.assertEqual(request_record.current_task_state, "Running")

            revoke_tasks = session.scalars(
                select(ConnectorTaskRecord)
                .where(ConnectorTaskRecord.task_type == "session_revoke")
                .order_by(ConnectorTaskRecord.created_at.asc())
            ).all()
            self.assertEqual(len(revoke_tasks), 1)
            self.assertEqual(revoke_tasks[0].task_status, "Pending")
            self.assertEqual(revoke_tasks[0].payload_json["global_session_id"], "gs_api_001")

            events = session.scalars(
                select(PermissionRequestEventRecord)
                .where(PermissionRequestEventRecord.request_id == "req_api_001")
                .order_by(PermissionRequestEventRecord.created_at.asc())
            ).all()
            self.assertEqual(
                [event.event_type for event in events],
                ["session.revoke_requested"],
            )

            audits = session.scalars(
                select(AuditRecordRecord)
                .where(AuditRecordRecord.request_id == "req_api_001")
                .order_by(AuditRecordRecord.created_at.asc())
            ).all()
            self.assertEqual(
                [audit.event_type for audit in audits],
                ["session.revoke_requested"],
            )

    def _truncate_tables(self) -> None:
        with self.session_factory.begin() as session:
            for model in (
                AuditRecordRecord,
                ConnectorTaskRecord,
                PermissionRequestEventRecord,
                SessionContextRecord,
                AccessGrantRecord,
                PermissionRequestRecord,
                DelegationCredentialRecord,
                AgentIdentityRecord,
                UserRecord,
            ):
                session.execute(delete(model))

    def _seed_identity_data(self) -> None:
        now = datetime(2026, 4, 18, 0, 0, tzinfo=timezone.utc)
        with self.session_factory.begin() as session:
            session.add(
                UserRecord(
                    user_id="user_001",
                    employee_no="E001",
                    display_name="Alice",
                    email="alice@example.com",
                    department_id="dept_sales",
                    department_name="sales",
                    manager_user_id="user_mgr_root",
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

    def _seed_active_request_grant_and_session(self) -> None:
        now = datetime.now(timezone.utc)
        with self.session_factory.begin() as session:
            session.add(
                PermissionRequestRecord(
                    request_id="req_api_001",
                    user_id="user_001",
                    agent_id="agent_perm_assistant_v1",
                    delegation_id="dlg_123",
                    raw_text="我需要查看销售部 Q3 报表",
                    resource_key="sales.q3_report",
                    resource_type="report",
                    action="read",
                    constraints_json=None,
                    requested_duration="P7D",
                    structured_request_json={"approval_route": ["manager"]},
                    suggested_permission="report:sales.q3:read",
                    risk_level="Low",
                    approval_status="Approved",
                    grant_status="Active",
                    request_status="Active",
                    current_task_state="Succeeded",
                    policy_version="perm-map.v1",
                    renew_round=0,
                    failed_reason=None,
                    created_at=now,
                    updated_at=now,
                )
            )
            session.flush()
            session.add(
                AccessGrantRecord(
                    grant_id="grt_api_001",
                    request_id="req_api_001",
                    resource_key="sales.q3_report",
                    resource_type="report",
                    action="read",
                    grant_status="Active",
                    connector_status="Applied",
                    reconcile_status="Confirmed",
                    effective_at=now - timedelta(minutes=10),
                    expire_at=now + timedelta(days=7),
                    revoked_at=None,
                    revocation_reason=None,
                    created_at=now,
                    updated_at=now,
                )
            )
            session.flush()
            session.add(
                SessionContextRecord(
                    global_session_id="gs_api_001",
                    grant_id="grt_api_001",
                    request_id="req_api_001",
                    agent_id="agent_perm_assistant_v1",
                    user_id="user_001",
                    task_session_id="ctk_provision_001",
                    connector_session_ref="feishu_task_apply_001",
                    session_status="Active",
                    revocation_reason=None,
                    last_sync_at=now - timedelta(minutes=10),
                    revoked_at=None,
                    created_at=now,
                    updated_at=now,
                )
            )

    @staticmethod
    def _find_free_port() -> int:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", 0))
            sock.listen(1)
            return int(sock.getsockname()[1])

    @classmethod
    def _wait_for_server_ready(cls, timeout: float = 10.0) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(f"{cls.base_url}/health", timeout=1) as response:
                    if response.status == 200:
                        return
            except Exception:
                time.sleep(0.1)
        raise RuntimeError("API server did not become ready in time")

    def _headers(self, request_id: str) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "X-Request-Id": request_id,
            "X-User-Id": "sec_admin_001",
            "X-Operator-Type": "SecurityAdmin",
        }

    def _request(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str],
        request_body: bytes | None = None,
    ) -> tuple[int, dict[str, object]]:
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            method=method,
            headers=headers,
            data=request_body,
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))
                return response.status, payload
        except urllib.error.HTTPError as exc:
            payload = json.loads(exc.read().decode("utf-8"))
            return exc.code, payload


if __name__ == "__main__":
    unittest.main()
