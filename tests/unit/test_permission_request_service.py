from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from packages.application import (
    PermissionRequestCreateInput,
    PermissionRequestListInput,
    PermissionRequestService,
)
from packages.domain import (
    AgentStatus,
    ApprovalStatus,
    DomainError,
    GrantStatus,
    RequestStatus,
    UserStatus,
)
from packages.infrastructure.db.models import (
    AgentIdentityRecord,
    AuditRecordRecord,
    DelegationCredentialRecord,
    PermissionRequestEventRecord,
    PermissionRequestRecord,
    UserRecord,
)


class _FakeLookupRepository:
    def __init__(self, items: dict[str, object] | None = None) -> None:
        self.items = items or {}

    def get(self, identifier: str) -> object | None:
        return self.items.get(identifier)


class _FakePermissionRequestRepository(_FakeLookupRepository):
    def __init__(self, items: dict[str, PermissionRequestRecord] | None = None) -> None:
        super().__init__(items)
        self.added: list[PermissionRequestRecord] = []

    def add(self, instance: PermissionRequestRecord) -> PermissionRequestRecord:
        self.items[instance.request_id] = instance
        self.added.append(instance)
        return instance

    def list_paginated(
        self,
        *,
        user_id: str | None = None,
        request_status: str | None = None,
        approval_status: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[PermissionRequestRecord], int]:
        records = list(self.items.values())
        if user_id is not None:
            records = [record for record in records if record.user_id == user_id]
        if request_status is not None:
            records = [record for record in records if record.request_status == request_status]
        if approval_status is not None:
            records = [record for record in records if record.approval_status == approval_status]
        records.sort(key=lambda record: record.created_at, reverse=True)

        total = len(records)
        start = (page - 1) * page_size
        end = start + page_size
        return records[start:end], total


class _FakePermissionRequestEventRepository:
    def __init__(self) -> None:
        self.added: list[PermissionRequestEventRecord] = []

    def add(self, instance: PermissionRequestEventRecord) -> PermissionRequestEventRecord:
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


class PermissionRequestServiceTests(unittest.TestCase):
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
                    capability_scope_json=None,
                    created_at=self.fixed_now,
                    updated_at=self.fixed_now,
                )
            }
        )
        self.delegation_repository = _FakeLookupRepository(
            {
                "dlg_123": DelegationCredentialRecord(
                    delegation_id="dlg_123",
                    user_id="user_001",
                    agent_id="agent_perm_assistant_v1",
                    task_scope="permission_self_service",
                    scope_json={
                        "resource_types": ["report", "doc"],
                        "allowed_actions": ["read", "request_edit"],
                    },
                    delegation_status="Active",
                    issued_at=self.fixed_now - timedelta(hours=1),
                    expire_at=self.fixed_now + timedelta(days=7),
                    revoked_at=None,
                    revocation_reason=None,
                    created_at=self.fixed_now - timedelta(hours=1),
                    updated_at=self.fixed_now - timedelta(hours=1),
                )
            }
        )
        self.permission_request_repository = _FakePermissionRequestRepository()
        self.permission_request_event_repository = _FakePermissionRequestEventRepository()
        self.audit_repository = _FakeAuditRepository()
        self.service = PermissionRequestService(
            user_repository=self.user_repository,
            agent_repository=self.agent_repository,
            delegation_repository=self.delegation_repository,
            permission_request_repository=self.permission_request_repository,
            permission_request_event_repository=self.permission_request_event_repository,
            audit_repository=self.audit_repository,
            now_provider=lambda: self.fixed_now,
        )

    def test_create_permission_request_persists_submitted_record_event_and_audit(self) -> None:
        permission_request = self.service.create_permission_request(
            PermissionRequestCreateInput(
                user_id="user_001",
                agent_id="agent_perm_assistant_v1",
                delegation_id="dlg_123",
                message="  我需要查看销售部Q3报表  ",
                conversation_id="conv_001",
                request_id="req_trace_001",
            )
        )

        self.assertTrue(permission_request.request_id.startswith("req_"))
        self.assertEqual(permission_request.raw_text, "我需要查看销售部Q3报表")
        self.assertEqual(permission_request.request_status, RequestStatus.SUBMITTED)
        self.assertEqual(permission_request.approval_status, ApprovalStatus.NOT_REQUIRED)
        self.assertEqual(permission_request.grant_status, GrantStatus.NOT_CREATED)
        self.assertEqual(len(self.permission_request_repository.added), 1)
        self.assertEqual(len(self.permission_request_event_repository.added), 1)
        self.assertEqual(len(self.audit_repository.added), 1)
        self.assertEqual(
            self.permission_request_event_repository.added[0].event_type,
            "request.submitted",
        )
        self.assertEqual(
            self.permission_request_event_repository.added[0].from_request_status,
            "Draft",
        )
        self.assertEqual(
            self.permission_request_event_repository.added[0].to_request_status,
            "Submitted",
        )

    def test_create_permission_request_rejects_invalid_delegation(self) -> None:
        with self.assertRaises(DomainError) as context:
            self.service.create_permission_request(
                PermissionRequestCreateInput(
                    user_id="user_001",
                    agent_id="agent_perm_assistant_v1",
                    delegation_id="dlg_missing",
                    message="我需要查看销售部Q3报表",
                    request_id="req_trace_002",
                )
            )

        self.assertEqual(context.exception.code.value, "DELEGATION_INVALID")

    def test_create_permission_request_rejects_empty_message(self) -> None:
        with self.assertRaises(DomainError) as context:
            self.service.create_permission_request(
                PermissionRequestCreateInput(
                    user_id="user_001",
                    agent_id="agent_perm_assistant_v1",
                    delegation_id="dlg_123",
                    message="   ",
                    request_id="req_trace_003",
                )
            )

        self.assertEqual(context.exception.code.value, "REQUEST_MESSAGE_EMPTY")

    def test_get_permission_request_returns_existing_record(self) -> None:
        created = self.service.create_permission_request(
            PermissionRequestCreateInput(
                user_id="user_001",
                agent_id="agent_perm_assistant_v1",
                delegation_id="dlg_123",
                message="我需要查看销售部Q3报表",
                request_id="req_trace_004",
            )
        )

        permission_request = self.service.get_permission_request(
            created.request_id,
            requester_user_id="user_001",
        )

        self.assertEqual(permission_request.request_id, created.request_id)
        self.assertEqual(permission_request.user_id, "user_001")
        self.assertEqual(permission_request.agent_id, "agent_perm_assistant_v1")

    def test_list_permission_requests_supports_pagination_and_filtering(self) -> None:
        first = self.service.create_permission_request(
            PermissionRequestCreateInput(
                user_id="user_001",
                agent_id="agent_perm_assistant_v1",
                delegation_id="dlg_123",
                message="申请一",
                request_id="req_trace_005",
            )
        )
        second = self.service.create_permission_request(
            PermissionRequestCreateInput(
                user_id="user_001",
                agent_id="agent_perm_assistant_v1",
                delegation_id="dlg_123",
                message="申请二",
                request_id="req_trace_006",
            )
        )
        third = self.service.create_permission_request(
            PermissionRequestCreateInput(
                user_id="user_001",
                agent_id="agent_perm_assistant_v1",
                delegation_id="dlg_123",
                message="申请三",
                request_id="req_trace_007",
            )
        )
        self.permission_request_repository.add(
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
                created_at=self.fixed_now + timedelta(minutes=1),
                updated_at=self.fixed_now + timedelta(minutes=1),
            )
        )

        result = self.service.list_permission_requests(
            PermissionRequestListInput(
                requester_user_id="user_001",
                page=2,
                page_size=2,
                request_status=RequestStatus.SUBMITTED,
                approval_status=ApprovalStatus.NOT_REQUIRED,
            )
        )

        self.assertEqual(result.total, 3)
        self.assertEqual(result.page, 2)
        self.assertEqual(result.page_size, 2)
        self.assertEqual(len(result.items), 1)
        self.assertEqual(result.items[0].request_status, RequestStatus.SUBMITTED)
        self.assertIn(result.items[0].request_id, {first.request_id, second.request_id, third.request_id})


if __name__ == "__main__":
    unittest.main()
