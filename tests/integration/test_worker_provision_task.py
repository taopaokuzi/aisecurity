from __future__ import annotations

import os
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest import mock

from celery import Celery
from sqlalchemy import create_engine, delete, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session, sessionmaker

from apps.worker.tasks import register_tasks
from packages.domain import DomainError, ErrorCode
from packages.infrastructure.db import Base
from packages.infrastructure.db.models import (
    AccessGrantRecord,
    AgentIdentityRecord,
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


class WorkerProvisionTaskIntegrationTests(unittest.TestCase):
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
        cls.celery_app = Celery(
            "aisecurity.worker.test",
            broker="memory://",
            backend="cache+memory://",
        )
        cls.celery_app.conf.update(
            worker_service_name="aisecurity-worker-test",
            task_default_queue="aisecurity.default",
        )
        register_tasks(cls.celery_app)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.engine.dispose()

    def setUp(self) -> None:
        os.environ["FEISHU_CONNECTOR_PROVIDER"] = "stub"
        os.environ["FEISHU_CONNECTOR_STUB_MODE"] = "accepted"
        self._truncate_tables()
        self._seed_identity_data()

    def test_worker_task_persists_failed_writeback_when_connector_is_unavailable(self) -> None:
        os.environ["FEISHU_CONNECTOR_STUB_MODE"] = "bogus"
        self._seed_approved_request("req_worker_unavailable_001")

        @contextmanager
        def session_scope_override(session_factory=None):
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

        provision_task = self.celery_app.tasks["worker.grants.provision"]
        with self.assertRaises(DomainError) as raised:
            with mock.patch("apps.worker.tasks.session_scope", new=session_scope_override):
                provision_task.run(
                    grant_id="grt_worker_unavailable_001",
                    permission_request_id="req_worker_unavailable_001",
                    policy_version="perm-map.v1",
                    delegation_id="dlg_123",
                    api_request_id="req_trace_worker_001",
                    operator_user_id="worker",
                    force_retry=False,
                    trace_id="trace_worker_001",
                )

        self.assertEqual(raised.exception.code, ErrorCode.CONNECTOR_UNAVAILABLE)

        with self.session_factory() as session:
            permission_request = session.get(PermissionRequestRecord, "req_worker_unavailable_001")
            self.assertIsNotNone(permission_request)
            assert permission_request is not None
            self.assertEqual(permission_request.request_status, "Failed")
            self.assertEqual(permission_request.grant_status, "ProvisionFailed")
            self.assertEqual(permission_request.current_task_state, "Failed")
            self.assertIn(
                "Unsupported feishu connector stub mode: bogus",
                permission_request.failed_reason or "",
            )

            grant = session.get(AccessGrantRecord, "grt_worker_unavailable_001")
            self.assertIsNotNone(grant)
            assert grant is not None
            self.assertEqual(grant.grant_status, "ProvisionFailed")
            self.assertEqual(grant.connector_status, "Failed")
            self.assertEqual(grant.reconcile_status, "Error")

            tasks = session.scalars(
                select(ConnectorTaskRecord)
                .where(ConnectorTaskRecord.grant_id == "grt_worker_unavailable_001")
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
                .where(PermissionRequestEventRecord.request_id == "req_worker_unavailable_001")
                .order_by(PermissionRequestEventRecord.created_at.asc())
            ).all()
            self.assertEqual(
                [event.event_type for event in events],
                ["grant.provisioning_requested", "grant.provision_failed"],
            )

            audits = session.scalars(
                select(AuditRecordRecord)
                .where(AuditRecordRecord.request_id == "req_worker_unavailable_001")
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


if __name__ == "__main__":
    unittest.main()
