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


class GrantProvisionApiIntegrationTests(unittest.TestCase):
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
        os.environ["FEISHU_CONNECTOR_STUB_MODE"] = "accepted"
        self._truncate_tables()
        self._seed_identity_data()

    def test_provision_endpoint_creates_grant_and_connector_task(self) -> None:
        self._seed_approved_request("req_grant_api_accepted_001")

        status_code, payload = self._request(
            "POST",
            "/grants/grt_grant_api_accepted_001/provision",
            headers=self._headers("req_trace_grant_001"),
            request_body=json.dumps(
                {
                    "request_id": "req_grant_api_accepted_001",
                    "policy_version": "perm-map.v1",
                    "delegation_id": "dlg_123",
                    "force_retry": False,
                }
            ).encode("utf-8"),
        )

        self.assertEqual(status_code, 200)
        self.assertEqual(payload["data"]["grant_status"], "Provisioning")
        self.assertEqual(payload["data"]["connector_status"], "Accepted")
        self.assertEqual(payload["data"]["request_status"], "Provisioning")

        with self.session_factory() as session:
            grant = session.get(AccessGrantRecord, "grt_grant_api_accepted_001")
            self.assertIsNotNone(grant)
            assert grant is not None
            self.assertEqual(grant.grant_status, "Provisioning")
            self.assertEqual(grant.connector_status, "Accepted")

            tasks = session.scalars(
                select(ConnectorTaskRecord)
                .where(ConnectorTaskRecord.grant_id == "grt_grant_api_accepted_001")
            ).all()
            self.assertEqual(len(tasks), 1)
            self.assertEqual(tasks[0].task_status, "Succeeded")

            events = session.scalars(
                select(PermissionRequestEventRecord)
                .where(PermissionRequestEventRecord.request_id == "req_grant_api_accepted_001")
                .order_by(PermissionRequestEventRecord.created_at.asc())
            ).all()
            self.assertEqual(
                [event.event_type for event in events],
                ["grant.provisioning_requested", "grant.accepted"],
            )

    def test_provision_endpoint_marks_grant_active_when_connector_applies(self) -> None:
        os.environ["FEISHU_CONNECTOR_STUB_MODE"] = "applied"
        self._seed_approved_request("req_grant_api_applied_001")

        status_code, payload = self._request(
            "POST",
            "/grants/grt_grant_api_applied_001/provision",
            headers=self._headers("req_trace_grant_002"),
            request_body=json.dumps(
                {
                    "request_id": "req_grant_api_applied_001",
                    "policy_version": "perm-map.v1",
                    "delegation_id": "dlg_123",
                    "force_retry": False,
                }
            ).encode("utf-8"),
        )

        self.assertEqual(status_code, 200)
        self.assertEqual(payload["data"]["grant_status"], "Active")
        self.assertEqual(payload["data"]["connector_status"], "Applied")
        self.assertEqual(payload["data"]["request_status"], "Active")
        self.assertIsNotNone(payload["data"]["effective_at"])

        with self.session_factory() as session:
            permission_request = session.get(PermissionRequestRecord, "req_grant_api_applied_001")
            self.assertIsNotNone(permission_request)
            assert permission_request is not None
            self.assertEqual(permission_request.request_status, "Active")
            self.assertEqual(permission_request.grant_status, "Active")

            audits = session.scalars(
                select(AuditRecordRecord)
                .where(AuditRecordRecord.request_id == "req_grant_api_applied_001")
                .order_by(AuditRecordRecord.created_at.asc())
            ).all()
            self.assertEqual(
                [audit.event_type for audit in audits],
                ["grant.provisioning_requested", "grant.provisioned"],
            )

    def test_provision_endpoint_persists_failed_writeback_when_connector_is_unavailable(self) -> None:
        os.environ["FEISHU_CONNECTOR_STUB_MODE"] = "bogus"
        self._seed_approved_request("req_grant_api_unavailable_001")

        status_code, payload = self._request(
            "POST",
            "/grants/grt_grant_api_unavailable_001/provision",
            headers=self._headers("req_trace_grant_003"),
            request_body=json.dumps(
                {
                    "request_id": "req_grant_api_unavailable_001",
                    "policy_version": "perm-map.v1",
                    "delegation_id": "dlg_123",
                    "force_retry": False,
                }
            ).encode("utf-8"),
        )

        self.assertEqual(status_code, 503)
        self.assertEqual(payload["error"]["code"], "CONNECTOR_UNAVAILABLE")

        with self.session_factory() as session:
            permission_request = session.get(
                PermissionRequestRecord,
                "req_grant_api_unavailable_001",
            )
            self.assertIsNotNone(permission_request)
            assert permission_request is not None
            self.assertEqual(permission_request.request_status, "Failed")
            self.assertEqual(permission_request.grant_status, "ProvisionFailed")
            self.assertEqual(permission_request.current_task_state, "Failed")
            self.assertIn(
                "Unsupported feishu connector stub mode: bogus",
                permission_request.failed_reason or "",
            )

            grant = session.get(AccessGrantRecord, "grt_grant_api_unavailable_001")
            self.assertIsNotNone(grant)
            assert grant is not None
            self.assertEqual(grant.grant_status, "ProvisionFailed")
            self.assertEqual(grant.connector_status, "Failed")
            self.assertEqual(grant.reconcile_status, "Error")

            tasks = session.scalars(
                select(ConnectorTaskRecord)
                .where(ConnectorTaskRecord.grant_id == "grt_grant_api_unavailable_001")
                .order_by(ConnectorTaskRecord.created_at.asc())
            ).all()
            self.assertEqual(len(tasks), 1)
            self.assertEqual(tasks[0].task_status, "Failed")
            self.assertEqual(tasks[0].last_error_code, "CONNECTOR_UNAVAILABLE")
            self.assertIn(
                "Unsupported feishu connector stub mode: bogus",
                tasks[0].last_error_message or "",
            )

            events = session.scalars(
                select(PermissionRequestEventRecord)
                .where(PermissionRequestEventRecord.request_id == "req_grant_api_unavailable_001")
                .order_by(PermissionRequestEventRecord.created_at.asc())
            ).all()
            self.assertEqual(
                [event.event_type for event in events],
                ["grant.provisioning_requested", "grant.provision_failed"],
            )

            audits = session.scalars(
                select(AuditRecordRecord)
                .where(AuditRecordRecord.request_id == "req_grant_api_unavailable_001")
                .order_by(AuditRecordRecord.created_at.asc())
            ).all()
            self.assertEqual(
                [audit.event_type for audit in audits],
                ["grant.provisioning_requested", "grant.provision_failed"],
            )
            self.assertEqual(audits[-1].result, "Fail")
            self.assertIn(
                "Unsupported feishu connector stub mode: bogus",
                audits[-1].reason or "",
            )

    def _seed_approved_request(self, request_id: str) -> None:
        now = datetime(2026, 4, 17, 12, 0, tzinfo=timezone.utc)
        with self.session_factory.begin() as session:
            session.add(
                PermissionRequestRecord(
                    request_id=request_id,
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
                    risk_level="Medium",
                    approval_status="Approved",
                    grant_status="NotCreated",
                    request_status="Approved",
                    current_task_state="Succeeded",
                    policy_version="perm-map.v1",
                    renew_round=0,
                    failed_reason=None,
                    created_at=now,
                    updated_at=now,
                )
            )

    def _truncate_tables(self) -> None:
        with self.session_factory.begin() as session:
            for model in (
                AuditRecordRecord,
                PermissionRequestEventRecord,
                ConnectorTaskRecord,
                AccessGrantRecord,
                PermissionRequestRecord,
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

    def _headers(self, request_id: str) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "X-Request-Id": request_id,
            "X-User-Id": "system_worker",
            "X-Operator-Type": "System",
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
            url=f"{self.base_url}{path}",
            data=request_body,
            headers=headers,
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
        raise RuntimeError("Grant provision API test server did not become ready in time")


if __name__ == "__main__":
    unittest.main()
