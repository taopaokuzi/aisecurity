from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from packages.application import GrantLifecycleService, GrantRenewInput
from packages.domain import (
    ApprovalStatus,
    DomainError,
    ErrorCode,
    GrantStatus,
    OperatorType,
    RequestStatus,
    TaskStatus,
)
from packages.infrastructure.db.models import (
    AccessGrantRecord,
    AuditRecordRecord,
    NotificationTaskRecord,
    PermissionRequestEventRecord,
    PermissionRequestRecord,
)


class _FakePermissionRequestRepository:
    def __init__(self, items: dict[str, PermissionRequestRecord]) -> None:
        self.items = items

    def add(self, instance: PermissionRequestRecord) -> PermissionRequestRecord:
        self.items[instance.request_id] = instance
        return instance

    def get(self, identifier: str) -> PermissionRequestRecord | None:
        return self.items.get(identifier)

    def list_for_user(self, user_id: str, *, limit: int | None = 100) -> list[PermissionRequestRecord]:
        items = [
            item
            for item in self.items.values()
            if item.user_id == user_id
        ]
        items.sort(key=lambda item: item.created_at, reverse=True)
        if limit is not None:
            items = items[:limit]
        return items


class _FakeAccessGrantRepository:
    def __init__(self, items: dict[str, AccessGrantRecord]) -> None:
        self.items = items

    def add(self, instance: AccessGrantRecord) -> AccessGrantRecord:
        self.items[instance.grant_id] = instance
        return instance

    def get(self, identifier: str) -> AccessGrantRecord | None:
        return self.items.get(identifier)

    def list_due_for_expiring(
        self,
        *,
        current_time: datetime,
        cutoff: datetime,
    ) -> list[AccessGrantRecord]:
        return sorted(
            [
                item
                for item in self.items.values()
                if item.expire_at > current_time
                and item.expire_at <= cutoff
                and item.grant_status in {"Active", "Expiring"}
            ],
            key=lambda item: item.expire_at,
        )

    def list_due_for_expiration(self, *, current_time: datetime) -> list[AccessGrantRecord]:
        return sorted(
            [
                item
                for item in self.items.values()
                if item.expire_at <= current_time
                and item.grant_status in {"Active", "Expiring"}
            ],
            key=lambda item: item.expire_at,
        )


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

    def get_latest_by_event_and_idempotency_key(
        self,
        *,
        actor_type: str,
        actor_id: str | None,
        event_type: str,
        idempotency_key: str,
    ) -> AuditRecordRecord | None:
        for item in reversed(self.items):
            metadata = item.metadata_json or {}
            if (
                item.actor_type == actor_type
                and item.actor_id == actor_id
                and item.event_type == event_type
                and metadata.get("idempotency_key") == idempotency_key
            ):
                return item
        return None


class _FakeNotificationTaskRepository:
    def __init__(self) -> None:
        self.items: dict[str, NotificationTaskRecord] = {}

    def add(self, instance: NotificationTaskRecord) -> NotificationTaskRecord:
        self.items[instance.task_id] = instance
        return instance

    def list_for_grant(self, grant_id: str) -> list[NotificationTaskRecord]:
        items = [item for item in self.items.values() if item.grant_id == grant_id]
        items.sort(key=lambda item: item.created_at, reverse=True)
        return items


class GrantLifecycleServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixed_now = datetime(2026, 4, 17, 12, 0, tzinfo=timezone.utc)
        self.permission_request_repository = _FakePermissionRequestRepository(
            {
                "req_active_001": self._build_request_record(
                    request_id="req_active_001",
                    request_status=RequestStatus.ACTIVE.value,
                    grant_status=GrantStatus.ACTIVE.value,
                    renew_round=0,
                ),
                "req_expired_001": self._build_request_record(
                    request_id="req_expired_001",
                    request_status=RequestStatus.EXPIRED.value,
                    grant_status=GrantStatus.EXPIRED.value,
                    renew_round=0,
                ),
            }
        )
        self.access_grant_repository = _FakeAccessGrantRepository(
            {
                "grt_active_001": self._build_grant_record(
                    grant_id="grt_active_001",
                    request_id="req_active_001",
                    grant_status=GrantStatus.ACTIVE.value,
                    expire_at=self.fixed_now + timedelta(hours=12),
                ),
                "grt_expired_001": self._build_grant_record(
                    grant_id="grt_expired_001",
                    request_id="req_expired_001",
                    grant_status=GrantStatus.EXPIRED.value,
                    expire_at=self.fixed_now - timedelta(hours=1),
                ),
            }
        )
        self.event_repository = _FakePermissionRequestEventRepository()
        self.audit_repository = _FakeAuditRepository()
        self.notification_task_repository = _FakeNotificationTaskRepository()

    def test_process_grant_lifecycle_marks_grant_expiring_and_records_reminder(self) -> None:
        service = self._build_service()

        result = service.process_grant_lifecycle()

        self.assertEqual(result.expiring_count, 1)
        self.assertEqual(result.reminder_count, 1)
        self.assertEqual(result.expired_count, 0)

        grant_record = self.access_grant_repository.get("grt_active_001")
        request_record = self.permission_request_repository.get("req_active_001")
        assert grant_record is not None
        assert request_record is not None
        self.assertEqual(grant_record.grant_status, GrantStatus.EXPIRING.value)
        self.assertEqual(request_record.request_status, RequestStatus.EXPIRING.value)
        self.assertEqual(request_record.grant_status, GrantStatus.EXPIRING.value)

        reminder_tasks = self.notification_task_repository.list_for_grant("grt_active_001")
        self.assertEqual(len(reminder_tasks), 1)
        self.assertEqual(reminder_tasks[0].task_type, "GrantExpirationReminder")
        self.assertEqual(reminder_tasks[0].task_status, "Succeeded")
        self.assertEqual(
            [event.event_type for event in self.event_repository.items],
            ["grant.expiring"],
        )

    def test_renew_grant_creates_follow_up_request_with_original_context(self) -> None:
        service = self._build_service()

        result = service.renew_grant(
            GrantRenewInput(
                grant_id="grt_active_001",
                requested_duration="P7D",
                reason="项目仍在进行，需要继续查看",
                api_request_id="req_trace_renew_001",
                operator_user_id="user_001",
                operator_type=OperatorType.USER,
                trace_id="trace_renew_001",
                idempotency_key="renew-key-001",
            )
        )

        self.assertEqual(result.grant_id, "grt_active_001")
        self.assertEqual(result.renew_round, 1)
        self.assertEqual(result.request_status, RequestStatus.PENDING_APPROVAL)

        renewal_request = self.permission_request_repository.get(result.renewal_request_id)
        self.assertIsNotNone(renewal_request)
        assert renewal_request is not None
        self.assertEqual(renewal_request.renew_round, 1)
        self.assertEqual(renewal_request.request_status, RequestStatus.PENDING_APPROVAL.value)
        renewal_context = renewal_request.structured_request_json["renewal_context"]
        self.assertEqual(renewal_context["grant_id"], "grt_active_001")
        self.assertEqual(renewal_context["source_request_id"], "req_active_001")
        self.assertEqual(renewal_context["root_request_id"], "req_active_001")
        self.assertEqual(renewal_context["requested_duration"], "P7D")

        self.assertEqual(
            [event.event_type for event in self.event_repository.items],
            ["grant.renew_requested", "grant.renew_requested"],
        )
        self.assertEqual(self.audit_repository.items[-1].event_type, "grant.renew_requested")

    def test_process_grant_lifecycle_expires_due_grant(self) -> None:
        self.permission_request_repository.items["req_due_001"] = self._build_request_record(
            request_id="req_due_001",
            request_status=RequestStatus.ACTIVE.value,
            grant_status=GrantStatus.ACTIVE.value,
            renew_round=0,
        )
        self.access_grant_repository.items["grt_due_001"] = self._build_grant_record(
            grant_id="grt_due_001",
            request_id="req_due_001",
            grant_status=GrantStatus.ACTIVE.value,
            expire_at=self.fixed_now - timedelta(minutes=5),
        )

        service = GrantLifecycleService(
            permission_request_repository=self.permission_request_repository,
            access_grant_repository=self.access_grant_repository,
            permission_request_event_repository=self.event_repository,
            audit_repository=self.audit_repository,
            notification_task_repository=self.notification_task_repository,
            now_provider=lambda: self.fixed_now,
            reminder_lead_time=timedelta(hours=1),
        )
        result = service.process_grant_lifecycle()

        self.assertEqual(result.expired_count, 1)

        grant_record = self.access_grant_repository.get("grt_due_001")
        request_record = self.permission_request_repository.get("req_due_001")
        assert grant_record is not None
        assert request_record is not None
        self.assertEqual(grant_record.grant_status, GrantStatus.EXPIRED.value)
        self.assertEqual(request_record.request_status, RequestStatus.EXPIRED.value)
        self.assertEqual(request_record.grant_status, GrantStatus.EXPIRED.value)
        self.assertEqual(
            [event.event_type for event in self.event_repository.items],
            ["grant.expiring", "grant.expired"],
        )
        self.assertEqual(self.audit_repository.items[-1].event_type, "grant.expired")

    def test_complete_approved_renewal_rebinds_existing_grant(self) -> None:
        self.permission_request_repository.items["req_active_001"].request_status = RequestStatus.EXPIRING.value
        self.permission_request_repository.items["req_active_001"].grant_status = GrantStatus.EXPIRING.value
        self.access_grant_repository.items["grt_active_001"].grant_status = GrantStatus.EXPIRING.value
        self.permission_request_repository.items["req_renew_approved_001"] = self._build_request_record(
            request_id="req_renew_approved_001",
            request_status=RequestStatus.APPROVED.value,
            approval_status=ApprovalStatus.APPROVED.value,
            grant_status=GrantStatus.EXPIRING.value,
            renew_round=1,
            structured_request_json={
                "approval_route": ["manager"],
                "renewal_context": {
                    "grant_id": "grt_active_001",
                    "source_request_id": "req_active_001",
                    "root_request_id": "req_active_001",
                    "requested_duration": "P7D",
                },
            },
        )

        service = self._build_service()
        result = service.complete_approved_renewal(
            permission_request_id="req_renew_approved_001",
            api_request_id="req_trace_renew_approved_001",
            operator_user_id="approval_callback",
            operator_type=OperatorType.SYSTEM,
            trace_id="trace_renew_approved_001",
        )

        self.assertEqual(result.grant_id, "grt_active_001")
        self.assertEqual(result.request_status, RequestStatus.ACTIVE)
        self.assertEqual(
            result.expire_at,
            self.fixed_now + timedelta(hours=12) + timedelta(days=7),
        )

        source_request = self.permission_request_repository.get("req_active_001")
        renewal_request = self.permission_request_repository.get("req_renew_approved_001")
        grant_record = self.access_grant_repository.get("grt_active_001")
        assert source_request is not None
        assert renewal_request is not None
        assert grant_record is not None
        self.assertEqual(source_request.request_status, RequestStatus.EXPIRED.value)
        self.assertEqual(renewal_request.request_status, RequestStatus.ACTIVE.value)
        self.assertEqual(grant_record.request_id, "req_renew_approved_001")
        self.assertEqual(grant_record.grant_status, GrantStatus.ACTIVE.value)

    def test_renew_grant_rejects_illegal_status(self) -> None:
        service = self._build_service()

        with self.assertRaises(DomainError) as raised:
            service.renew_grant(
                GrantRenewInput(
                    grant_id="grt_expired_001",
                    requested_duration="P7D",
                    reason="到期后尝试续期",
                    api_request_id="req_trace_renew_002",
                    operator_user_id="user_001",
                    operator_type=OperatorType.USER,
                )
            )

        self.assertEqual(raised.exception.code, ErrorCode.REQUEST_STATUS_INVALID)

    def _build_service(self) -> GrantLifecycleService:
        return GrantLifecycleService(
            permission_request_repository=self.permission_request_repository,
            access_grant_repository=self.access_grant_repository,
            permission_request_event_repository=self.event_repository,
            audit_repository=self.audit_repository,
            notification_task_repository=self.notification_task_repository,
            now_provider=lambda: self.fixed_now,
            reminder_lead_time=timedelta(days=1),
        )

    def _build_request_record(
        self,
        *,
        request_id: str,
        request_status: str,
        grant_status: str,
        renew_round: int,
        approval_status: str = ApprovalStatus.APPROVED.value,
        structured_request_json: dict[str, object] | None = None,
    ) -> PermissionRequestRecord:
        return PermissionRequestRecord(
            request_id=request_id,
            user_id="user_001",
            agent_id="agent_perm_assistant_v1",
            delegation_id="dlg_123",
            raw_text="需要只读权限",
            resource_key="sales.q3_report",
            resource_type="report",
            action="read",
            constraints_json=None,
            requested_duration="P7D",
            structured_request_json=structured_request_json or {"approval_route": ["manager"]},
            suggested_permission="report:sales.q3:read",
            risk_level="Low",
            approval_status=approval_status,
            grant_status=grant_status,
            request_status=request_status,
            current_task_state=TaskStatus.SUCCEEDED.value,
            policy_version="perm-map.v1",
            renew_round=renew_round,
            failed_reason=None,
            created_at=self.fixed_now,
            updated_at=self.fixed_now,
        )

    def _build_grant_record(
        self,
        *,
        grant_id: str,
        request_id: str,
        grant_status: str,
        expire_at: datetime,
    ) -> AccessGrantRecord:
        return AccessGrantRecord(
            grant_id=grant_id,
            request_id=request_id,
            resource_key="sales.q3_report",
            resource_type="report",
            action="read",
            grant_status=grant_status,
            connector_status="Applied",
            reconcile_status="Confirmed",
            effective_at=self.fixed_now - timedelta(days=1),
            expire_at=expire_at,
            revoked_at=None,
            revocation_reason=None,
            created_at=self.fixed_now - timedelta(days=1),
            updated_at=self.fixed_now,
        )


if __name__ == "__main__":
    unittest.main()
