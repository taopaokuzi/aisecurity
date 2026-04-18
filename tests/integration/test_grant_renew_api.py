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
    ApprovalRecordRecord,
    AuditRecordRecord,
    DelegationCredentialRecord,
    NotificationTaskRecord,
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


class GrantRenewApiIntegrationTests(unittest.TestCase):
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

    def test_post_grant_renew_creates_follow_up_request(self) -> None:
        self._seed_active_request_and_grant()

        status_code, payload = self._request(
            "POST",
            "/grants/grt_renew_api_001/renew",
            headers=self._headers("req_trace_grant_renew_001"),
            request_body=json.dumps(
                {
                    "requested_duration": "P7D",
                    "reason": "项目仍在进行，需要继续查看",
                }
            ).encode("utf-8"),
        )

        self.assertEqual(status_code, 200)
        self.assertEqual(payload["data"]["grant_id"], "grt_renew_api_001")
        self.assertEqual(payload["data"]["renew_round"], 1)
        self.assertEqual(payload["data"]["request_status"], "PendingApproval")

        with self.session_factory() as session:
            requests = session.scalars(
                select(PermissionRequestRecord).order_by(PermissionRequestRecord.created_at.asc())
            ).all()
            self.assertEqual(len(requests), 2)

            renewal_request = requests[-1]
            renewal_context = renewal_request.structured_request_json["renewal_context"]
            self.assertEqual(renewal_request.request_status, "PendingApproval")
            self.assertEqual(renewal_request.grant_status, "Active")
            self.assertEqual(renewal_request.renew_round, 1)
            self.assertEqual(renewal_context["grant_id"], "grt_renew_api_001")
            self.assertEqual(renewal_context["source_request_id"], "req_renew_api_001")
            self.assertEqual(renewal_context["root_request_id"], "req_renew_api_001")
            self.assertEqual(renewal_context["requested_duration"], "P7D")

            approval_record = session.scalar(
                select(ApprovalRecordRecord)
                .where(ApprovalRecordRecord.request_id == renewal_request.request_id)
                .order_by(ApprovalRecordRecord.created_at.desc())
            )
            self.assertIsNotNone(approval_record)
            assert approval_record is not None
            self.assertEqual(approval_record.request_id, renewal_request.request_id)
            self.assertEqual(approval_record.approval_status, "Pending")
            self.assertEqual(approval_record.approval_node, "manager")
            self.assertTrue(approval_record.external_approval_id.startswith("feishu_apr_"))

            events = session.scalars(
                select(PermissionRequestEventRecord)
                .order_by(PermissionRequestEventRecord.created_at.asc())
            ).all()
            self.assertEqual(
                [event.event_type for event in events],
                ["grant.renew_requested", "grant.renew_requested", "approval.required"],
            )
            approval_event = events[-1]
            self.assertEqual(approval_event.request_id, renewal_request.request_id)
            self.assertEqual(
                approval_event.metadata_json["approval_id"],
                approval_record.approval_id,
            )

            approval_audit = session.scalar(
                select(AuditRecordRecord)
                .where(AuditRecordRecord.request_id == renewal_request.request_id)
                .where(AuditRecordRecord.event_type == "approval.required")
            )
            self.assertIsNotNone(approval_audit)
            assert approval_audit is not None
            self.assertEqual(
                approval_audit.metadata_json["approval_id"],
                approval_record.approval_id,
            )

    def test_post_grant_renew_rolls_back_when_approval_submission_fails(self) -> None:
        self._seed_active_request_and_grant(structured_request_json={})

        status_code, payload = self._request(
            "POST",
            "/grants/grt_renew_api_001/renew",
            headers=self._headers("req_trace_grant_renew_002"),
            request_body=json.dumps(
                {
                    "requested_duration": "P7D",
                    "reason": "项目仍在进行，需要继续查看",
                }
            ).encode("utf-8"),
        )

        self.assertEqual(status_code, 409)
        self.assertEqual(payload["error"]["code"], "REQUEST_STATUS_INVALID")

        with self.session_factory() as session:
            requests = session.scalars(
                select(PermissionRequestRecord).order_by(PermissionRequestRecord.created_at.asc())
            ).all()
            self.assertEqual(len(requests), 1)
            self.assertEqual(requests[0].request_id, "req_renew_api_001")
            self.assertEqual(requests[0].request_status, "Active")

            approval_records = session.scalars(select(ApprovalRecordRecord)).all()
            self.assertEqual(approval_records, [])

            renew_events = session.scalars(
                select(PermissionRequestEventRecord).where(
                    PermissionRequestEventRecord.event_type == "grant.renew_requested"
                )
            ).all()
            self.assertEqual(renew_events, [])

            approval_events = session.scalars(
                select(PermissionRequestEventRecord).where(
                    PermissionRequestEventRecord.event_type == "approval.required"
                )
            ).all()
            self.assertEqual(approval_events, [])

            approval_audits = session.scalars(
                select(AuditRecordRecord).where(
                    AuditRecordRecord.event_type.in_(["grant.renew_requested", "approval.required"])
                )
            ).all()
            self.assertEqual(approval_audits, [])

    def _truncate_tables(self) -> None:
        with self.session_factory.begin() as session:
            for model in (
                AuditRecordRecord,
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

    def _seed_active_request_and_grant(
        self,
        *,
        structured_request_json: dict[str, object] | None = None,
    ) -> None:
        now = datetime(2026, 4, 17, 9, 0, tzinfo=timezone.utc)
        request_payload = structured_request_json
        if request_payload is None:
            request_payload = {"approval_route": ["manager"]}
        with self.session_factory.begin() as session:
            session.add(
                PermissionRequestRecord(
                    request_id="req_renew_api_001",
                    user_id="user_001",
                    agent_id="agent_perm_assistant_v1",
                    delegation_id="dlg_123",
                    raw_text="我需要查看销售部Q3报表",
                    resource_key="sales.q3_report",
                    resource_type="report",
                    action="read",
                    constraints_json=None,
                    requested_duration="P7D",
                    structured_request_json=request_payload,
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
                    grant_id="grt_renew_api_001",
                    request_id="req_renew_api_001",
                    resource_key="sales.q3_report",
                    resource_type="report",
                    action="read",
                    grant_status="Active",
                    connector_status="Applied",
                    reconcile_status="Confirmed",
                    effective_at=now,
                    expire_at=now + timedelta(days=3),
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
            "X-User-Id": "user_001",
            "X-Operator-Type": "User",
            "Idempotency-Key": "renew-key-api-001",
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
        raise RuntimeError("Grant renew API test server did not become ready in time")


if __name__ == "__main__":
    unittest.main()
