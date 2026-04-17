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
    DelegationCredentialRecord,
    NotificationTaskRecord,
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


class WorkerGrantLifecycleTaskIntegrationTests(unittest.TestCase):
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
            "aisecurity.worker.lifecycle.test",
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
        self._truncate_tables()
        self._seed_identity_data()

    def test_worker_lifecycle_task_marks_expiring_and_expires_due_grants(self) -> None:
        self._seed_active_request_and_grant(
            request_id="req_worker_expiring_001",
            grant_id="grt_worker_expiring_001",
            expire_at=datetime.now(timezone.utc) + timedelta(hours=8),
        )
        self._seed_active_request_and_grant(
            request_id="req_worker_expired_001",
            grant_id="grt_worker_expired_001",
            expire_at=datetime.now(timezone.utc) - timedelta(minutes=5),
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

        lifecycle_task = self.celery_app.tasks["worker.grants.lifecycle.reconcile"]
        with mock.patch("apps.worker.tasks.session_scope", new=session_scope_override):
            result = lifecycle_task.run()

        self.assertEqual(result["expiring_count"], 1)
        self.assertEqual(result["reminder_count"], 1)
        self.assertEqual(result["expired_count"], 1)

        with self.session_factory() as session:
            expiring_grant = session.get(AccessGrantRecord, "grt_worker_expiring_001")
            expired_grant = session.get(AccessGrantRecord, "grt_worker_expired_001")
            self.assertIsNotNone(expiring_grant)
            self.assertIsNotNone(expired_grant)
            assert expiring_grant is not None
            assert expired_grant is not None
            self.assertEqual(expiring_grant.grant_status, "Expiring")
            self.assertEqual(expired_grant.grant_status, "Expired")

            reminder_tasks = session.scalars(
                select(NotificationTaskRecord)
                .where(NotificationTaskRecord.grant_id == "grt_worker_expiring_001")
            ).all()
            self.assertEqual(len(reminder_tasks), 1)
            self.assertEqual(reminder_tasks[0].task_status, "Succeeded")

            expired_events = session.scalars(
                select(PermissionRequestEventRecord)
                .where(PermissionRequestEventRecord.request_id == "req_worker_expired_001")
                .order_by(PermissionRequestEventRecord.created_at.asc())
            ).all()
            self.assertEqual(
                [event.event_type for event in expired_events],
                ["grant.expiring", "grant.expired"],
            )

            expired_audits = session.scalars(
                select(AuditRecordRecord)
                .where(AuditRecordRecord.request_id == "req_worker_expired_001")
                .order_by(AuditRecordRecord.created_at.asc())
            ).all()
            self.assertEqual(
                [audit.event_type for audit in expired_audits],
                ["grant.expired"],
            )

    def _truncate_tables(self) -> None:
        with self.session_factory.begin() as session:
            for model in (
                AuditRecordRecord,
                NotificationTaskRecord,
                PermissionRequestEventRecord,
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

    def _seed_active_request_and_grant(
        self,
        *,
        request_id: str,
        grant_id: str,
        expire_at: datetime,
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
                    grant_id=grant_id,
                    request_id=request_id,
                    resource_key="sales.q3_report",
                    resource_type="report",
                    action="read",
                    grant_status="Active",
                    connector_status="Applied",
                    reconcile_status="Confirmed",
                    effective_at=now - timedelta(minutes=5),
                    expire_at=expire_at,
                    revoked_at=None,
                    revocation_reason=None,
                    created_at=now,
                    updated_at=now,
                )
            )


if __name__ == "__main__":
    unittest.main()
