from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from packages.application import ApprovalService, ApprovalSubmitInput
from packages.infrastructure.approval_adapter import (
    ApprovalSubmissionCommand,
    ApprovalSubmissionResponse,
)
from packages.infrastructure.db.models import (
    ApprovalRecordRecord,
    AuditRecordRecord,
    PermissionRequestEventRecord,
    PermissionRequestRecord,
)


class _FakePermissionRequestRepository:
    def __init__(self, items: dict[str, PermissionRequestRecord]) -> None:
        self.items = items

    def get(self, identifier: str) -> PermissionRequestRecord | None:
        return self.items.get(identifier)


class _FakeApprovalRepository:
    def __init__(self) -> None:
        self.records: dict[str, ApprovalRecordRecord] = {}
        self.session = self

    def add(self, instance: ApprovalRecordRecord) -> ApprovalRecordRecord:
        self.records[instance.approval_id] = instance
        return instance

    def list_for_request(self, request_id: str) -> list[ApprovalRecordRecord]:
        return [
            record
            for record in self.records.values()
            if record.request_id == request_id
        ]

    def get_by_idempotency_key(self, idempotency_key: str) -> ApprovalRecordRecord | None:
        for record in self.records.values():
            if record.idempotency_key == idempotency_key:
                return record
        return None

    def get_by_external_approval_id(self, external_approval_id: str) -> ApprovalRecordRecord | None:
        for record in self.records.values():
            if record.external_approval_id == external_approval_id:
                return record
        return None

    def flush(self) -> None:
        return None


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


class _FakeApprovalAdapter:
    def submit_approval(
        self,
        command: ApprovalSubmissionCommand,
    ) -> ApprovalSubmissionResponse:
        return ApprovalSubmissionResponse(
            external_approval_id="feishu_apr_unit_001",
            approval_node=command.approval_route[0],
            approver_id=None,
            submitted_at=datetime(2026, 4, 17, 10, 1, tzinfo=timezone.utc),
            provider_request_id="feishu_req_unit_001",
            raw_payload={
                "request_id": command.request_id,
                "approval_route": list(command.approval_route),
            },
        )


class _NoopCallbackVerifier:
    def verify(
        self,
        *,
        signature: str,
        timestamp: str,
        raw_body: bytes,
        source: str | None,
    ) -> None:
        return None


class ApprovalServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        fixed_now = datetime(2026, 4, 17, 10, 0, tzinfo=timezone.utc)
        self.permission_request_repository = _FakePermissionRequestRepository(
            {
                "req_pending_approval": PermissionRequestRecord(
                    request_id="req_pending_approval",
                    user_id="user_001",
                    agent_id="agent_perm_assistant_v1",
                    delegation_id="dlg_123",
                    raw_text="我需要查看薪资报表",
                    resource_key="finance.payroll",
                    resource_type="report",
                    action="read",
                    constraints_json=None,
                    requested_duration="P7D",
                    structured_request_json={
                        "approval_route": ["manager", "security_admin"],
                    },
                    suggested_permission="report:finance.payroll:read",
                    risk_level="High",
                    approval_status="Pending",
                    grant_status="NotCreated",
                    request_status="PendingApproval",
                    current_task_state="Succeeded",
                    policy_version="perm-map.v1",
                    renew_round=0,
                    failed_reason=None,
                    created_at=fixed_now - timedelta(minutes=5),
                    updated_at=fixed_now - timedelta(minutes=5),
                )
            }
        )
        self.approval_repository = _FakeApprovalRepository()
        self.event_repository = _FakePermissionRequestEventRepository()
        self.audit_repository = _FakeAuditRepository()
        self.service = ApprovalService(
            permission_request_repository=self.permission_request_repository,
            approval_repository=self.approval_repository,
            permission_request_event_repository=self.event_repository,
            audit_repository=self.audit_repository,
            approval_adapter=_FakeApprovalAdapter(),
            callback_verifier=_NoopCallbackVerifier(),
            now_provider=lambda: fixed_now,
        )

    def test_submit_approval_for_request_creates_pending_record_and_audit(self) -> None:
        result = self.service.submit_approval_for_request(
            ApprovalSubmitInput(
                permission_request_id="req_pending_approval",
                request_id="req_trace_401",
                operator_user_id="system_worker",
            )
        )

        self.assertEqual(result.request_id, "req_pending_approval")
        self.assertEqual(result.external_approval_id, "feishu_apr_unit_001")
        self.assertEqual(result.approval_status.value, "Pending")
        self.assertEqual(result.approval_node, "manager")

        self.assertEqual(len(self.approval_repository.records), 1)
        approval_record = next(iter(self.approval_repository.records.values()))
        self.assertEqual(approval_record.approval_status, "Pending")
        self.assertEqual(approval_record.external_approval_id, "feishu_apr_unit_001")

        self.assertEqual(
            [event.event_type for event in self.event_repository.added],
            ["approval.required"],
        )
        self.assertEqual(
            [audit.event_type for audit in self.audit_repository.added],
            ["approval.required"],
        )


if __name__ == "__main__":
    unittest.main()
