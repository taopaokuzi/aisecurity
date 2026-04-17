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
from packages.application import default_grant_id_for_request
from packages.infrastructure import build_callback_signature
from packages.infrastructure.db import Base
from packages.infrastructure.db.models import (
    AccessGrantRecord,
    AgentIdentityRecord,
    ApprovalRecordRecord,
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
CALLBACK_SECRET = "test-approval-secret"


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


class ApprovalCallbackApiIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        ensure_test_database()
        os.environ["APPROVAL_CALLBACK_SECRET"] = CALLBACK_SECRET
        os.environ["APPROVAL_CALLBACK_ALLOWED_SOURCES"] = "127.0.0.1"
        os.environ["APPROVAL_CALLBACK_MAX_AGE_SECONDS"] = "300"

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

    def test_approval_callback_marks_request_approved(self) -> None:
        self._seed_pending_approval(
            request_id="req_approved_001",
            approval_id="apr_approved_001",
            external_approval_id="feishu_apr_approved_001",
        )

        status_code, payload = self._callback(
            request_id="cb_trace_001",
            body={
                "external_approval_id": "feishu_apr_approved_001",
                "request_id": "req_approved_001",
                "approval_status": "Approved",
                "approval_node": "manager",
                "approver_id": "user_mgr_001",
                "decision_at": "2026-04-17T10:05:00Z",
                "idempotency_key": "feishu_cb_approved_001",
                "payload": {"raw": "approved"},
            },
        )

        self.assertEqual(status_code, 200)
        self.assertEqual(payload["data"]["accepted"], True)
        self.assertEqual(payload["data"]["approval_status"], "Approved")

        with self.session_factory() as session:
            permission_request = session.get(PermissionRequestRecord, "req_approved_001")
            self.assertIsNotNone(permission_request)
            assert permission_request is not None
            self.assertEqual(permission_request.approval_status, "Approved")
            self.assertEqual(permission_request.request_status, "Provisioning")
            self.assertEqual(permission_request.grant_status, "Provisioning")
            self.assertEqual(permission_request.current_task_state, "Succeeded")

            approval_record = session.get(ApprovalRecordRecord, "apr_approved_001")
            self.assertIsNotNone(approval_record)
            assert approval_record is not None
            self.assertEqual(approval_record.approval_status, "Approved")
            self.assertEqual(approval_record.idempotency_key, "feishu_cb_approved_001")
            self.assertIsNotNone(approval_record.callback_payload_json)
            self.assertEqual(
                approval_record.callback_payload_json["body"]["approval_status"],
                "Approved",
            )

            grant_id = default_grant_id_for_request("req_approved_001")
            access_grant = session.get(AccessGrantRecord, grant_id)
            self.assertIsNotNone(access_grant)
            assert access_grant is not None
            self.assertEqual(access_grant.grant_status, "Provisioning")
            self.assertEqual(access_grant.connector_status, "Accepted")

            connector_tasks = session.scalars(
                select(ConnectorTaskRecord)
                .where(ConnectorTaskRecord.grant_id == grant_id)
            ).all()
            self.assertEqual(len(connector_tasks), 1)
            self.assertEqual(connector_tasks[0].task_status, "Succeeded")

            events = session.scalars(
                select(PermissionRequestEventRecord)
                .where(PermissionRequestEventRecord.request_id == "req_approved_001")
                .order_by(PermissionRequestEventRecord.created_at.asc())
            ).all()
            self.assertEqual(
                [event.event_type for event in events],
                ["approval.approved", "grant.provisioning_requested", "grant.accepted"],
            )

            audits = session.scalars(
                select(AuditRecordRecord)
                .where(AuditRecordRecord.request_id == "req_approved_001")
                .order_by(AuditRecordRecord.created_at.asc())
            ).all()
            self.assertCountEqual(
                [audit.event_type for audit in audits],
                [
                    "approval.callback_received",
                    "approval.approved",
                    "grant.provisioning_requested",
                    "grant.accepted",
                ],
            )

    def test_approval_callback_marks_request_failed_on_rejection(self) -> None:
        self._seed_pending_approval(
            request_id="req_rejected_001",
            approval_id="apr_rejected_001",
            external_approval_id="feishu_apr_rejected_001",
        )

        status_code, payload = self._callback(
            request_id="cb_trace_002",
            body={
                "external_approval_id": "feishu_apr_rejected_001",
                "request_id": "req_rejected_001",
                "approval_status": "Rejected",
                "approval_node": "manager",
                "approver_id": "user_mgr_002",
                "decision_at": "2026-04-17T10:06:00Z",
                "idempotency_key": "feishu_cb_rejected_001",
                "payload": {"raw": "rejected"},
            },
        )

        self.assertEqual(status_code, 200)
        self.assertEqual(payload["data"]["approval_status"], "Rejected")

        with self.session_factory() as session:
            permission_request = session.get(PermissionRequestRecord, "req_rejected_001")
            self.assertIsNotNone(permission_request)
            assert permission_request is not None
            self.assertEqual(permission_request.approval_status, "Rejected")
            self.assertEqual(permission_request.request_status, "Failed")
            self.assertEqual(permission_request.failed_reason, "Approval rejected")

            approval_record = session.get(ApprovalRecordRecord, "apr_rejected_001")
            self.assertIsNotNone(approval_record)
            assert approval_record is not None
            self.assertEqual(approval_record.approval_status, "Rejected")
            self.assertIsNotNone(approval_record.rejected_at)

            rejection_event = session.scalar(
                select(PermissionRequestEventRecord)
                .where(PermissionRequestEventRecord.request_id == "req_rejected_001")
                .where(PermissionRequestEventRecord.event_type == "approval.rejected")
            )
            self.assertIsNotNone(rejection_event)

    def test_duplicate_callback_is_idempotent(self) -> None:
        self._seed_pending_approval(
            request_id="req_duplicate_001",
            approval_id="apr_duplicate_001",
            external_approval_id="feishu_apr_duplicate_001",
        )
        callback_body = {
            "external_approval_id": "feishu_apr_duplicate_001",
            "request_id": "req_duplicate_001",
            "approval_status": "Approved",
            "approval_node": "manager",
            "approver_id": "user_mgr_003",
            "decision_at": "2026-04-17T10:07:00Z",
            "idempotency_key": "feishu_cb_duplicate_001",
            "payload": {"raw": "duplicate"},
        }

        first_status, _ = self._callback(request_id="cb_trace_003", body=callback_body)
        second_status, second_payload = self._callback(
            request_id="cb_trace_004",
            body=callback_body,
        )

        self.assertEqual(first_status, 200)
        self.assertEqual(second_status, 200)
        self.assertEqual(second_payload["data"]["accepted"], True)
        self.assertEqual(second_payload["data"]["approval_status"], "Approved")
        self.assertEqual(second_payload["data"]["duplicated"], True)

        with self.session_factory() as session:
            events = session.scalars(
                select(PermissionRequestEventRecord)
                .where(PermissionRequestEventRecord.request_id == "req_duplicate_001")
            ).all()
            self.assertEqual(len(events), 3)

            audits = session.scalars(
                select(AuditRecordRecord)
                .where(AuditRecordRecord.request_id == "req_duplicate_001")
            ).all()
            self.assertEqual(len(audits), 4)

            grant_id = default_grant_id_for_request("req_duplicate_001")
            connector_tasks = session.scalars(
                select(ConnectorTaskRecord)
                .where(ConnectorTaskRecord.grant_id == grant_id)
            ).all()
            self.assertEqual(len(connector_tasks), 1)

    def test_callback_rejects_invalid_signature(self) -> None:
        self._seed_pending_approval(
            request_id="req_signature_001",
            approval_id="apr_signature_001",
            external_approval_id="feishu_apr_signature_001",
        )
        body = {
            "external_approval_id": "feishu_apr_signature_001",
            "request_id": "req_signature_001",
            "approval_status": "Approved",
            "approval_node": "manager",
            "approver_id": "user_mgr_004",
            "decision_at": "2026-04-17T10:08:00Z",
            "idempotency_key": "feishu_cb_signature_001",
            "payload": {"raw": "invalid-signature"},
        }

        status_code, payload = self._callback(
            request_id="cb_trace_005",
            body=body,
            override_signature="invalid-signature",
        )

        self.assertEqual(status_code, 401)
        self.assertEqual(payload["error"]["code"], "CALLBACK_SIGNATURE_INVALID")

        with self.session_factory() as session:
            events = session.scalars(select(PermissionRequestEventRecord)).all()
            audits = session.scalars(select(AuditRecordRecord)).all()
            self.assertEqual(events, [])
            self.assertEqual(audits, [])

    def test_callback_returns_not_found_when_approval_missing(self) -> None:
        status_code, payload = self._callback(
            request_id="cb_trace_006",
            body={
                "external_approval_id": "feishu_apr_missing_001",
                "request_id": "req_missing_001",
                "approval_status": "Approved",
                "approval_node": "manager",
                "approver_id": "user_mgr_005",
                "decision_at": "2026-04-17T10:09:00Z",
                "idempotency_key": "feishu_cb_missing_001",
                "payload": {"raw": "missing"},
            },
        )

        self.assertEqual(status_code, 404)
        self.assertEqual(payload["error"]["code"], "APPROVAL_RECORD_NOT_FOUND")

    def _seed_pending_approval(
        self,
        *,
        request_id: str,
        approval_id: str,
        external_approval_id: str,
    ) -> None:
        now = datetime(2026, 4, 17, 10, 0, tzinfo=timezone.utc)
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
                    approval_status="Pending",
                    grant_status="NotCreated",
                    request_status="PendingApproval",
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
                ApprovalRecordRecord(
                    approval_id=approval_id,
                    request_id=request_id,
                    external_approval_id=external_approval_id,
                    approval_node="manager",
                    approver_id=None,
                    approval_status="Pending",
                    callback_payload_json=None,
                    idempotency_key=None,
                    submitted_at=now,
                    approved_at=None,
                    rejected_at=None,
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

    def _callback(
        self,
        *,
        request_id: str,
        body: dict[str, object],
        override_signature: str | None = None,
    ) -> tuple[int, dict[str, object]]:
        raw_body = json.dumps(body).encode("utf-8")
        timestamp = str(int(datetime.now(timezone.utc).timestamp()))
        signature = override_signature or build_callback_signature(
            secret=CALLBACK_SECRET,
            timestamp=timestamp,
            raw_body=raw_body,
        )
        headers = {
            "Content-Type": "application/json",
            "X-Feishu-Request-Id": request_id,
            "X-Feishu-Timestamp": timestamp,
            "X-Feishu-Signature": signature,
        }
        return self._request(
            "POST",
            "/approvals/callback",
            headers=headers,
            request_body=raw_body,
        )

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
        raise RuntimeError("Approval callback API test server did not become ready in time")


if __name__ == "__main__":
    unittest.main()
