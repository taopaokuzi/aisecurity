from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from packages.application import GrantProvisionInput, ProvisioningService
from packages.domain import (
    ApprovalStatus,
    AuditResult,
    ConnectorStatus,
    DomainError,
    ErrorCode,
    GrantStatus,
    RequestStatus,
    TaskStatus,
)
from packages.infrastructure.db.models import (
    AccessGrantRecord,
    AuditRecordRecord,
    ConnectorTaskRecord,
    PermissionRequestEventRecord,
    PermissionRequestRecord,
)
from packages.infrastructure.feishu_connector import (
    ConnectorProvisionResponse,
    ConnectorUnavailableError,
    FeishuPermissionConnector,
)


class _FakePermissionRequestRepository:
    def __init__(self, items: dict[str, PermissionRequestRecord]) -> None:
        self.items = items

    def get(self, identifier: str) -> PermissionRequestRecord | None:
        return self.items.get(identifier)


class _FakeAccessGrantRepository:
    def __init__(self) -> None:
        self.items: dict[str, AccessGrantRecord] = {}

    def add(self, instance: AccessGrantRecord) -> AccessGrantRecord:
        self.items[instance.grant_id] = instance
        return instance

    def get(self, identifier: str) -> AccessGrantRecord | None:
        return self.items.get(identifier)

    def get_by_request_id(self, request_id: str) -> AccessGrantRecord | None:
        for item in self.items.values():
            if item.request_id == request_id:
                return item
        return None


class _FakeConnectorTaskRepository:
    def __init__(self) -> None:
        self.items: dict[str, ConnectorTaskRecord] = {}
        self.session = self

    def add(self, instance: ConnectorTaskRecord) -> ConnectorTaskRecord:
        self.items[instance.task_id] = instance
        return instance

    def get_latest_for_grant(self, grant_id: str) -> ConnectorTaskRecord | None:
        candidates = [item for item in self.items.values() if item.grant_id == grant_id]
        if not candidates:
            return None
        return sorted(candidates, key=lambda item: item.created_at, reverse=True)[0]

    def flush(self) -> None:
        return None


class _FakePermissionRequestEventRepository:
    def __init__(self) -> None:
        self.items: list[PermissionRequestEventRecord] = []

    def add(self, instance: PermissionRequestEventRecord) -> PermissionRequestEventRecord:
        self.items.append(instance)
        return instance


class _FakeAuditRepository:
    def __init__(self) -> None:
        self.items: list[AuditRecordRecord] = []

    def add(self, instance: AuditRecordRecord) -> AuditRecordRecord:
        self.items.append(instance)
        return instance


class _FakeConnector(FeishuPermissionConnector):
    def __init__(self, response: ConnectorProvisionResponse) -> None:
        self.response = response
        self.calls = 0

    def provision_access(self, command):  # type: ignore[override]
        self.calls += 1
        return self.response


class _UnavailableConnector(FeishuPermissionConnector):
    def __init__(self, message: str) -> None:
        self.message = message
        self.calls = 0

    def provision_access(self, command):  # type: ignore[override]
        self.calls += 1
        raise ConnectorUnavailableError(self.message)


class ProvisioningServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixed_now = datetime(2026, 4, 17, 12, 30, tzinfo=timezone.utc)
        self.permission_request_repository = _FakePermissionRequestRepository(
            {
                "req_approved_001": self._build_request_record(
                    request_id="req_approved_001",
                    approval_status=ApprovalStatus.APPROVED.value,
                    grant_status=GrantStatus.NOT_CREATED.value,
                    request_status=RequestStatus.APPROVED.value,
                ),
                "req_failed_001": self._build_request_record(
                    request_id="req_failed_001",
                    approval_status=ApprovalStatus.APPROVED.value,
                    grant_status=GrantStatus.PROVISION_FAILED.value,
                    request_status=RequestStatus.FAILED.value,
                    failed_reason="previous failed",
                ),
                "req_pending_001": self._build_request_record(
                    request_id="req_pending_001",
                    approval_status=ApprovalStatus.PENDING.value,
                    grant_status=GrantStatus.NOT_CREATED.value,
                    request_status=RequestStatus.PENDING_APPROVAL.value,
                ),
            }
        )
        self.access_grant_repository = _FakeAccessGrantRepository()
        self.connector_task_repository = _FakeConnectorTaskRepository()
        self.event_repository = _FakePermissionRequestEventRepository()
        self.audit_repository = _FakeAuditRepository()

    def test_provisioning_creates_grant_and_marks_accepted_when_connector_accepts(self) -> None:
        service = self._build_service(
            ConnectorProvisionResponse(
                connector_status=ConnectorStatus.ACCEPTED,
                provider_request_id="feishu_req_accepted_001",
                provider_task_id="feishu_task_accepted_001",
                effective_at=None,
                retryable=True,
                error_code=None,
                error_message=None,
                raw_payload={"mode": "accepted"},
            )
        )

        result = service.provision_grant(self._build_command("req_approved_001", "grt_accepted_001"))

        self.assertEqual(result.grant_status, GrantStatus.PROVISIONING)
        self.assertEqual(result.connector_status, ConnectorStatus.ACCEPTED)
        self.assertEqual(result.request_status, RequestStatus.PROVISIONING)
        self.assertEqual(result.connector_task_status, TaskStatus.SUCCEEDED)

        grant_record = self.access_grant_repository.get("grt_accepted_001")
        self.assertIsNotNone(grant_record)
        assert grant_record is not None
        self.assertEqual(grant_record.grant_status, GrantStatus.PROVISIONING.value)
        self.assertEqual(grant_record.connector_status, ConnectorStatus.ACCEPTED.value)
        self.assertEqual(grant_record.reconcile_status, "AwaitingConfirmation")

        request_record = self.permission_request_repository.get("req_approved_001")
        assert request_record is not None
        self.assertEqual(request_record.request_status, RequestStatus.PROVISIONING.value)
        self.assertEqual(request_record.current_task_state, TaskStatus.SUCCEEDED.value)

        self.assertEqual(
            [event.event_type for event in self.event_repository.items],
            ["grant.provisioning_requested", "grant.accepted"],
        )
        self.assertEqual(
            [audit.event_type for audit in self.audit_repository.items],
            ["grant.provisioning_requested", "grant.accepted"],
        )

    def test_provisioning_marks_grant_active_when_connector_applies_immediately(self) -> None:
        service = self._build_service(
            ConnectorProvisionResponse(
                connector_status=ConnectorStatus.APPLIED,
                provider_request_id="feishu_req_applied_001",
                provider_task_id="feishu_task_applied_001",
                effective_at=self.fixed_now + timedelta(minutes=1),
                retryable=False,
                error_code=None,
                error_message=None,
                raw_payload={"mode": "applied"},
            )
        )

        result = service.provision_grant(self._build_command("req_approved_001", "grt_applied_001"))

        self.assertEqual(result.grant_status, GrantStatus.ACTIVE)
        self.assertEqual(result.connector_status, ConnectorStatus.APPLIED)
        self.assertEqual(result.request_status, RequestStatus.ACTIVE)
        self.assertEqual(result.connector_task_status, TaskStatus.SUCCEEDED)
        self.assertEqual(result.effective_at, self.fixed_now + timedelta(minutes=1))

        request_record = self.permission_request_repository.get("req_approved_001")
        assert request_record is not None
        self.assertEqual(request_record.grant_status, GrantStatus.ACTIVE.value)
        self.assertEqual(request_record.request_status, RequestStatus.ACTIVE.value)

    def test_provisioning_marks_failed_when_connector_returns_failure(self) -> None:
        service = self._build_service(
            ConnectorProvisionResponse(
                connector_status=ConnectorStatus.FAILED,
                provider_request_id="feishu_req_failed_001",
                provider_task_id="feishu_task_failed_001",
                effective_at=None,
                retryable=True,
                error_code="FEISHU_PROVISION_FAILED",
                error_message="connector failed",
                raw_payload={"mode": "failed"},
            )
        )

        result = service.provision_grant(self._build_command("req_approved_001", "grt_failed_001"))

        self.assertEqual(result.grant_status, GrantStatus.PROVISION_FAILED)
        self.assertEqual(result.connector_status, ConnectorStatus.FAILED)
        self.assertEqual(result.request_status, RequestStatus.FAILED)
        self.assertEqual(result.connector_task_status, TaskStatus.FAILED)

        request_record = self.permission_request_repository.get("req_approved_001")
        assert request_record is not None
        self.assertEqual(request_record.failed_reason, "connector failed")
        self.assertEqual(
            [event.event_type for event in self.event_repository.items],
            ["grant.provisioning_requested", "grant.provision_failed"],
        )
        self.assertEqual(self.audit_repository.items[-1].result, AuditResult.FAIL.value)

    def test_provisioning_persists_failed_writeback_before_raising_connector_unavailable(self) -> None:
        connector = _UnavailableConnector("stub mode bogus is unavailable")
        service = self._build_service(
            ConnectorProvisionResponse(
                connector_status=ConnectorStatus.ACCEPTED,
                provider_request_id="unused",
                provider_task_id="unused",
                effective_at=None,
                retryable=True,
                error_code=None,
                error_message=None,
                raw_payload={"mode": "accepted"},
            ),
            connector=connector,
        )

        with self.assertRaises(DomainError) as raised:
            service.provision_grant(self._build_command("req_approved_001", "grt_unavailable_001"))

        self.assertEqual(raised.exception.code, ErrorCode.CONNECTOR_UNAVAILABLE)
        self.assertEqual(connector.calls, 1)

        grant_record = self.access_grant_repository.get("grt_unavailable_001")
        self.assertIsNotNone(grant_record)
        assert grant_record is not None
        self.assertEqual(grant_record.grant_status, GrantStatus.PROVISION_FAILED.value)
        self.assertEqual(grant_record.connector_status, ConnectorStatus.FAILED.value)
        self.assertEqual(grant_record.reconcile_status, "Error")

        request_record = self.permission_request_repository.get("req_approved_001")
        assert request_record is not None
        self.assertEqual(request_record.grant_status, GrantStatus.PROVISION_FAILED.value)
        self.assertEqual(request_record.request_status, RequestStatus.FAILED.value)
        self.assertEqual(request_record.current_task_state, TaskStatus.FAILED.value)
        self.assertEqual(request_record.failed_reason, "stub mode bogus is unavailable")

        tasks = list(self.connector_task_repository.items.values())
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0].task_status, TaskStatus.FAILED.value)
        self.assertEqual(tasks[0].last_error_code, "CONNECTOR_UNAVAILABLE")
        self.assertEqual(tasks[0].last_error_message, "stub mode bogus is unavailable")

        self.assertEqual(
            [event.event_type for event in self.event_repository.items],
            ["grant.provisioning_requested", "grant.provision_failed"],
        )
        self.assertEqual(self.audit_repository.items[-1].event_type, "grant.provision_failed")
        self.assertEqual(self.audit_repository.items[-1].result, AuditResult.FAIL.value)
        self.assertEqual(self.audit_repository.items[-1].reason, "stub mode bogus is unavailable")

    def test_duplicate_provision_request_returns_existing_state_without_new_task(self) -> None:
        existing_grant = AccessGrantRecord(
            grant_id="grt_existing_001",
            request_id="req_approved_001",
            resource_key="sales.q3_report",
            resource_type="report",
            action="read",
            grant_status=GrantStatus.PROVISIONING.value,
            connector_status=ConnectorStatus.ACCEPTED.value,
            reconcile_status="AwaitingConfirmation",
            effective_at=None,
            expire_at=self.fixed_now + timedelta(days=7),
            revoked_at=None,
            revocation_reason=None,
            created_at=self.fixed_now,
            updated_at=self.fixed_now,
        )
        self.access_grant_repository.add(existing_grant)
        existing_task = ConnectorTaskRecord(
            task_id="ctk_existing_001",
            grant_id="grt_existing_001",
            request_id="req_approved_001",
            task_type="provision",
            task_status=TaskStatus.SUCCEEDED.value,
            retry_count=0,
            max_retry_count=3,
            last_error_code=None,
            last_error_message=None,
            payload_json={"mode": "accepted"},
            scheduled_at=self.fixed_now,
            processed_at=self.fixed_now,
            created_at=self.fixed_now,
            updated_at=self.fixed_now,
        )
        self.connector_task_repository.add(existing_task)

        connector = _FakeConnector(
            ConnectorProvisionResponse(
                connector_status=ConnectorStatus.ACCEPTED,
                provider_request_id="unused",
                provider_task_id="unused",
                effective_at=None,
                retryable=True,
                error_code=None,
                error_message=None,
                raw_payload={"mode": "accepted"},
            )
        )
        service = self._build_service(connector.response, connector=connector)

        result = service.provision_grant(self._build_command("req_approved_001", "grt_existing_001"))

        self.assertEqual(result.grant_id, "grt_existing_001")
        self.assertEqual(result.connector_task_id, "ctk_existing_001")
        self.assertEqual(connector.calls, 0)
        self.assertEqual(len(self.connector_task_repository.items), 1)

    def test_force_retry_after_failure_creates_new_task(self) -> None:
        failed_grant = AccessGrantRecord(
            grant_id="grt_retry_001",
            request_id="req_failed_001",
            resource_key="sales.q3_report",
            resource_type="report",
            action="read",
            grant_status=GrantStatus.PROVISION_FAILED.value,
            connector_status=ConnectorStatus.FAILED.value,
            reconcile_status="Error",
            effective_at=None,
            expire_at=self.fixed_now + timedelta(days=7),
            revoked_at=None,
            revocation_reason=None,
            created_at=self.fixed_now - timedelta(hours=1),
            updated_at=self.fixed_now - timedelta(hours=1),
        )
        self.access_grant_repository.add(failed_grant)
        failed_task = ConnectorTaskRecord(
            task_id="ctk_retry_prev_001",
            grant_id="grt_retry_001",
            request_id="req_failed_001",
            task_type="provision",
            task_status=TaskStatus.FAILED.value,
            retry_count=0,
            max_retry_count=3,
            last_error_code="ERR_PREV",
            last_error_message="previous",
            payload_json={"mode": "failed"},
            scheduled_at=self.fixed_now - timedelta(hours=1),
            processed_at=self.fixed_now - timedelta(hours=1),
            created_at=self.fixed_now - timedelta(hours=1),
            updated_at=self.fixed_now - timedelta(hours=1),
        )
        self.connector_task_repository.add(failed_task)

        service = self._build_service(
            ConnectorProvisionResponse(
                connector_status=ConnectorStatus.ACCEPTED,
                provider_request_id="feishu_req_retry_001",
                provider_task_id="feishu_task_retry_001",
                effective_at=None,
                retryable=True,
                error_code=None,
                error_message=None,
                raw_payload={"mode": "accepted"},
            )
        )

        result = service.provision_grant(
            self._build_command("req_failed_001", "grt_retry_001", force_retry=True)
        )

        self.assertEqual(result.retry_count, 1)
        self.assertEqual(len(self.connector_task_repository.items), 2)
        self.assertEqual(
            [event.event_type for event in self.event_repository.items],
            ["grant.retry_requested", "grant.provisioning_requested", "grant.accepted"],
        )

    def test_provisioning_rejects_request_without_approved_status(self) -> None:
        service = self._build_service(
            ConnectorProvisionResponse(
                connector_status=ConnectorStatus.ACCEPTED,
                provider_request_id="unused",
                provider_task_id="unused",
                effective_at=None,
                retryable=True,
                error_code=None,
                error_message=None,
                raw_payload={"mode": "accepted"},
            )
        )

        with self.assertRaises(DomainError) as raised:
            service.provision_grant(self._build_command("req_pending_001", "grt_invalid_001"))

        self.assertEqual(raised.exception.code, ErrorCode.APPROVAL_NOT_APPROVED)

    def _build_service(
        self,
        response: ConnectorProvisionResponse,
        *,
        connector: _FakeConnector | None = None,
    ) -> ProvisioningService:
        return ProvisioningService(
            permission_request_repository=self.permission_request_repository,
            access_grant_repository=self.access_grant_repository,
            connector_task_repository=self.connector_task_repository,
            permission_request_event_repository=self.event_repository,
            audit_repository=self.audit_repository,
            connector=connector or _FakeConnector(response),
            now_provider=lambda: self.fixed_now,
        )

    def _build_command(
        self,
        request_id: str,
        grant_id: str,
        *,
        force_retry: bool = False,
    ) -> GrantProvisionInput:
        return GrantProvisionInput(
            grant_id=grant_id,
            permission_request_id=request_id,
            policy_version="perm-map.v1",
            delegation_id="dlg_123",
            api_request_id="req_trace_unit",
            operator_user_id="system_worker",
            force_retry=force_retry,
        )

    def _build_request_record(
        self,
        *,
        request_id: str,
        approval_status: str,
        grant_status: str,
        request_status: str,
        failed_reason: str | None = None,
    ) -> PermissionRequestRecord:
        return PermissionRequestRecord(
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
            approval_status=approval_status,
            grant_status=grant_status,
            request_status=request_status,
            current_task_state=TaskStatus.SUCCEEDED.value,
            policy_version="perm-map.v1",
            renew_round=0,
            failed_reason=failed_reason,
            created_at=self.fixed_now - timedelta(minutes=5),
            updated_at=self.fixed_now - timedelta(minutes=5),
        )


if __name__ == "__main__":
    unittest.main()
