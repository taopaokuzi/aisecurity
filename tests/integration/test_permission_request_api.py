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
    AgentIdentityRecord,
    AuditRecordRecord,
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


class PermissionRequestApiIntegrationTests(unittest.TestCase):
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

    def test_post_permission_requests_creates_record_event_and_audit(self) -> None:
        status_code, payload = self._request(
            "POST",
            "/permission-requests",
            headers=self._headers("req_trace_201"),
            json_body={
                "message": "我需要查看销售部Q3报表",
                "agent_id": "agent_perm_assistant_v1",
                "delegation_id": "dlg_123",
                "conversation_id": "conv_001",
            },
        )

        self.assertEqual(status_code, 200)
        permission_request_id = payload["data"]["permission_request_id"]
        self.assertTrue(permission_request_id.startswith("req_"))
        self.assertEqual(payload["data"]["request_status"], "Submitted")
        self.assertEqual(payload["data"]["next_action"], "Evaluating")

        with self.session_factory() as session:
            permission_request = session.get(PermissionRequestRecord, permission_request_id)
            self.assertIsNotNone(permission_request)
            assert permission_request is not None
            self.assertEqual(permission_request.user_id, "user_001")
            self.assertEqual(permission_request.agent_id, "agent_perm_assistant_v1")
            self.assertEqual(permission_request.delegation_id, "dlg_123")
            self.assertEqual(permission_request.raw_text, "我需要查看销售部Q3报表")
            self.assertEqual(permission_request.request_status, "Submitted")
            self.assertEqual(permission_request.approval_status, "NotRequired")
            self.assertEqual(permission_request.grant_status, "NotCreated")

            event_record = session.scalar(
                select(PermissionRequestEventRecord)
                .where(PermissionRequestEventRecord.request_id == permission_request_id)
                .order_by(PermissionRequestEventRecord.occurred_at.desc())
            )
            self.assertIsNotNone(event_record)
            assert event_record is not None
            self.assertEqual(event_record.event_type, "request.submitted")
            self.assertEqual(event_record.to_request_status, "Submitted")

            audit_record = session.scalar(
                select(AuditRecordRecord)
                .where(AuditRecordRecord.request_id == permission_request_id)
                .order_by(AuditRecordRecord.created_at.desc())
            )
            self.assertIsNotNone(audit_record)
            assert audit_record is not None
            self.assertEqual(audit_record.event_type, "request.submitted")
            self.assertEqual(audit_record.actor_id, "user_001")

    def test_post_permission_requests_rejects_invalid_delegation(self) -> None:
        status_code, payload = self._request(
            "POST",
            "/permission-requests",
            headers=self._headers("req_trace_202"),
            json_body={
                "message": "我需要查看销售部Q3报表",
                "agent_id": "agent_perm_assistant_v1",
                "delegation_id": "dlg_missing",
            },
        )

        self.assertEqual(status_code, 404)
        self.assertEqual(payload["error"]["code"], "DELEGATION_INVALID")

    def test_post_permission_requests_rejects_empty_message(self) -> None:
        status_code, payload = self._request(
            "POST",
            "/permission-requests",
            headers=self._headers("req_trace_203"),
            json_body={
                "message": "   ",
                "agent_id": "agent_perm_assistant_v1",
                "delegation_id": "dlg_123",
            },
        )

        self.assertEqual(status_code, 400)
        self.assertEqual(payload["error"]["code"], "REQUEST_MESSAGE_EMPTY")

    def test_get_permission_request_returns_existing_record(self) -> None:
        _, create_payload = self._request(
            "POST",
            "/permission-requests",
            headers=self._headers("req_trace_204"),
            json_body={
                "message": "我需要查看销售部Q3报表",
                "agent_id": "agent_perm_assistant_v1",
                "delegation_id": "dlg_123",
            },
        )
        permission_request_id = create_payload["data"]["permission_request_id"]

        status_code, payload = self._request(
            "GET",
            f"/permission-requests/{permission_request_id}",
            headers=self._headers("req_trace_205"),
        )

        self.assertEqual(status_code, 200)
        self.assertEqual(payload["data"]["request_id"], permission_request_id)
        self.assertEqual(payload["data"]["user_id"], "user_001")
        self.assertEqual(payload["data"]["agent_id"], "agent_perm_assistant_v1")
        self.assertEqual(payload["data"]["delegation_id"], "dlg_123")
        self.assertEqual(payload["data"]["request_status"], "Submitted")
        self.assertEqual(payload["data"]["approval_status"], "NotRequired")
        self.assertEqual(payload["data"]["grant_status"], "NotCreated")

    def test_get_permission_requests_supports_pagination_and_filters(self) -> None:
        now = datetime(2026, 4, 17, 9, 0, tzinfo=timezone.utc)
        with self.session_factory.begin() as session:
            session.add(
                UserRecord(
                    user_id="user_002",
                    employee_no="E002",
                    display_name="Bob",
                    email="bob@example.com",
                    department_id="dept_002",
                    department_name="Finance",
                    manager_user_id=None,
                    user_status="Active",
                    identity_source="SSO",
                    created_at=now,
                    updated_at=now,
                )
            )
            session.flush()
            session.add(
                DelegationCredentialRecord(
                    delegation_id="dlg_456",
                    user_id="user_002",
                    agent_id="agent_perm_assistant_v1",
                    task_scope="permission_self_service",
                    scope_json={
                        "resource_types": ["report"],
                        "allowed_actions": ["read"],
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
            session.flush()
            session.add_all(
                [
                    PermissionRequestRecord(
                        request_id="req_001",
                        user_id="user_001",
                        agent_id="agent_perm_assistant_v1",
                        delegation_id="dlg_123",
                        raw_text="申请一",
                        resource_key=None,
                        resource_type=None,
                        action=None,
                        constraints_json=None,
                        requested_duration=None,
                        structured_request_json=None,
                        suggested_permission=None,
                        risk_level=None,
                        approval_status="NotRequired",
                        grant_status="NotCreated",
                        request_status="Submitted",
                        current_task_state=None,
                        policy_version=None,
                        renew_round=0,
                        failed_reason=None,
                        created_at=now,
                        updated_at=now,
                    ),
                    PermissionRequestRecord(
                        request_id="req_002",
                        user_id="user_001",
                        agent_id="agent_perm_assistant_v1",
                        delegation_id="dlg_123",
                        raw_text="申请二",
                        resource_key=None,
                        resource_type=None,
                        action=None,
                        constraints_json=None,
                        requested_duration=None,
                        structured_request_json=None,
                        suggested_permission=None,
                        risk_level=None,
                        approval_status="NotRequired",
                        grant_status="NotCreated",
                        request_status="Submitted",
                        current_task_state=None,
                        policy_version=None,
                        renew_round=0,
                        failed_reason=None,
                        created_at=now + timedelta(minutes=1),
                        updated_at=now + timedelta(minutes=1),
                    ),
                    PermissionRequestRecord(
                        request_id="req_003",
                        user_id="user_001",
                        agent_id="agent_perm_assistant_v1",
                        delegation_id="dlg_123",
                        raw_text="申请三",
                        resource_key=None,
                        resource_type=None,
                        action=None,
                        constraints_json=None,
                        requested_duration=None,
                        structured_request_json=None,
                        suggested_permission=None,
                        risk_level=None,
                        approval_status="NotRequired",
                        grant_status="NotCreated",
                        request_status="Submitted",
                        current_task_state=None,
                        policy_version=None,
                        renew_round=0,
                        failed_reason=None,
                        created_at=now + timedelta(minutes=2),
                        updated_at=now + timedelta(minutes=2),
                    ),
                    PermissionRequestRecord(
                        request_id="req_pending_001",
                        user_id="user_001",
                        agent_id="agent_perm_assistant_v1",
                        delegation_id="dlg_123",
                        raw_text="待审批申请",
                        resource_key="sales.q3_report",
                        resource_type="report",
                        action="read",
                        constraints_json=None,
                        requested_duration=None,
                        structured_request_json=None,
                        suggested_permission="report:sales.q3:read",
                        risk_level="Low",
                        approval_status="Pending",
                        grant_status="NotCreated",
                        request_status="PendingApproval",
                        current_task_state=None,
                        policy_version="perm-map.v1",
                        renew_round=0,
                        failed_reason=None,
                        created_at=now + timedelta(minutes=3),
                        updated_at=now + timedelta(minutes=3),
                    ),
                    PermissionRequestRecord(
                        request_id="req_other_user_001",
                        user_id="user_002",
                        agent_id="agent_perm_assistant_v1",
                        delegation_id="dlg_456",
                        raw_text="其他人的申请",
                        resource_key=None,
                        resource_type=None,
                        action=None,
                        constraints_json=None,
                        requested_duration=None,
                        structured_request_json=None,
                        suggested_permission=None,
                        risk_level=None,
                        approval_status="NotRequired",
                        grant_status="NotCreated",
                        request_status="Submitted",
                        current_task_state=None,
                        policy_version=None,
                        renew_round=0,
                        failed_reason=None,
                        created_at=now + timedelta(minutes=4),
                        updated_at=now + timedelta(minutes=4),
                    ),
                ]
            )

        status_code, payload = self._request(
            "GET",
            "/permission-requests?page=2&page_size=2&request_status=Submitted&approval_status=NotRequired",
            headers=self._headers("req_trace_206"),
        )

        self.assertEqual(status_code, 200)
        self.assertEqual(payload["data"]["page"], 2)
        self.assertEqual(payload["data"]["page_size"], 2)
        self.assertEqual(payload["data"]["total"], 3)
        self.assertEqual(len(payload["data"]["items"]), 1)
        self.assertEqual(payload["data"]["items"][0]["user_id"], "user_001")
        self.assertEqual(payload["data"]["items"][0]["request_status"], "Submitted")
        self.assertEqual(payload["data"]["items"][0]["approval_status"], "NotRequired")

    def _truncate_tables(self) -> None:
        with self.session_factory.begin() as session:
            for model in (
                AuditRecordRecord,
                PermissionRequestEventRecord,
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
        raise RuntimeError("Permission request API test server did not become ready in time")


if __name__ == "__main__":
    unittest.main()
