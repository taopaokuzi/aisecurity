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
from packages.infrastructure.db.models import (
    AccessGrantRecord,
    AgentIdentityRecord,
    ApprovalRecordRecord,
    AuditRecordRecord,
    ConnectorTaskRecord,
    PermissionRequestRecord,
    SessionContextRecord,
)
from tests.support.feishu_flow import FeishuFlowHarness
from tests.support.mock_feishu import MockFeishuSessionConnector


class MockFeishuFlowIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.harness = FeishuFlowHarness()
        cls.harness.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.harness.stop()

    def setUp(self) -> None:
        self.harness.reset_state()

    def test_approval_approved_then_provisioned_normally(self) -> None:
        request_id = self._create_and_evaluate_payroll_request()

        status_code, payload = self._send_mock_approval(request_id=request_id, scenario="approved")

        self.assertEqual(status_code, 200)
        self.assertEqual(payload["data"]["deliveries"][0]["status_code"], 200)

        grant_id = default_grant_id_for_request(request_id)
        with self.harness.session() as session:
            request_record = session.get(PermissionRequestRecord, request_id)
            grant_record = session.get(AccessGrantRecord, grant_id)
            session_context = session.scalar(
                select(SessionContextRecord).where(SessionContextRecord.grant_id == grant_id)
            )
            self.assertIsNotNone(request_record)
            self.assertIsNotNone(grant_record)
            self.assertIsNotNone(session_context)
            assert request_record is not None
            assert grant_record is not None
            assert session_context is not None
            self.assertEqual(request_record.approval_status, "Approved")
            self.assertEqual(request_record.request_status, "Active")
            self.assertEqual(grant_record.grant_status, "Active")
            self.assertEqual(grant_record.connector_status, "Applied")
            self.assertEqual(session_context.session_status, "Active")

    def test_approval_rejected_marks_request_failed(self) -> None:
        request_id = self._create_and_evaluate_payroll_request()

        status_code, payload = self._send_mock_approval(request_id=request_id, scenario="rejected")

        self.assertEqual(status_code, 200)
        self.assertEqual(payload["data"]["deliveries"][0]["status_code"], 200)

        with self.harness.session() as session:
            request_record = session.get(PermissionRequestRecord, request_id)
            grant_record = session.get(AccessGrantRecord, default_grant_id_for_request(request_id))
            self.assertIsNotNone(request_record)
            assert request_record is not None
            self.assertEqual(request_record.approval_status, "Rejected")
            self.assertEqual(request_record.request_status, "Failed")
            self.assertEqual(request_record.failed_reason, "Approval rejected")
            self.assertIsNone(grant_record)

    def test_duplicate_approval_callback_is_idempotent(self) -> None:
        request_id = self._create_and_evaluate_payroll_request()

        status_code, payload = self._send_mock_approval(request_id=request_id, scenario="duplicate")

        self.assertEqual(status_code, 200)
        self.assertEqual(len(payload["data"]["deliveries"]), 2)
        self.assertEqual(payload["data"]["deliveries"][1]["status_code"], 200)
        self.assertEqual(
            payload["data"]["deliveries"][1]["payload"]["data"]["duplicated"],
            True,
        )

        grant_id = default_grant_id_for_request(request_id)
        with self.harness.session() as session:
            tasks = session.scalars(
                select(ConnectorTaskRecord).where(ConnectorTaskRecord.grant_id == grant_id)
            ).all()
            self.assertEqual(len(tasks), 1)

    def test_provision_failure_can_be_retried_after_mock_connector_recovers(self) -> None:
        os.environ["MOCK_FEISHU_PROVISION_SCENARIO"] = "failed"
        request_id = self._create_and_evaluate_payroll_request()
        self._send_mock_approval(request_id=request_id, scenario="approved")

        with self.harness.session() as session:
            request_record = session.get(PermissionRequestRecord, request_id)
            grant_record = session.get(AccessGrantRecord, default_grant_id_for_request(request_id))
            self.assertIsNotNone(request_record)
            self.assertIsNotNone(grant_record)
            assert request_record is not None
            assert grant_record is not None
            self.assertEqual(request_record.request_status, "Failed")
            self.assertEqual(grant_record.grant_status, "ProvisionFailed")

        os.environ["MOCK_FEISHU_PROVISION_SCENARIO"] = "applied"
        failed_task_id = self._latest_connector_task_id(default_grant_id_for_request(request_id))
        status_code, payload = self.harness.api_request(
            method="POST",
            path=f"/admin/connector-tasks/{failed_task_id}/retry",
            payload={"reason": "mock-feishu recovered"},
            headers=self._headers("req_retry_001", user_id="it_admin_001", operator_type="ITAdmin"),
        )

        self.assertEqual(status_code, 200)
        self.assertEqual(payload["data"]["task_status"], "Succeeded")
        self.assertEqual(payload["data"]["request_status"], "Active")
        self.assertEqual(payload["data"]["grant_status"], "Active")

    def test_approved_request_can_remain_provisioning_when_mock_accepts_but_delays_effect(self) -> None:
        os.environ["MOCK_FEISHU_PROVISION_SCENARIO"] = "accepted_delayed"
        request_id = self._create_and_evaluate_payroll_request()

        status_code, payload = self._send_mock_approval(request_id=request_id, scenario="approved")

        self.assertEqual(status_code, 200)
        self.assertEqual(payload["data"]["deliveries"][0]["status_code"], 200)

        with self.harness.session() as session:
            request_record = session.get(PermissionRequestRecord, request_id)
            grant_record = session.get(AccessGrantRecord, default_grant_id_for_request(request_id))
            session_context = session.scalar(
                select(SessionContextRecord).where(
                    SessionContextRecord.grant_id == default_grant_id_for_request(request_id)
                )
            )
            self.assertIsNotNone(request_record)
            self.assertIsNotNone(grant_record)
            assert request_record is not None
            assert grant_record is not None
            self.assertEqual(request_record.request_status, "Provisioning")
            self.assertEqual(grant_record.grant_status, "Provisioning")
            self.assertEqual(grant_record.connector_status, "Accepted")
            self.assertIsNone(session_context)

    def test_expired_grant_triggers_auto_reclaim(self) -> None:
        request_id, grant_id = self._create_and_activate_payroll_request()
        with self.harness.session() as session:
            grant_record = session.get(AccessGrantRecord, grant_id)
            assert grant_record is not None
            grant_record.expire_at = datetime.now(timezone.utc) - timedelta(minutes=5)
            session.commit()

        lifecycle_result = self.harness.run_lifecycle_worker()
        revoke_result = self.harness.run_revoke_worker()

        self.assertEqual(lifecycle_result["expired_count"], 1)
        self.assertEqual(revoke_result["revoked_count"], 1)

        with self.harness.session() as session:
            request_record = session.get(PermissionRequestRecord, request_id)
            grant_record = session.get(AccessGrantRecord, grant_id)
            session_context = session.scalar(
                select(SessionContextRecord).where(SessionContextRecord.grant_id == grant_id)
            )
            self.assertEqual(request_record.request_status, "Expired")
            self.assertEqual(grant_record.grant_status, "Expired")
            self.assertEqual(session_context.session_status, "Revoked")

    def test_agent_disable_requests_revoke_for_active_sessions(self) -> None:
        request_id, grant_id = self._create_and_activate_payroll_request()
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
                    reason="agent disabled by integration test",
                    api_request_id="req_agent_disable_001",
                    operator_user_id="security_admin_001",
                    operator_type="SecurityAdmin",
                )
            )
            session.commit()

        self.assertEqual(result.revoked_session_count, 1)
        self.assertEqual(result.revoke_job_created, True)

        with self.harness.session() as session:
            agent_record = session.get(AgentIdentityRecord, "agent_perm_assistant_v1")
            request_record = session.get(PermissionRequestRecord, request_id)
            grant_record = session.get(AccessGrantRecord, grant_id)
            revoke_task = session.scalar(
                select(ConnectorTaskRecord)
                .where(ConnectorTaskRecord.grant_id == grant_id)
                .where(ConnectorTaskRecord.task_type == "session_revoke")
            )
            self.assertEqual(agent_record.agent_status, "Disabled")
            self.assertEqual(request_record.grant_status, "Revoking")
            self.assertEqual(grant_record.grant_status, "Revoking")
            self.assertIsNotNone(revoke_task)

    def test_revoke_failure_can_be_compensated_with_retry(self) -> None:
        request_id, grant_id = self._create_and_activate_payroll_request()
        status_code, _ = self.harness.api_request(
            method="POST",
            path="/sessions/revoke",
            payload={
                "global_session_id": self._global_session_id(grant_id),
                "reason": "manual revoke",
                "cascade_connector_sessions": True,
            },
            headers=self._headers("req_revoke_001", user_id="it_admin_001", operator_type="ITAdmin"),
        )
        self.assertEqual(status_code, 200)

        os.environ["MOCK_FEISHU_SESSION_REVOKE_SCENARIO"] = "failed"
        revoke_result = self.harness.run_revoke_worker()
        self.assertEqual(revoke_result["sync_failed_count"], 1)

        status_code, payload = self.harness.api_request(
            method="GET",
            path=f"/admin/failed-tasks?task_type=session_revoke&request_id={request_id}",
            headers=self._headers("req_failed_tasks_001", user_id="it_admin_001", operator_type="ITAdmin"),
        )
        self.assertEqual(status_code, 200)
        self.assertEqual(payload["data"]["total"], 1)
        failed_task_id = payload["data"]["items"][0]["task_id"]

        os.environ["MOCK_FEISHU_SESSION_REVOKE_SCENARIO"] = "success"
        status_code, payload = self.harness.api_request(
            method="POST",
            path=f"/admin/connector-tasks/{failed_task_id}/retry",
            payload={"reason": "retry revoke after mock recovery"},
            headers=self._headers("req_retry_revoke_001", user_id="it_admin_001", operator_type="ITAdmin"),
        )
        self.assertEqual(status_code, 200)
        self.assertEqual(payload["data"]["task_status"], "Succeeded")
        self.assertEqual(payload["data"]["session_status"], "Revoked")

        with self.harness.session() as session:
            request_record = session.get(PermissionRequestRecord, request_id)
            grant_record = session.get(AccessGrantRecord, grant_id)
            session_context = session.scalar(
                select(SessionContextRecord).where(SessionContextRecord.grant_id == grant_id)
            )
            self.assertEqual(request_record.request_status, "Revoked")
            self.assertEqual(grant_record.grant_status, "Revoked")
            self.assertEqual(session_context.session_status, "Revoked")

    def _create_and_activate_sales_report_request(self) -> tuple[str, str]:
        request_id = self._create_request("我需要查看销售部 Q3 报表，但不需要修改权限")
        status_code, _ = self.harness.api_request(
            method="POST",
            path=f"/permission-requests/{request_id}/evaluate",
            payload={"force_re_evaluate": False},
            headers=self._headers("req_eval_sales_001", user_id="system", operator_type="System"),
        )
        self.assertEqual(status_code, 200)
        grant_id = default_grant_id_for_request(request_id)
        status_code, payload = self.harness.api_request(
            method="POST",
            path=f"/grants/{grant_id}/provision",
            payload={
                "request_id": request_id,
                "policy_version": "perm-map.v1",
                "delegation_id": "dlg_123",
                "force_retry": False,
            },
            headers=self._headers("req_provision_sales_001", user_id="system", operator_type="System"),
        )
        self.assertEqual(status_code, 200)
        self.assertEqual(payload["data"]["grant_status"], "Active")
        return request_id, grant_id

    def _create_and_activate_payroll_request(self) -> tuple[str, str]:
        request_id = self._create_and_evaluate_payroll_request()
        status_code, payload = self._send_mock_approval(request_id=request_id, scenario="approved")
        self.assertEqual(status_code, 200)
        self.assertEqual(payload["data"]["deliveries"][0]["status_code"], 200)
        return request_id, default_grant_id_for_request(request_id)

    def _create_and_evaluate_payroll_request(self) -> str:
        request_id = self._create_request("我需要查看薪资报表")
        status_code, payload = self.harness.api_request(
            method="POST",
            path=f"/permission-requests/{request_id}/evaluate",
            payload={"force_re_evaluate": False},
            headers=self._headers("req_eval_payroll_001", user_id="system", operator_type="System"),
        )
        self.assertEqual(status_code, 200)
        self.assertEqual(payload["data"]["approval_status"], "Pending")
        return request_id

    def _create_request(self, message: str) -> str:
        status_code, payload = self.harness.api_request(
            method="POST",
            path="/permission-requests",
            payload={
                "message": message,
                "agent_id": "agent_perm_assistant_v1",
                "delegation_id": "dlg_123",
                "conversation_id": "conv_test_001",
            },
            headers=self._headers("req_submit_001", user_id="user_001", operator_type="User"),
        )
        self.assertEqual(status_code, 200)
        return payload["data"]["permission_request_id"]

    def _send_mock_approval(self, *, request_id: str, scenario: str) -> tuple[int, dict[str, object]]:
        approval_record = self.harness.latest_approval_for_request(request_id)
        return self.harness.mock_request(
            method="POST",
            path="/approval/callbacks/send",
            payload={
                "callback_url": f"{self.harness.api_base_url}/approvals/callback",
                "request_id": request_id,
                "external_approval_id": approval_record.external_approval_id,
                "scenario": scenario,
                "approval_node": approval_record.approval_node,
                "approver_id": "user_mgr_001",
                "api_request_id": f"mock_callback_{request_id}",
            },
        )

    def _latest_connector_task_id(self, grant_id: str) -> str:
        with self.harness.session() as session:
            task = session.scalar(
                select(ConnectorTaskRecord)
                .where(ConnectorTaskRecord.grant_id == grant_id)
                .order_by(ConnectorTaskRecord.created_at.desc())
            )
            if task is None:
                raise AssertionError(f"Missing connector task for grant {grant_id}")
            return task.task_id

    def _global_session_id(self, grant_id: str) -> str:
        with self.harness.session() as session:
            record = session.scalar(
                select(SessionContextRecord).where(SessionContextRecord.grant_id == grant_id)
            )
            if record is None:
                raise AssertionError(f"Missing session context for grant {grant_id}")
            return record.global_session_id

    @staticmethod
    def _headers(request_id: str, *, user_id: str, operator_type: str) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "X-Request-Id": request_id,
            "X-User-Id": user_id,
            "X-Operator-Type": operator_type,
        }
