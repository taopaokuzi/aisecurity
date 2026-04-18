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


class WorkerSessionRevokeTaskIntegrationTests(unittest.TestCase):
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
            "aisecurity.worker.session_revoke.test",
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
        self._truncate_tables()
        self._seed_identity_data()

    def test_worker_session_revoke_task_marks_session_revoked(self) -> None:
        os.environ["FEISHU_SESSION_REVOKE_STUB_MODE"] = "success"
        self._seed_revoke_flow_fixture(
            request_id="req_worker_revoke_success_001",
            grant_id="grt_worker_revoke_success_001",
            global_session_id="gs_worker_revoke_success_001",
            connector_task_id="ctk_worker_revoke_success_001",
        )

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

        task = self.celery_app.tasks["worker.sessions.revoke.process_pending"]
        with mock.patch("apps.worker.tasks.session_scope", new=session_scope_override):
            result = task.run()

        self.assertEqual(result["processed_count"], 1)
        self.assertEqual(result["revoked_count"], 1)
        self.assertEqual(result["sync_failed_count"], 0)

        with self.session_factory() as session:
            session_context = session.get(SessionContextRecord, "gs_worker_revoke_success_001")
            grant = session.get(AccessGrantRecord, "grt_worker_revoke_success_001")
            request_record = session.get(PermissionRequestRecord, "req_worker_revoke_success_001")
            connector_task = session.get(ConnectorTaskRecord, "ctk_worker_revoke_success_001")
            self.assertIsNotNone(session_context)
            self.assertIsNotNone(grant)
            self.assertIsNotNone(request_record)
            self.assertIsNotNone(connector_task)
            assert session_context is not None
            assert grant is not None
            assert request_record is not None
            assert connector_task is not None

            self.assertEqual(session_context.session_status, "Revoked")
            self.assertEqual(grant.grant_status, "Revoked")
            self.assertEqual(request_record.request_status, "Revoked")
            self.assertEqual(connector_task.task_status, "Succeeded")

            events = session.scalars(
                select(PermissionRequestEventRecord)
                .where(PermissionRequestEventRecord.request_id == "req_worker_revoke_success_001")
                .order_by(PermissionRequestEventRecord.created_at.asc())
            ).all()
            self.assertEqual([event.event_type for event in events], ["session.revoked"])

    def test_worker_session_revoke_task_marks_session_sync_failed(self) -> None:
        os.environ["FEISHU_SESSION_REVOKE_STUB_MODE"] = "failed"
        self._seed_revoke_flow_fixture(
            request_id="req_worker_revoke_failed_001",
            grant_id="grt_worker_revoke_failed_001",
            global_session_id="gs_worker_revoke_failed_001",
            connector_task_id="ctk_worker_revoke_failed_001",
        )

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

        task = self.celery_app.tasks["worker.sessions.revoke.process_pending"]
        with mock.patch("apps.worker.tasks.session_scope", new=session_scope_override):
            result = task.run()

        self.assertEqual(result["processed_count"], 1)
        self.assertEqual(result["revoked_count"], 0)
        self.assertEqual(result["sync_failed_count"], 1)

        with self.session_factory() as session:
            session_context = session.get(SessionContextRecord, "gs_worker_revoke_failed_001")
            grant = session.get(AccessGrantRecord, "grt_worker_revoke_failed_001")
            request_record = session.get(PermissionRequestRecord, "req_worker_revoke_failed_001")
            connector_task = session.get(ConnectorTaskRecord, "ctk_worker_revoke_failed_001")
            self.assertIsNotNone(session_context)
            self.assertIsNotNone(grant)
            self.assertIsNotNone(request_record)
            self.assertIsNotNone(connector_task)
            assert session_context is not None
            assert grant is not None
            assert request_record is not None
            assert connector_task is not None

            self.assertEqual(session_context.session_status, "SyncFailed")
            self.assertEqual(grant.grant_status, "RevokeFailed")
            self.assertEqual(request_record.grant_status, "RevokeFailed")
            self.assertEqual(request_record.current_task_state, "Failed")
            self.assertEqual(connector_task.task_status, "Failed")

            audits = session.scalars(
                select(AuditRecordRecord)
                .where(AuditRecordRecord.request_id == "req_worker_revoke_failed_001")
                .order_by(AuditRecordRecord.created_at.asc())
            ).all()
            self.assertEqual([audit.event_type for audit in audits], ["session.sync_failed"])

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

    def _seed_revoke_flow_fixture(
        self,
        *,
        request_id: str,
        grant_id: str,
        global_session_id: str,
        connector_task_id: str,
    ) -> None:
        now = datetime.now(timezone.utc)
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
                    risk_level="Low",
                    approval_status="Approved",
                    grant_status="Revoking",
                    request_status="Active",
                    current_task_state="Running",
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
                    grant_id=grant_id,
                    request_id=request_id,
                    resource_key="sales.q3_report",
                    resource_type="report",
                    action="read",
                    grant_status="Revoking",
                    connector_status="Applied",
                    reconcile_status="Confirmed",
                    effective_at=now - timedelta(minutes=30),
                    expire_at=now + timedelta(days=7),
                    revoked_at=None,
                    revocation_reason="Manual revoke",
                    created_at=now,
                    updated_at=now,
                )
            )
            session.flush()
            session.add(
                SessionContextRecord(
                    global_session_id=global_session_id,
                    grant_id=grant_id,
                    request_id=request_id,
                    agent_id="agent_perm_assistant_v1",
                    user_id="user_001",
                    task_session_id="ctk_provision_001",
                    connector_session_ref="feishu_task_apply_001",
                    session_status="Revoking",
                    revocation_reason="Manual revoke",
                    last_sync_at=now - timedelta(minutes=10),
                    revoked_at=None,
                    created_at=now,
                    updated_at=now,
                )
            )
            session.flush()
            session.add(
                ConnectorTaskRecord(
                    task_id=connector_task_id,
                    grant_id=grant_id,
                    request_id=request_id,
                    task_type="session_revoke",
                    task_status="Pending",
                    retry_count=0,
                    max_retry_count=3,
                    last_error_code=None,
                    last_error_message=None,
                    payload_json={
                        "global_session_id": global_session_id,
                        "grant_id": grant_id,
                        "request_id": request_id,
                        "api_request_id": "req_trace_worker_session_revoke_001",
                        "trigger_source": "Manual",
                        "reason": "Manual revoke",
                        "cascade_connector_sessions": True,
                    },
                    scheduled_at=now,
                    processed_at=None,
                    created_at=now,
                    updated_at=now,
                )
            )


if __name__ == "__main__":
    unittest.main()
