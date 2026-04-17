from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from packages.application import (
    PermissionRequestEvaluationInput,
    PermissionRequestEvaluationService,
)
from packages.domain import (
    ApprovalStatus,
    DomainError,
    ErrorCode,
    GrantStatus,
    OperatorType,
    RequestStatus,
    RiskLevel,
    TaskStatus,
    UserStatus,
)
from packages.infrastructure.db.models import (
    AuditRecordRecord,
    PermissionRequestEventRecord,
    PermissionRequestRecord,
    UserRecord,
)
from packages.infrastructure.permission_request_parser import PermissionRequestParser
from packages.policy import create_policy_engine


class _FakeLookupRepository:
    def __init__(self, items: dict[str, object] | None = None) -> None:
        self.items = items or {}

    def get(self, identifier: str) -> object | None:
        return self.items.get(identifier)


class _FakePermissionRequestRepository(_FakeLookupRepository):
    pass


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


class PermissionRequestEvaluationServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixed_now = datetime(2026, 4, 17, 10, 0, tzinfo=timezone.utc)
        self.user_repository = _FakeLookupRepository(
            {
                "user_sales": self._build_user(
                    user_id="user_sales",
                    department_name="sales",
                ),
                "user_finance": self._build_user(
                    user_id="user_finance",
                    department_name="finance",
                ),
            }
        )
        self.permission_request_repository = _FakePermissionRequestRepository(
            {
                "req_main": self._build_request(
                    request_id="req_main",
                    user_id="user_sales",
                    raw_text="我需要查看销售部 Q3 报表，但不需要修改权限",
                ),
                "req_cross": self._build_request(
                    request_id="req_cross",
                    user_id="user_finance",
                    raw_text="我需要查看销售部 Q3 报表，但不需要修改权限",
                ),
                "req_sensitive": self._build_request(
                    request_id="req_sensitive",
                    user_id="user_finance",
                    raw_text="我需要查看薪资报表",
                ),
                "req_fuzzy": self._build_request(
                    request_id="req_fuzzy",
                    user_id="user_sales",
                    raw_text="帮我把那个权限赶紧处理一下。",
                ),
                "req_done": self._build_request(
                    request_id="req_done",
                    user_id="user_sales",
                    raw_text="我需要查看销售部 Q3 报表",
                    request_status=RequestStatus.PENDING_APPROVAL.value,
                    approval_status=ApprovalStatus.PENDING.value,
                    current_task_state=TaskStatus.SUCCEEDED.value,
                    resource_key="sales.q3_report",
                    resource_type="report",
                    action="read",
                    requested_duration="P7D",
                    structured_request_json={"approval_route": ["manager"]},
                    suggested_permission="report:sales.q3:read",
                    risk_level=RiskLevel.MEDIUM.value,
                    policy_version="perm-map.v1",
                ),
            }
        )
        self.permission_request_event_repository = _FakePermissionRequestEventRepository()
        self.audit_repository = _FakeAuditRepository()
        self.service = PermissionRequestEvaluationService(
            user_repository=self.user_repository,
            permission_request_repository=self.permission_request_repository,
            permission_request_event_repository=self.permission_request_event_repository,
            audit_repository=self.audit_repository,
            parser=PermissionRequestParser(),
            policy_engine=create_policy_engine(),
            now_provider=lambda: self.fixed_now,
        )

    def test_evaluate_main_case_returns_read_only_suggestion(self) -> None:
        result = self.service.evaluate_permission_request(
            PermissionRequestEvaluationInput(
                permission_request_id="req_main",
                request_id="req_trace_301",
                operator_user_id="system_worker",
                operator_type=OperatorType.SYSTEM,
            )
        )

        record = self.permission_request_repository.get("req_main")
        assert isinstance(record, PermissionRequestRecord)
        self.assertEqual(result.request_id, "req_main")
        self.assertEqual(result.resource_key, "sales.q3_report")
        self.assertEqual(result.resource_type, "report")
        self.assertEqual(result.action, "read")
        self.assertEqual(result.requested_duration, "P7D")
        self.assertEqual(result.suggested_permission, "report:sales.q3:read")
        self.assertEqual(result.risk_level, RiskLevel.LOW)
        self.assertEqual(result.approval_route, ())
        self.assertEqual(result.approval_status, ApprovalStatus.NOT_REQUIRED)
        self.assertEqual(result.request_status, RequestStatus.PENDING_APPROVAL)
        self.assertEqual(record.request_status, RequestStatus.PENDING_APPROVAL.value)
        self.assertEqual(record.current_task_state, TaskStatus.SUCCEEDED.value)
        self.assertEqual(record.suggested_permission, "report:sales.q3:read")
        self.assertEqual(record.policy_version, "perm-map.v1")
        self.assertEqual(len(self.permission_request_event_repository.added), 2)
        self.assertEqual(
            [event.event_type for event in self.permission_request_event_repository.added],
            ["request.evaluation_started", "request.evaluated"],
        )
        self.assertEqual(self.audit_repository.added[-1].event_type, "request.evaluated")

    def test_cross_department_access_requires_manager_approval(self) -> None:
        result = self.service.evaluate_permission_request(
            PermissionRequestEvaluationInput(
                permission_request_id="req_cross",
                request_id="req_trace_302",
                operator_user_id="system_worker",
                operator_type=OperatorType.SYSTEM,
            )
        )

        self.assertEqual(result.risk_level, RiskLevel.MEDIUM)
        self.assertEqual(result.approval_route, ("manager",))
        self.assertEqual(result.approval_status, ApprovalStatus.PENDING)
        assert result.structured_request is not None
        policy_payload = result.structured_request["policy_evaluation"]
        assert isinstance(policy_payload, dict)
        self.assertTrue(policy_payload["cross_department"])
        self.assertIn("cross_department_access", policy_payload["triggered_risk_rules"])

    def test_high_sensitive_resource_requires_security_escalation(self) -> None:
        result = self.service.evaluate_permission_request(
            PermissionRequestEvaluationInput(
                permission_request_id="req_sensitive",
                request_id="req_trace_303",
                operator_user_id="system_worker",
                operator_type=OperatorType.SYSTEM,
            )
        )

        self.assertEqual(result.resource_key, "finance.payroll")
        self.assertEqual(result.suggested_permission, "report:finance.payroll:read")
        self.assertEqual(result.risk_level, RiskLevel.HIGH)
        self.assertEqual(result.approval_route, ("manager", "security_admin"))

    def test_ambiguous_request_follows_safer_manual_review_path(self) -> None:
        result = self.service.evaluate_permission_request(
            PermissionRequestEvaluationInput(
                permission_request_id="req_fuzzy",
                request_id="req_trace_304",
                operator_user_id="system_worker",
                operator_type=OperatorType.SYSTEM,
            )
        )

        self.assertIsNone(result.resource_key)
        self.assertIsNone(result.action)
        self.assertIsNone(result.suggested_permission)
        self.assertEqual(result.risk_level, RiskLevel.HIGH)
        self.assertEqual(result.approval_route, ("manager", "security_admin"))
        assert result.structured_request is not None
        policy_payload = result.structured_request["policy_evaluation"]
        assert isinstance(policy_payload, dict)
        self.assertTrue(policy_payload["fallback_to_safe_path"])
        self.assertEqual(policy_payload["recommended_path"], "manual_review")

    def test_repeated_evaluation_from_pending_approval_is_rejected(self) -> None:
        with self.assertRaises(DomainError) as context:
            self.service.evaluate_permission_request(
                PermissionRequestEvaluationInput(
                    permission_request_id="req_done",
                    request_id="req_trace_305",
                    operator_user_id="system_worker",
                    operator_type=OperatorType.SYSTEM,
                )
            )

        self.assertEqual(context.exception.code, ErrorCode.REQUEST_STATUS_INVALID)

    def _build_user(self, *, user_id: str, department_name: str) -> UserRecord:
        return UserRecord(
            user_id=user_id,
            employee_no=f"E_{user_id}",
            display_name=user_id,
            email=f"{user_id}@example.com",
            department_id=f"dept_{department_name}",
            department_name=department_name,
            manager_user_id=None,
            user_status=UserStatus.ACTIVE.value,
            identity_source="SSO",
            created_at=self.fixed_now - timedelta(days=1),
            updated_at=self.fixed_now - timedelta(days=1),
        )

    def _build_request(
        self,
        *,
        request_id: str,
        user_id: str,
        raw_text: str,
        request_status: str = RequestStatus.SUBMITTED.value,
        approval_status: str = ApprovalStatus.NOT_REQUIRED.value,
        current_task_state: str | None = None,
        resource_key: str | None = None,
        resource_type: str | None = None,
        action: str | None = None,
        requested_duration: str | None = None,
        structured_request_json: dict[str, object] | None = None,
        suggested_permission: str | None = None,
        risk_level: str | None = None,
        policy_version: str | None = None,
    ) -> PermissionRequestRecord:
        return PermissionRequestRecord(
            request_id=request_id,
            user_id=user_id,
            agent_id="agent_perm_assistant_v1",
            delegation_id="dlg_123",
            raw_text=raw_text,
            resource_key=resource_key,
            resource_type=resource_type,
            action=action,
            constraints_json=None,
            requested_duration=requested_duration,
            structured_request_json=structured_request_json,
            suggested_permission=suggested_permission,
            risk_level=risk_level,
            approval_status=approval_status,
            grant_status=GrantStatus.NOT_CREATED.value,
            request_status=request_status,
            current_task_state=current_task_state,
            policy_version=policy_version,
            renew_round=0,
            failed_reason=None,
            created_at=self.fixed_now - timedelta(hours=1),
            updated_at=self.fixed_now - timedelta(hours=1),
        )


if __name__ == "__main__":
    unittest.main()
