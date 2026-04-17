from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from packages.application import DelegationCreateInput, DelegationService
from packages.domain import AgentStatus, DelegationStatus, DomainError, UserStatus
from packages.infrastructure.db.models import (
    AgentIdentityRecord,
    AuditRecordRecord,
    DelegationCredentialRecord,
    UserRecord,
)


class _FakeLookupRepository:
    def __init__(self, items: dict[str, object] | None = None) -> None:
        self.items = items or {}

    def get(self, identifier: str) -> object | None:
        return self.items.get(identifier)


class _FakeDelegationRepository(_FakeLookupRepository):
    def __init__(self, items: dict[str, DelegationCredentialRecord] | None = None) -> None:
        super().__init__(items)
        self.added: list[DelegationCredentialRecord] = []

    def add(self, instance: DelegationCredentialRecord) -> DelegationCredentialRecord:
        self.items[instance.delegation_id] = instance
        self.added.append(instance)
        return instance


class _FakeAuditRepository:
    def __init__(self) -> None:
        self.added: list[AuditRecordRecord] = []

    def add(self, instance: AuditRecordRecord) -> AuditRecordRecord:
        self.added.append(instance)
        return instance

    def get_latest_by_event_and_idempotency_key(
        self,
        *,
        actor_type: str,
        actor_id: str | None,
        event_type: str,
        idempotency_key: str,
    ) -> AuditRecordRecord | None:
        for record in reversed(self.added):
            if (
                record.actor_type == actor_type
                and record.actor_id == actor_id
                and record.event_type == event_type
                and record.metadata_json
                and record.metadata_json.get("idempotency_key") == idempotency_key
            ):
                return record
        return None


class DelegationServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixed_now = datetime(2026, 4, 17, 8, 0, tzinfo=timezone.utc)
        self.user_repository = _FakeLookupRepository(
            {
                "user_001": UserRecord(
                    user_id="user_001",
                    employee_no="E001",
                    display_name="Alice",
                    email="alice@example.com",
                    department_id="dept_001",
                    department_name="Security",
                    manager_user_id=None,
                    user_status=UserStatus.ACTIVE.value,
                    identity_source="SSO",
                    created_at=self.fixed_now,
                    updated_at=self.fixed_now,
                )
            }
        )
        self.agent_repository = _FakeLookupRepository(
            {
                "agent_perm_assistant_v1": AgentIdentityRecord(
                    agent_id="agent_perm_assistant_v1",
                    agent_name="Permission Assistant",
                    agent_version="v1",
                    agent_type="first_party",
                    agent_status=AgentStatus.ACTIVE.value,
                    capability_scope_json={
                        "resource_types": ["report", "doc"],
                        "allowed_actions": ["read", "request_edit"],
                    },
                    created_at=self.fixed_now,
                    updated_at=self.fixed_now,
                )
            }
        )
        self.delegation_repository = _FakeDelegationRepository()
        self.audit_repository = _FakeAuditRepository()
        self.service = DelegationService(
            user_repository=self.user_repository,
            agent_repository=self.agent_repository,
            delegation_repository=self.delegation_repository,
            audit_repository=self.audit_repository,
            now_provider=lambda: self.fixed_now,
        )

    def test_create_delegation_builds_active_record_and_audit_event(self) -> None:
        delegation = self.service.create_delegation(
            DelegationCreateInput(
                user_id="user_001",
                agent_id="agent_perm_assistant_v1",
                task_scope="permission_self_service",
                scope={
                    "resource_types": ["report", "doc"],
                    "allowed_actions": ["read", "request_edit"],
                },
                expire_at=self.fixed_now + timedelta(days=7),
                request_id="req_trace_001",
                idempotency_key="idem-001",
            )
        )

        self.assertEqual(delegation.delegation_status, DelegationStatus.ACTIVE)
        self.assertEqual(len(self.delegation_repository.added), 1)
        self.assertEqual(len(self.audit_repository.added), 1)
        self.assertTrue(delegation.delegation_id.startswith("dlg_"))
        self.assertEqual(
            self.audit_repository.added[0].metadata_json["delegation_id"],
            delegation.delegation_id,
        )

    def test_create_delegation_rejects_disabled_agent(self) -> None:
        disabled_agent = self.agent_repository.get("agent_perm_assistant_v1")
        assert isinstance(disabled_agent, AgentIdentityRecord)
        disabled_agent.agent_status = AgentStatus.DISABLED.value

        with self.assertRaises(DomainError) as context:
            self.service.create_delegation(
                DelegationCreateInput(
                    user_id="user_001",
                    agent_id="agent_perm_assistant_v1",
                    task_scope="permission_self_service",
                    scope={
                        "resource_types": ["report"],
                        "allowed_actions": ["read"],
                    },
                    expire_at=self.fixed_now + timedelta(days=1),
                    request_id="req_trace_002",
                )
            )

        self.assertEqual(context.exception.code.value, "AGENT_DISABLED")

    def test_create_delegation_rejects_invalid_expire_at(self) -> None:
        with self.assertRaises(DomainError) as context:
            self.service.create_delegation(
                DelegationCreateInput(
                    user_id="user_001",
                    agent_id="agent_perm_assistant_v1",
                    task_scope="permission_self_service",
                    scope={
                        "resource_types": ["report"],
                        "allowed_actions": ["read"],
                    },
                    expire_at=self.fixed_now - timedelta(minutes=1),
                    request_id="req_trace_003",
                )
            )

        self.assertEqual(context.exception.code.value, "DELEGATION_EXPIRE_AT_INVALID")

    def test_create_delegation_reuses_existing_record_for_same_idempotency_key(self) -> None:
        first = self.service.create_delegation(
            DelegationCreateInput(
                user_id="user_001",
                agent_id="agent_perm_assistant_v1",
                task_scope="permission_self_service",
                scope={
                    "resource_types": ["report"],
                    "allowed_actions": ["read"],
                },
                expire_at=self.fixed_now + timedelta(days=1),
                request_id="req_trace_004",
                idempotency_key="idem-004",
            )
        )

        second = self.service.create_delegation(
            DelegationCreateInput(
                user_id="user_001",
                agent_id="agent_perm_assistant_v1",
                task_scope="permission_self_service",
                scope={
                    "resource_types": ["report"],
                    "allowed_actions": ["read"],
                },
                expire_at=self.fixed_now + timedelta(days=1),
                request_id="req_trace_005",
                idempotency_key="idem-004",
            )
        )

        self.assertEqual(first.delegation_id, second.delegation_id)
        self.assertEqual(len(self.delegation_repository.added), 1)
        self.assertEqual(len(self.audit_repository.added), 1)


if __name__ == "__main__":
    unittest.main()
