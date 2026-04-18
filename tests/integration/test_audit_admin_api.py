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
    ConnectorTaskRecord,
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


class AuditAdminApiIntegrationTests(unittest.TestCase):
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
        os.environ["FEISHU_SESSION_REVOKE_STUB_MODE"] = "success"
        self._truncate_tables()
        self._seed_identity_data()

    def test_get_audit_records_returns_single_request_chain(self) -> None:
        self._seed_audit_chain()

        status_code, payload = self._request(
            "GET",
            "/audit-records?request_id=req_audit_chain_001",
            headers=self._headers("req_trace_audit_chain_001", operator_type="SecurityAdmin"),
        )

        self.assertEqual(status_code, 200)
        self.assertEqual(payload["data"]["total"], 3)
        self.assertEqual(payload["data"]["page"], 1)
        self.assertEqual(payload["data"]["page_size"], 20)

        items = payload["data"]["items"]
        self.assertEqual(
            [item["event_type"] for item in items],
            ["grant.provisioned", "approval.approved", "request.submitted"],
        )
        self.assertEqual(items[0]["request"]["request_id"], "req_audit_chain_001")
        self.assertEqual(items[0]["grant"]["grant_id"], "grt_audit_chain_001")
        self.assertEqual(items[0]["connector_task"]["task_id"], "ctk_audit_chain_001")
        self.assertEqual(items[0]["session_context"]["global_session_id"], "gs_audit_chain_001")
        self.assertEqual(items[1]["approval_record"]["approval_id"], "apr_audit_chain_001")

    def test_get_audit_records_supports_pagination(self) -> None:
        self._seed_paginated_audits(total=25)

        status_code, payload = self._request(
            "GET",
            "/audit-records?event_type=grant.provisioned&actor_type=System&actor_id=worker_audit&page=2&page_size=10",
            headers=self._headers("req_trace_audit_page_001", operator_type="ITAdmin"),
        )

        self.assertEqual(status_code, 200)
        self.assertEqual(payload["data"]["total"], 25)
        self.assertEqual(payload["data"]["page"], 2)
        self.assertEqual(payload["data"]["page_size"], 10)
        self.assertEqual(len(payload["data"]["items"]), 10)
        self.assertTrue(all(item["event_type"] == "grant.provisioned" for item in payload["data"]["items"]))
        self.assertEqual(payload["data"]["items"][0]["request_id"], "req_audit_page_014")
        self.assertEqual(payload["data"]["items"][-1]["request_id"], "req_audit_page_005")

    def test_get_failed_tasks_lists_connector_and_callback_failures(self) -> None:
        self._seed_failed_provision_task()
        self._seed_failed_session_task()
        self._seed_callback_failed_record()

        status_code, payload = self._request(
            "GET",
            "/admin/failed-tasks?page=1&page_size=10",
            headers=self._headers("req_trace_failed_tasks_001", operator_type="ITAdmin"),
        )

        self.assertEqual(status_code, 200)
        self.assertEqual(payload["data"]["total"], 3)
        task_types = {item["task_type"] for item in payload["data"]["items"]}
        self.assertEqual(task_types, {"provision", "session_revoke", "approval_callback"})

        provision_item = next(
            item for item in payload["data"]["items"] if item["task_type"] == "provision"
        )
        self.assertTrue(provision_item["retryable"])
        self.assertEqual(provision_item["grant"]["grant_id"], "grt_failed_provision_001")

        status_code, filtered_payload = self._request(
            "GET",
            "/admin/failed-tasks?task_type=provision&request_id=req_failed_provision_001",
            headers=self._headers("req_trace_failed_tasks_002", operator_type="ITAdmin"),
        )

        self.assertEqual(status_code, 200)
        self.assertEqual(filtered_payload["data"]["total"], 1)
        self.assertEqual(filtered_payload["data"]["items"][0]["task_id"], "ctk_failed_provision_001")

    def test_retry_connector_task_retries_allowed_failed_task(self) -> None:
        self._seed_failed_provision_task()
        os.environ["FEISHU_CONNECTOR_STUB_MODE"] = "applied"

        status_code, payload = self._request(
            "POST",
            "/admin/connector-tasks/ctk_failed_provision_001/retry",
            headers=self._headers("req_trace_retry_allow_001", operator_type="ITAdmin"),
            json_body={"reason": "Manual retry after connector recovery"},
        )

        self.assertEqual(status_code, 200)
        self.assertEqual(payload["data"]["original_task_id"], "ctk_failed_provision_001")
        self.assertNotEqual(payload["data"]["retry_task_id"], "ctk_failed_provision_001")
        self.assertEqual(payload["data"]["task_type"], "provision")
        self.assertEqual(payload["data"]["task_status"], "Succeeded")
        self.assertEqual(payload["data"]["request_status"], "Active")
        self.assertEqual(payload["data"]["grant_status"], "Active")

        with self.session_factory() as session:
            request_record = session.get(PermissionRequestRecord, "req_failed_provision_001")
            grant_record = session.get(AccessGrantRecord, "grt_failed_provision_001")
            tasks = session.scalars(
                select(ConnectorTaskRecord)
                .where(ConnectorTaskRecord.grant_id == "grt_failed_provision_001")
                .order_by(ConnectorTaskRecord.created_at.asc())
            ).all()
            audits = session.scalars(
                select(AuditRecordRecord)
                .where(AuditRecordRecord.request_id == "req_failed_provision_001")
                .order_by(AuditRecordRecord.created_at.asc())
            ).all()

            self.assertIsNotNone(request_record)
            self.assertIsNotNone(grant_record)
            assert request_record is not None
            assert grant_record is not None
            self.assertEqual(request_record.request_status, "Active")
            self.assertEqual(grant_record.grant_status, "Active")
            self.assertEqual(len(tasks), 2)
            task_by_id = {task.task_id: task for task in tasks}
            self.assertEqual(task_by_id["ctk_failed_provision_001"].task_status, "Failed")
            self.assertEqual(
                task_by_id[payload["data"]["retry_task_id"]].task_status,
                "Succeeded",
            )
            self.assertEqual(task_by_id[payload["data"]["retry_task_id"]].retry_count, 1)
            self.assertIn("connector.retry_requested", [audit.event_type for audit in audits])
            self.assertIn("grant.retry_requested", [audit.event_type for audit in audits])

    def test_retry_connector_task_rejects_non_retryable_task(self) -> None:
        self._seed_succeeded_provision_task()

        status_code, payload = self._request(
            "POST",
            "/admin/connector-tasks/ctk_succeeded_provision_001/retry",
            headers=self._headers("req_trace_retry_deny_001", operator_type="ITAdmin"),
            json_body={"reason": "Should be rejected"},
        )

        self.assertEqual(status_code, 409)
        self.assertEqual(payload["error"]["code"], "RETRY_NOT_ALLOWED")

        with self.session_factory() as session:
            audits = session.scalars(
                select(AuditRecordRecord)
                .where(AuditRecordRecord.request_id == "req_succeeded_provision_001")
                .where(AuditRecordRecord.event_type == "connector.retry_requested")
                .order_by(AuditRecordRecord.created_at.asc())
            ).all()
            self.assertEqual(len(audits), 1)
            self.assertEqual(audits[0].result, "Denied")
            self.assertEqual(audits[0].actor_id, "it_admin_001")
            self.assertIn("Only failed provision tasks can be retried", audits[0].reason or "")

    def _seed_identity_data(self) -> None:
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
                        department_name="sales",
                        manager_user_id="user_mgr_root",
                        user_status="Active",
                        identity_source="SSO",
                        created_at=now,
                        updated_at=now,
                    ),
                    UserRecord(
                        user_id="it_admin_001",
                        employee_no="E900",
                        display_name="IT Admin",
                        email="it-admin@example.com",
                        department_id="dept_it",
                        department_name="it",
                        manager_user_id="user_mgr_root",
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

    def _seed_audit_chain(self) -> None:
        created_at = datetime(2026, 4, 18, 1, 0, tzinfo=timezone.utc)
        with self.session_factory.begin() as session:
            session.add(
                PermissionRequestRecord(
                    request_id="req_audit_chain_001",
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
                    grant_status="Active",
                    request_status="Active",
                    current_task_state="Succeeded",
                    policy_version="perm-map.v1",
                    renew_round=0,
                    failed_reason=None,
                    created_at=created_at,
                    updated_at=created_at + timedelta(minutes=10),
                )
            )
            session.flush()
            session.add(
                ApprovalRecordRecord(
                    approval_id="apr_audit_chain_001",
                    request_id="req_audit_chain_001",
                    external_approval_id="fs_audit_chain_001",
                    approval_node="manager",
                    approver_id="user_mgr_001",
                    approval_status="Approved",
                    callback_payload_json={"status": "APPROVED"},
                    idempotency_key="idem_audit_chain_001",
                    submitted_at=created_at + timedelta(minutes=2),
                    approved_at=created_at + timedelta(minutes=5),
                    rejected_at=None,
                    created_at=created_at + timedelta(minutes=2),
                    updated_at=created_at + timedelta(minutes=5),
                )
            )
            session.add(
                AccessGrantRecord(
                    grant_id="grt_audit_chain_001",
                    request_id="req_audit_chain_001",
                    resource_key="sales.q3_report",
                    resource_type="report",
                    action="read",
                    grant_status="Active",
                    connector_status="Applied",
                    reconcile_status="Confirmed",
                    effective_at=created_at + timedelta(minutes=10),
                    expire_at=created_at + timedelta(days=7),
                    revoked_at=None,
                    revocation_reason=None,
                    created_at=created_at + timedelta(minutes=6),
                    updated_at=created_at + timedelta(minutes=10),
                )
            )
            session.flush()
            session.add(
                ConnectorTaskRecord(
                    task_id="ctk_audit_chain_001",
                    grant_id="grt_audit_chain_001",
                    request_id="req_audit_chain_001",
                    task_type="provision",
                    task_status="Succeeded",
                    retry_count=0,
                    max_retry_count=3,
                    last_error_code=None,
                    last_error_message=None,
                    payload_json={"grant_id": "grt_audit_chain_001"},
                    scheduled_at=created_at + timedelta(minutes=6),
                    processed_at=created_at + timedelta(minutes=10),
                    created_at=created_at + timedelta(minutes=6),
                    updated_at=created_at + timedelta(minutes=10),
                )
            )
            session.add(
                SessionContextRecord(
                    global_session_id="gs_audit_chain_001",
                    grant_id="grt_audit_chain_001",
                    request_id="req_audit_chain_001",
                    agent_id="agent_perm_assistant_v1",
                    user_id="user_001",
                    task_session_id="ctk_audit_chain_001",
                    connector_session_ref="fs_task_audit_chain_001",
                    session_status="Active",
                    revocation_reason=None,
                    last_sync_at=created_at + timedelta(minutes=10),
                    revoked_at=None,
                    created_at=created_at + timedelta(minutes=10),
                    updated_at=created_at + timedelta(minutes=10),
                )
            )
            session.add_all(
                [
                    AuditRecordRecord(
                        audit_id="aud_audit_chain_001",
                        request_id="req_audit_chain_001",
                        event_type="request.submitted",
                        actor_type="User",
                        actor_id="user_001",
                        subject_chain="user:user_001->agent:agent_perm_assistant_v1->request:req_audit_chain_001",
                        result="Success",
                        reason=None,
                        metadata_json={"conversation_id": "conv_audit_chain_001"},
                        created_at=created_at,
                    ),
                    AuditRecordRecord(
                        audit_id="aud_audit_chain_002",
                        request_id="req_audit_chain_001",
                        event_type="approval.approved",
                        actor_type="Approver",
                        actor_id="user_mgr_001",
                        subject_chain="user:user_001->agent:agent_perm_assistant_v1->request:req_audit_chain_001",
                        result="Success",
                        reason=None,
                        metadata_json={"approval_id": "apr_audit_chain_001"},
                        created_at=created_at + timedelta(minutes=5),
                    ),
                    AuditRecordRecord(
                        audit_id="aud_audit_chain_003",
                        request_id="req_audit_chain_001",
                        event_type="grant.provisioned",
                        actor_type="System",
                        actor_id="worker_audit",
                        subject_chain="user:user_001->agent:agent_perm_assistant_v1->request:req_audit_chain_001",
                        result="Success",
                        reason=None,
                        metadata_json={
                            "grant_id": "grt_audit_chain_001",
                            "task_id": "ctk_audit_chain_001",
                            "global_session_id": "gs_audit_chain_001",
                        },
                        created_at=created_at + timedelta(minutes=10),
                    ),
                ]
            )

    def _seed_paginated_audits(self, *, total: int) -> None:
        base_time = datetime(2026, 4, 18, 2, 0, tzinfo=timezone.utc)
        with self.session_factory.begin() as session:
            for index in range(total):
                request_id = f"req_audit_page_{index:03d}"
                grant_id = f"grt_audit_page_{index:03d}"
                created_at = base_time + timedelta(minutes=index)
                session.add(
                    PermissionRequestRecord(
                        request_id=request_id,
                        user_id="user_001",
                        agent_id="agent_perm_assistant_v1",
                        delegation_id="dlg_123",
                        raw_text=f"分页审计申请 {index}",
                        resource_key="sales.q3_report",
                        resource_type="report",
                        action="read",
                        constraints_json=None,
                        requested_duration="P7D",
                        structured_request_json=None,
                        suggested_permission="report:sales.q3:read",
                        risk_level="Low",
                        approval_status="Approved",
                        grant_status="Active",
                        request_status="Active",
                        current_task_state="Succeeded",
                        policy_version="perm-map.v1",
                        renew_round=0,
                        failed_reason=None,
                        created_at=created_at,
                        updated_at=created_at,
                    )
                )
                session.flush()
                session.add(
                    AccessGrantRecord(
                        grant_id=grant_id,
                        request_id=request_id,
                        resource_key="sales.q3_report",
                        resource_type="report",
                        action="read",
                        grant_status="Active",
                        connector_status="Applied",
                        reconcile_status="Confirmed",
                        effective_at=created_at,
                        expire_at=created_at + timedelta(days=7),
                        revoked_at=None,
                        revocation_reason=None,
                        created_at=created_at,
                        updated_at=created_at,
                    )
                )
                session.add(
                    AuditRecordRecord(
                        audit_id=f"aud_audit_page_{index:03d}",
                        request_id=request_id,
                        event_type="grant.provisioned",
                        actor_type="System",
                        actor_id="worker_audit",
                        subject_chain=(
                            f"user:user_001->agent:agent_perm_assistant_v1->request:{request_id}"
                        ),
                        result="Success",
                        reason=None,
                        metadata_json={"grant_id": grant_id},
                        created_at=created_at,
                    )
                )

    def _seed_failed_provision_task(self) -> None:
        now = datetime(2026, 4, 18, 3, 0, tzinfo=timezone.utc)
        with self.session_factory.begin() as session:
            session.add(
                PermissionRequestRecord(
                    request_id="req_failed_provision_001",
                    user_id="user_001",
                    agent_id="agent_perm_assistant_v1",
                    delegation_id="dlg_123",
                    raw_text="失败开通任务",
                    resource_key="sales.q3_report",
                    resource_type="report",
                    action="read",
                    constraints_json=None,
                    requested_duration="P7D",
                    structured_request_json={"approval_route": ["manager"]},
                    suggested_permission="report:sales.q3:read",
                    risk_level="Medium",
                    approval_status="Approved",
                    grant_status="ProvisionFailed",
                    request_status="Failed",
                    current_task_state="Failed",
                    policy_version="perm-map.v1",
                    renew_round=0,
                    failed_reason="Feishu connector failed to apply the requested permission",
                    created_at=now,
                    updated_at=now,
                )
            )
            session.flush()
            session.add(
                AccessGrantRecord(
                    grant_id="grt_failed_provision_001",
                    request_id="req_failed_provision_001",
                    resource_key="sales.q3_report",
                    resource_type="report",
                    action="read",
                    grant_status="ProvisionFailed",
                    connector_status="Failed",
                    reconcile_status="Error",
                    effective_at=None,
                    expire_at=now + timedelta(days=7),
                    revoked_at=None,
                    revocation_reason=None,
                    created_at=now,
                    updated_at=now,
                )
            )
            session.flush()
            session.add(
                ConnectorTaskRecord(
                    task_id="ctk_failed_provision_001",
                    grant_id="grt_failed_provision_001",
                    request_id="req_failed_provision_001",
                    task_type="provision",
                    task_status="Failed",
                    retry_count=0,
                    max_retry_count=3,
                    last_error_code="FEISHU_PROVISION_FAILED",
                    last_error_message="Feishu connector failed to apply the requested permission",
                    payload_json={"grant_id": "grt_failed_provision_001"},
                    scheduled_at=now,
                    processed_at=now + timedelta(minutes=1),
                    created_at=now,
                    updated_at=now + timedelta(minutes=1),
                )
            )

    def _seed_failed_session_task(self) -> None:
        now = datetime(2026, 4, 18, 4, 0, tzinfo=timezone.utc)
        with self.session_factory.begin() as session:
            session.add(
                PermissionRequestRecord(
                    request_id="req_failed_revoke_001",
                    user_id="user_001",
                    agent_id="agent_perm_assistant_v1",
                    delegation_id="dlg_123",
                    raw_text="失败撤销任务",
                    resource_key="sales.q3_report",
                    resource_type="report",
                    action="read",
                    constraints_json=None,
                    requested_duration="P7D",
                    structured_request_json={"approval_route": ["manager"]},
                    suggested_permission="report:sales.q3:read",
                    risk_level="Medium",
                    approval_status="Approved",
                    grant_status="RevokeFailed",
                    request_status="Active",
                    current_task_state="Failed",
                    policy_version="perm-map.v1",
                    renew_round=0,
                    failed_reason="Feishu connector failed to revoke the connector session",
                    created_at=now,
                    updated_at=now,
                )
            )
            session.flush()
            session.add(
                AccessGrantRecord(
                    grant_id="grt_failed_revoke_001",
                    request_id="req_failed_revoke_001",
                    resource_key="sales.q3_report",
                    resource_type="report",
                    action="read",
                    grant_status="RevokeFailed",
                    connector_status="Applied",
                    reconcile_status="Confirmed",
                    effective_at=now - timedelta(days=1),
                    expire_at=now + timedelta(days=6),
                    revoked_at=None,
                    revocation_reason="Manual revoke",
                    created_at=now - timedelta(days=1),
                    updated_at=now,
                )
            )
            session.flush()
            session.add(
                SessionContextRecord(
                    global_session_id="gs_failed_revoke_001",
                    grant_id="grt_failed_revoke_001",
                    request_id="req_failed_revoke_001",
                    agent_id="agent_perm_assistant_v1",
                    user_id="user_001",
                    task_session_id="ctk_failed_revoke_001",
                    connector_session_ref="fs_failed_revoke_001",
                    session_status="SyncFailed",
                    revocation_reason="Manual revoke",
                    last_sync_at=now,
                    revoked_at=None,
                    created_at=now - timedelta(days=1),
                    updated_at=now,
                )
            )
            session.add(
                ConnectorTaskRecord(
                    task_id="ctk_failed_revoke_001",
                    grant_id="grt_failed_revoke_001",
                    request_id="req_failed_revoke_001",
                    task_type="session_revoke",
                    task_status="Failed",
                    retry_count=0,
                    max_retry_count=3,
                    last_error_code="FEISHU_SESSION_REVOKE_FAILED",
                    last_error_message="Feishu connector failed to revoke the connector session",
                    payload_json={
                        "global_session_id": "gs_failed_revoke_001",
                        "grant_id": "grt_failed_revoke_001",
                        "request_id": "req_failed_revoke_001",
                        "reason": "Manual revoke",
                        "cascade_connector_sessions": True,
                    },
                    scheduled_at=now,
                    processed_at=now + timedelta(minutes=1),
                    created_at=now,
                    updated_at=now + timedelta(minutes=1),
                )
            )

    def _seed_callback_failed_record(self) -> None:
        now = datetime(2026, 4, 18, 5, 0, tzinfo=timezone.utc)
        with self.session_factory.begin() as session:
            session.add(
                PermissionRequestRecord(
                    request_id="req_failed_callback_001",
                    user_id="user_001",
                    agent_id="agent_perm_assistant_v1",
                    delegation_id="dlg_123",
                    raw_text="失败回调任务",
                    resource_key="sales.q3_report",
                    resource_type="report",
                    action="read",
                    constraints_json=None,
                    requested_duration="P7D",
                    structured_request_json={"approval_route": ["manager"]},
                    suggested_permission="report:sales.q3:read",
                    risk_level="High",
                    approval_status="CallbackFailed",
                    grant_status="NotCreated",
                    request_status="PendingApproval",
                    current_task_state="Failed",
                    policy_version="perm-map.v1",
                    renew_round=0,
                    failed_reason="Approval callback payload cannot be mapped",
                    created_at=now,
                    updated_at=now,
                )
            )
            session.flush()
            session.add(
                ApprovalRecordRecord(
                    approval_id="apr_failed_callback_001",
                    request_id="req_failed_callback_001",
                    external_approval_id="fs_failed_callback_001",
                    approval_node="manager",
                    approver_id=None,
                    approval_status="CallbackFailed",
                    callback_payload_json={"status": "BROKEN"},
                    idempotency_key="idem_failed_callback_001",
                    submitted_at=now - timedelta(minutes=10),
                    approved_at=None,
                    rejected_at=None,
                    created_at=now - timedelta(minutes=10),
                    updated_at=now,
                )
            )

    def _seed_succeeded_provision_task(self) -> None:
        now = datetime(2026, 4, 18, 6, 0, tzinfo=timezone.utc)
        with self.session_factory.begin() as session:
            session.add(
                PermissionRequestRecord(
                    request_id="req_succeeded_provision_001",
                    user_id="user_001",
                    agent_id="agent_perm_assistant_v1",
                    delegation_id="dlg_123",
                    raw_text="已成功的开通任务",
                    resource_key="sales.q3_report",
                    resource_type="report",
                    action="read",
                    constraints_json=None,
                    requested_duration="P7D",
                    structured_request_json={"approval_route": ["manager"]},
                    suggested_permission="report:sales.q3:read",
                    risk_level="Medium",
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
                    grant_id="grt_succeeded_provision_001",
                    request_id="req_succeeded_provision_001",
                    resource_key="sales.q3_report",
                    resource_type="report",
                    action="read",
                    grant_status="Active",
                    connector_status="Applied",
                    reconcile_status="Confirmed",
                    effective_at=now,
                    expire_at=now + timedelta(days=7),
                    revoked_at=None,
                    revocation_reason=None,
                    created_at=now,
                    updated_at=now,
                )
            )
            session.flush()
            session.add(
                ConnectorTaskRecord(
                    task_id="ctk_succeeded_provision_001",
                    grant_id="grt_succeeded_provision_001",
                    request_id="req_succeeded_provision_001",
                    task_type="provision",
                    task_status="Succeeded",
                    retry_count=0,
                    max_retry_count=3,
                    last_error_code=None,
                    last_error_message=None,
                    payload_json={"grant_id": "grt_succeeded_provision_001"},
                    scheduled_at=now,
                    processed_at=now,
                    created_at=now,
                    updated_at=now,
                )
            )

    def _truncate_tables(self) -> None:
        with self.session_factory.begin() as session:
            for model in (
                AuditRecordRecord,
                ApprovalRecordRecord,
                NotificationTaskRecord,
                PermissionRequestEventRecord,
                ConnectorTaskRecord,
                SessionContextRecord,
                AccessGrantRecord,
                PermissionRequestRecord,
                DelegationCredentialRecord,
                AgentIdentityRecord,
                UserRecord,
            ):
                session.execute(delete(model))

    def _headers(
        self,
        request_id: str,
        *,
        operator_type: str,
        user_id: str = "it_admin_001",
    ) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "X-Request-Id": request_id,
            "X-User-Id": user_id,
            "X-Operator-Type": operator_type,
        }

    def _request(
        self,
        method: str,
        path: str,
        *,
        headers: dict[str, str],
        json_body: dict[str, object] | None = None,
    ) -> tuple[int, dict[str, object]]:
        request = urllib.request.Request(
            url=f"{self.base_url}{path}",
            data=(json.dumps(json_body).encode("utf-8") if json_body is not None else None),
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
        raise RuntimeError("Audit admin API test server did not become ready in time")


if __name__ == "__main__":
    unittest.main()
