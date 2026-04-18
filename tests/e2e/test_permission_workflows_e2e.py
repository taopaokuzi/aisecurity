from __future__ import annotations

import os
import unittest
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from packages.application import AgentDisableInput, SessionAuthority, default_grant_id_for_request
from packages.infrastructure import (
    AccessGrantRepository,
    AgentIdentityRepository,
    AuditRecordRepository,
    ConnectorTaskRepository,
    PermissionRequestEventRepository,
    PermissionRequestRepository,
    SessionContextRepository,
)
from packages.infrastructure.db.models import AccessGrantRecord, PermissionRequestRecord, SessionContextRecord
from tests.support.feishu_flow import FeishuFlowHarness
from tests.support.mock_feishu import MockFeishuSessionConnector


class PermissionWorkflowsE2ETests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.harness = FeishuFlowHarness()
        cls.harness.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.harness.stop()

    def setUp(self) -> None:
        self.harness.reset_state()

    def test_same_department_employee_gets_sales_q3_read_only_access(self) -> None:
        request_id = self._submit_request("我需要查看销售部 Q3 报表，但不需要修改权限")
        evaluation = self._evaluate_request(request_id)
        self.assertEqual(evaluation["data"]["suggested_permission"], "report:sales.q3:read")
        self.assertEqual(evaluation["data"]["approval_status"], "NotRequired")

        with self.harness.session() as session:
            request_record = session.get(PermissionRequestRecord, request_id)
            self.assertEqual(request_record.request_status, "PendingApproval")
            self.assertEqual(request_record.approval_status, "NotRequired")
            self.assertEqual(request_record.suggested_permission, "report:sales.q3:read")

    def test_cross_department_high_sensitive_access_requires_approval_and_can_complete(self) -> None:
        request_id = self._submit_request("我需要查看薪资报表")
        evaluation = self._evaluate_request(request_id)
        self.assertEqual(evaluation["data"]["risk_level"], "High")
        self.assertEqual(evaluation["data"]["approval_route"], ["manager", "security_admin"])
        self.assertEqual(evaluation["data"]["approval_status"], "Pending")

        self._send_mock_approval(request_id=request_id, scenario="approved")

        with self.harness.session() as session:
            request_record = session.get(PermissionRequestRecord, request_id)
            grant_record = session.get(AccessGrantRecord, default_grant_id_for_request(request_id))
            self.assertEqual(request_record.request_status, "Active")
            self.assertEqual(grant_record.grant_status, "Active")

    def test_approval_passed_but_feishu_provision_failed(self) -> None:
        os.environ["MOCK_FEISHU_PROVISION_SCENARIO"] = "failed"
        request_id = self._submit_request("我需要查看薪资报表")
        self._evaluate_request(request_id)
        self._send_mock_approval(request_id=request_id, scenario="approved")

        with self.harness.session() as session:
            request_record = session.get(PermissionRequestRecord, request_id)
            grant_record = session.get(AccessGrantRecord, default_grant_id_for_request(request_id))
            self.assertEqual(request_record.request_status, "Failed")
            self.assertEqual(grant_record.grant_status, "ProvisionFailed")

    def test_authorization_expires_and_is_reclaimed_automatically(self) -> None:
        request_id, grant_id = self._submit_and_activate_payroll_request()

        with self.harness.session() as session:
            grant_record = session.get(AccessGrantRecord, grant_id)
            assert grant_record is not None
            grant_record.expire_at = datetime.now(timezone.utc) - timedelta(minutes=1)
            session.commit()

        self.harness.run_lifecycle_worker()
        self.harness.run_revoke_worker()

        with self.harness.session() as session:
            request_record = session.get(PermissionRequestRecord, request_id)
            grant_record = session.get(AccessGrantRecord, grant_id)
            session_context = session.scalar(
                select(SessionContextRecord).where(SessionContextRecord.grant_id == grant_id)
            )
            self.assertEqual(request_record.request_status, "Expired")
            self.assertEqual(grant_record.grant_status, "Expired")
            self.assertEqual(session_context.session_status, "Revoked")

    def test_agent_disable_triggers_revoke_and_takes_effect(self) -> None:
        request_id, grant_id = self._submit_and_activate_payroll_request()

        with self.harness.session() as session:
            service = SessionAuthority(
                permission_request_repository=PermissionRequestRepository(session),
                access_grant_repository=AccessGrantRepository(session),
                session_context_repository=SessionContextRepository(session),
                permission_request_event_repository=PermissionRequestEventRepository(session),
                audit_repository=AuditRecordRepository(session),
                connector_task_repository=ConnectorTaskRepository(session),
                agent_identity_repository=AgentIdentityRepository(session),
                connector=MockFeishuSessionConnector(self.harness.mock_base_url),
            )
            result = service.disable_agent_and_request_revoke(
                AgentDisableInput(
                    agent_id="agent_perm_assistant_v1",
                    reason="agent disabled in e2e",
                    api_request_id="req_e2e_disable_001",
                    operator_user_id="security_admin_001",
                    operator_type="SecurityAdmin",
                )
            )
            session.commit()
        self.assertEqual(result.revoked_session_count, 1)

        self.harness.run_revoke_worker()

        with self.harness.session() as session:
            request_record = session.get(PermissionRequestRecord, request_id)
            grant_record = session.get(AccessGrantRecord, grant_id)
            session_context = session.scalar(
                select(SessionContextRecord).where(SessionContextRecord.grant_id == grant_id)
            )
            self.assertEqual(request_record.request_status, "Revoked")
            self.assertEqual(grant_record.grant_status, "Revoked")
            self.assertEqual(session_context.session_status, "Revoked")

    def _submit_request(self, message: str) -> str:
        status_code, payload = self.harness.api_request(
            method="POST",
            path="/permission-requests",
            payload={
                "message": message,
                "agent_id": "agent_perm_assistant_v1",
                "delegation_id": "dlg_123",
                "conversation_id": "conv_e2e_001",
            },
            headers=self._user_headers("req_e2e_submit_001"),
        )
        self.assertEqual(status_code, 200)
        return payload["data"]["permission_request_id"]

    def _evaluate_request(self, request_id: str) -> dict[str, object]:
        status_code, payload = self.harness.api_request(
            method="POST",
            path=f"/permission-requests/{request_id}/evaluate",
            payload={"force_re_evaluate": False},
            headers=self._system_headers("req_e2e_eval_001"),
        )
        self.assertEqual(status_code, 200)
        return payload

    def _send_mock_approval(self, *, request_id: str, scenario: str) -> None:
        approval_record = self.harness.latest_approval_for_request(request_id)
        status_code, payload = self.harness.mock_request(
            method="POST",
            path="/approval/callbacks/send",
            payload={
                "callback_url": f"{self.harness.api_base_url}/approvals/callback",
                "request_id": request_id,
                "external_approval_id": approval_record.external_approval_id,
                "scenario": scenario,
                "approval_node": approval_record.approval_node,
                "approver_id": "user_mgr_001",
                "api_request_id": f"mock_e2e_callback_{request_id}",
            },
        )
        self.assertEqual(status_code, 200)
        self.assertEqual(payload["data"]["deliveries"][0]["status_code"], 200)

    def _submit_and_activate_payroll_request(self) -> tuple[str, str]:
        request_id = self._submit_request("我需要查看薪资报表")
        self._evaluate_request(request_id)
        self._send_mock_approval(request_id=request_id, scenario="approved")
        return request_id, default_grant_id_for_request(request_id)

    @staticmethod
    def _user_headers(request_id: str) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "X-Request-Id": request_id,
            "X-User-Id": "user_001",
            "X-Operator-Type": "User",
        }

    @staticmethod
    def _system_headers(request_id: str) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "X-Request-Id": request_id,
            "X-User-Id": "system",
            "X-Operator-Type": "System",
        }
