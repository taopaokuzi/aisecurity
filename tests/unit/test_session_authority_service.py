from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from packages.application import (
    AgentDisableInput,
    SessionAuthority,
    SessionBindingInput,
    SessionRevokeInput,
)
from packages.domain import (
    ApprovalStatus,
    ConnectorStatus,
    GrantStatus,
    OperatorType,
    RequestStatus,
    SessionStatus,
    TaskStatus,
)
from packages.infrastructure.db.models import (
    AccessGrantRecord,
    AgentIdentityRecord,
    AuditRecordRecord,
    ConnectorTaskRecord,
    PermissionRequestEventRecord,
    PermissionRequestRecord,
    SessionContextRecord,
)
from packages.infrastructure.feishu_connector import (
    ConnectorSessionRevokeCommand,
    ConnectorSessionRevokeResponse,
    FeishuSessionConnector,
)


class _FakePermissionRequestRepository:
    def __init__(self, items: dict[str, PermissionRequestRecord]) -> None:
        self.items = items

    def get(self, identifier: str) -> PermissionRequestRecord | None:
        return self.items.get(identifier)


class _FakeAccessGrantRepository:
    def __init__(self, items: dict[str, AccessGrantRecord]) -> None:
        self.items = items

    def get(self, identifier: str) -> AccessGrantRecord | None:
        return self.items.get(identifier)


class _FakeSessionContextRepository:
    def __init__(self, items: dict[str, SessionContextRecord]) -> None:
        self.items = items

    def add(self, instance: SessionContextRecord) -> SessionContextRecord:
        self.items[instance.global_session_id] = instance
        return instance

    def get(self, identifier: str) -> SessionContextRecord | None:
        return self.items.get(identifier)

    def get_by_grant_id(self, grant_id: str) -> SessionContextRecord | None:
        for item in self.items.values():
            if item.grant_id == grant_id:
                return item
        return None

    def list_for_agent(
        self,
        agent_id: str,
        *,
        statuses: list[str] | tuple[str, ...] | None = None,
        limit: int | None = 100,
    ) -> list[SessionContextRecord]:
        items = [item for item in self.items.values() if item.agent_id == agent_id]
        if statuses:
            items = [item for item in items if item.session_status in set(statuses)]
        items.sort(key=lambda item: item.updated_at, reverse=True)
        if limit is not None:
            items = items[:limit]
        return items


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


class _FakeConnectorTaskRepository:
    def __init__(self) -> None:
        self.items: dict[str, ConnectorTaskRecord] = {}

    def add(self, instance: ConnectorTaskRecord) -> ConnectorTaskRecord:
        self.items[instance.task_id] = instance
        return instance

    def get(self, identifier: str) -> ConnectorTaskRecord | None:
        return self.items.get(identifier)

    def get_latest_session_revoke_for_session(
        self,
        *,
        global_session_id: str,
    ) -> ConnectorTaskRecord | None:
        candidates = [
            item
            for item in self.items.values()
            if item.task_type == "session_revoke"
            and (item.payload_json or {}).get("global_session_id") == global_session_id
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda item: item.created_at, reverse=True)
        return candidates[0]

    def list_pending_session_revoke_tasks(
        self,
        *,
        limit: int | None = 100,
    ) -> list[ConnectorTaskRecord]:
        items = [
            item
            for item in self.items.values()
            if item.task_type == "session_revoke"
            and item.task_status in {"Pending", "Retrying"}
        ]
        items.sort(key=lambda item: (item.scheduled_at, item.created_at))
        if limit is not None:
            items = items[:limit]
        return items


class _FakeAgentIdentityRepository:
    def __init__(self, items: dict[str, AgentIdentityRecord]) -> None:
        self.items = items

    def get(self, identifier: str) -> AgentIdentityRecord | None:
        return self.items.get(identifier)


class _SuccessConnector(FeishuSessionConnector):
    def __init__(self, *, fixed_now: datetime) -> None:
        self.fixed_now = fixed_now
        self.calls: list[ConnectorSessionRevokeCommand] = []

    def revoke_session(  # type: ignore[override]
        self,
        command: ConnectorSessionRevokeCommand,
    ) -> ConnectorSessionRevokeResponse:
        self.calls.append(command)
        return ConnectorSessionRevokeResponse(
            provider_request_id="feishu_revoke_req_001",
            provider_task_id="feishu_revoke_task_001",
            connector_session_ref=command.connector_session_ref,
            revoked_at=self.fixed_now,
            retryable=False,
            error_code=None,
            error_message=None,
            raw_payload={"mode": "success"},
        )


class _FailureConnector(FeishuSessionConnector):
    def __init__(self) -> None:
        self.calls: list[ConnectorSessionRevokeCommand] = []

    def revoke_session(  # type: ignore[override]
        self,
        command: ConnectorSessionRevokeCommand,
    ) -> ConnectorSessionRevokeResponse:
        self.calls.append(command)
        return ConnectorSessionRevokeResponse(
            provider_request_id="feishu_revoke_req_001",
            provider_task_id="feishu_revoke_task_001",
            connector_session_ref=command.connector_session_ref,
            revoked_at=None,
            retryable=True,
            error_code="FEISHU_SESSION_REVOKE_FAILED",
            error_message="connector revoke failed",
            raw_payload={"mode": "failed"},
        )


class SessionAuthorityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixed_now = datetime(2026, 4, 18, 1, 0, tzinfo=timezone.utc)
        self.permission_request_repository = _FakePermissionRequestRepository(
            {
                "req_active_001": self._build_request_record(),
            }
        )
        self.access_grant_repository = _FakeAccessGrantRepository(
            {
                "grt_active_001": self._build_grant_record(),
            }
        )
        self.session_context_repository = _FakeSessionContextRepository(
            {
                "gs_active_001": self._build_session_record(),
            }
        )
        self.event_repository = _FakePermissionRequestEventRepository()
        self.audit_repository = _FakeAuditRepository()
        self.connector_task_repository = _FakeConnectorTaskRepository()
        self.agent_repository = _FakeAgentIdentityRepository(
            {
                "agent_perm_assistant_v1": self._build_agent_record(),
            }
        )

    def test_manual_revoke_marks_session_revoking_and_creates_revoke_task(self) -> None:
        service = self._build_service(_SuccessConnector(fixed_now=self.fixed_now))

        result = service.request_session_revoke(
            SessionRevokeInput(
                global_session_id="gs_active_001",
                reason="Security admin revoked the session",
                cascade_connector_sessions=True,
                api_request_id="req_trace_session_001",
                operator_user_id="sec_admin_001",
                operator_type=OperatorType.SECURITY_ADMIN,
                trace_id="trace_session_001",
            )
        )

        self.assertEqual(result.session_status, SessionStatus.REVOKING)
        session_record = self.session_context_repository.get("gs_active_001")
        grant_record = self.access_grant_repository.get("grt_active_001")
        request_record = self.permission_request_repository.get("req_active_001")
        assert session_record is not None
        assert grant_record is not None
        assert request_record is not None
        self.assertEqual(session_record.session_status, SessionStatus.REVOKING.value)
        self.assertEqual(grant_record.grant_status, GrantStatus.REVOKING.value)
        self.assertEqual(request_record.grant_status, GrantStatus.REVOKING.value)
        self.assertEqual(request_record.current_task_state, TaskStatus.RUNNING.value)
        self.assertEqual(
            [event.event_type for event in self.event_repository.items],
            ["session.revoke_requested"],
        )
        self.assertEqual(len(self.connector_task_repository.items), 1)

    def test_bind_active_session_creates_or_maintains_global_session_id(self) -> None:
        service = self._build_service(_SuccessConnector(fixed_now=self.fixed_now))

        initial_status = service.get_session_status("gs_active_001")
        service.bind_active_session(
            SessionBindingInput(
                grant_id="grt_active_001",
                request_id="req_active_001",
                agent_id="agent_perm_assistant_v1",
                user_id="user_001",
                connector_session_ref="feishu_task_apply_002",
                task_session_id="ctk_provision_002",
            )
        )

        updated_status = service.get_session_status("gs_active_001")
        session_record = self.session_context_repository.get("gs_active_001")
        assert session_record is not None
        self.assertEqual(initial_status.global_session_id, updated_status.global_session_id)
        self.assertEqual(updated_status.session_status, SessionStatus.ACTIVE)
        self.assertEqual(session_record.connector_session_ref, "feishu_task_apply_002")
        self.assertEqual(session_record.task_session_id, "ctk_provision_002")

    def test_disable_agent_requests_revoke_for_related_active_sessions(self) -> None:
        service = self._build_service(_SuccessConnector(fixed_now=self.fixed_now))

        result = service.disable_agent_and_request_revoke(
            AgentDisableInput(
                agent_id="agent_perm_assistant_v1",
                reason="Security suspension",
                api_request_id="req_trace_disable_001",
                operator_user_id="it_admin_001",
                operator_type=OperatorType.IT_ADMIN,
                trace_id="trace_disable_001",
                cascade_connector_sessions=True,
            )
        )

        self.assertEqual(result.agent_status.value, "Disabled")
        self.assertEqual(result.revoked_session_count, 1)
        self.assertTrue(result.revoke_job_created)
        agent_record = self.agent_repository.get("agent_perm_assistant_v1")
        session_record = self.session_context_repository.get("gs_active_001")
        assert agent_record is not None
        assert session_record is not None
        self.assertEqual(agent_record.agent_status, "Disabled")
        self.assertEqual(session_record.session_status, SessionStatus.REVOKING.value)

    def test_process_pending_revoke_task_marks_session_revoked(self) -> None:
        service = self._build_service(_SuccessConnector(fixed_now=self.fixed_now))
        service.request_session_revoke(
            SessionRevokeInput(
                global_session_id="gs_active_001",
                reason="Manual revoke",
                cascade_connector_sessions=True,
                api_request_id="req_trace_session_002",
                operator_user_id="sec_admin_001",
                operator_type=OperatorType.SECURITY_ADMIN,
            )
        )

        result = service.process_pending_revoke_tasks()

        self.assertEqual(result.processed_count, 1)
        self.assertEqual(result.revoked_count, 1)
        session_record = self.session_context_repository.get("gs_active_001")
        grant_record = self.access_grant_repository.get("grt_active_001")
        request_record = self.permission_request_repository.get("req_active_001")
        assert session_record is not None
        assert grant_record is not None
        assert request_record is not None
        self.assertEqual(session_record.session_status, SessionStatus.REVOKED.value)
        self.assertEqual(grant_record.grant_status, GrantStatus.REVOKED.value)
        self.assertEqual(request_record.request_status, RequestStatus.REVOKED.value)
        self.assertEqual(request_record.grant_status, GrantStatus.REVOKED.value)
        self.assertEqual(
            [event.event_type for event in self.event_repository.items],
            ["session.revoke_requested", "session.revoked"],
        )

    def test_process_pending_revoke_task_marks_session_sync_failed(self) -> None:
        service = self._build_service(_FailureConnector())
        service.request_session_revoke(
            SessionRevokeInput(
                global_session_id="gs_active_001",
                reason="Manual revoke",
                cascade_connector_sessions=True,
                api_request_id="req_trace_session_003",
                operator_user_id="sec_admin_001",
                operator_type=OperatorType.SECURITY_ADMIN,
            )
        )

        result = service.process_pending_revoke_tasks()

        self.assertEqual(result.processed_count, 1)
        self.assertEqual(result.sync_failed_count, 1)
        session_record = self.session_context_repository.get("gs_active_001")
        grant_record = self.access_grant_repository.get("grt_active_001")
        request_record = self.permission_request_repository.get("req_active_001")
        assert session_record is not None
        assert grant_record is not None
        assert request_record is not None
        self.assertEqual(session_record.session_status, SessionStatus.SYNC_FAILED.value)
        self.assertEqual(grant_record.grant_status, GrantStatus.REVOKE_FAILED.value)
        self.assertEqual(request_record.grant_status, GrantStatus.REVOKE_FAILED.value)
        self.assertEqual(request_record.current_task_state, TaskStatus.FAILED.value)
        self.assertEqual(
            [event.event_type for event in self.event_repository.items],
            ["session.revoke_requested", "session.sync_failed"],
        )

    def _build_service(self, connector: FeishuSessionConnector) -> SessionAuthority:
        return SessionAuthority(
            permission_request_repository=self.permission_request_repository,
            access_grant_repository=self.access_grant_repository,
            session_context_repository=self.session_context_repository,
            permission_request_event_repository=self.event_repository,
            audit_repository=self.audit_repository,
            connector_task_repository=self.connector_task_repository,
            agent_identity_repository=self.agent_repository,
            connector=connector,
            now_provider=lambda: self.fixed_now,
        )

    def _build_request_record(self) -> PermissionRequestRecord:
        return PermissionRequestRecord(
            request_id="req_active_001",
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
            approval_status=ApprovalStatus.APPROVED.value,
            grant_status=GrantStatus.ACTIVE.value,
            request_status=RequestStatus.ACTIVE.value,
            current_task_state=TaskStatus.SUCCEEDED.value,
            policy_version="perm-map.v1",
            renew_round=0,
            failed_reason=None,
            created_at=self.fixed_now - timedelta(hours=1),
            updated_at=self.fixed_now - timedelta(hours=1),
        )

    def _build_grant_record(self) -> AccessGrantRecord:
        return AccessGrantRecord(
            grant_id="grt_active_001",
            request_id="req_active_001",
            resource_key="sales.q3_report",
            resource_type="report",
            action="read",
            grant_status=GrantStatus.ACTIVE.value,
            connector_status=ConnectorStatus.APPLIED.value,
            reconcile_status="Confirmed",
            effective_at=self.fixed_now - timedelta(minutes=30),
            expire_at=self.fixed_now + timedelta(days=7),
            revoked_at=None,
            revocation_reason=None,
            created_at=self.fixed_now - timedelta(hours=1),
            updated_at=self.fixed_now - timedelta(hours=1),
        )

    def _build_session_record(self) -> SessionContextRecord:
        return SessionContextRecord(
            global_session_id="gs_active_001",
            grant_id="grt_active_001",
            request_id="req_active_001",
            agent_id="agent_perm_assistant_v1",
            user_id="user_001",
            task_session_id="ctk_provision_001",
            connector_session_ref="feishu_task_apply_001",
            session_status=SessionStatus.ACTIVE.value,
            revocation_reason=None,
            last_sync_at=self.fixed_now - timedelta(minutes=30),
            revoked_at=None,
            created_at=self.fixed_now - timedelta(hours=1),
            updated_at=self.fixed_now - timedelta(hours=1),
        )

    def _build_agent_record(self) -> AgentIdentityRecord:
        return AgentIdentityRecord(
            agent_id="agent_perm_assistant_v1",
            agent_name="Permission Assistant",
            agent_version="v1",
            agent_type="first_party",
            agent_status="Active",
            capability_scope_json={
                "resource_types": ["report", "doc"],
                "allowed_actions": ["read", "request_edit"],
            },
            created_at=self.fixed_now - timedelta(days=1),
            updated_at=self.fixed_now - timedelta(days=1),
        )


if __name__ == "__main__":
    unittest.main()
