from __future__ import annotations

import unittest

from packages.domain import RiskLevel
from packages.policy import (
    LLMPolicyHints,
    PolicyEngine,
    PolicyEvaluationInput,
    get_policy_version,
    load_policy_bundle,
)


class PolicyEngineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.bundle = load_policy_bundle()
        self.engine = PolicyEngine(self.bundle)

    def test_policy_loader_returns_explicit_policy_version_and_digest(self) -> None:
        self.assertEqual(get_policy_version(), "perm-map.v1")
        self.assertEqual(self.bundle.policy_version, "perm-map.v1")
        self.assertEqual(len(self.bundle.policy_digest), 12)

    def test_read_only_request_prefers_read_permission_even_if_llm_hints_write(self) -> None:
        result = self.engine.evaluate(
            PolicyEvaluationInput(
                request_text="我需要查看销售部 Q3 报表，但不修改。",
                requester_department="sales",
                llm_hints=LLMPolicyHints(
                    action="write",
                    authorization_decision="grant_write",
                ),
            )
        )

        self.assertEqual(result.action, "read")
        self.assertEqual(result.suggested_permission, "report:sales.q3:read")
        self.assertEqual(result.mapping_rule, "sales_q3_report")
        self.assertEqual(result.risk_level, RiskLevel.LOW)
        self.assertFalse(result.approval_required)
        self.assertEqual(result.recommended_path, "direct_process")
        self.assertTrue(result.llm_final_decision_ignored)

    def test_cross_department_access_increases_risk_and_requires_manager_approval(self) -> None:
        result = self.engine.evaluate(
            PolicyEvaluationInput(
                request_text="我需要查看销售部 Q3 报表。",
                requester_department="finance",
            )
        )

        self.assertTrue(result.cross_department)
        self.assertEqual(result.risk_level, RiskLevel.MEDIUM)
        self.assertIn("cross_department_access", result.triggered_risk_rules)
        self.assertTrue(result.approval_required)
        self.assertTrue(result.requires_manager_approval)
        self.assertFalse(result.requires_escalated_approval)
        self.assertEqual(result.approval_route, ("manager",))

    def test_high_sensitive_resource_increases_risk_and_requires_escalation(self) -> None:
        result = self.engine.evaluate(
            PolicyEvaluationInput(
                request_text="我需要查看薪资报表。",
                requester_department="finance",
            )
        )

        self.assertEqual(result.resource_key, "finance.payroll")
        self.assertEqual(result.suggested_permission, "report:finance.payroll:read")
        self.assertEqual(result.risk_level, RiskLevel.HIGH)
        self.assertIn("high_sensitive_resource", result.triggered_risk_rules)
        self.assertTrue(result.requires_manager_approval)
        self.assertTrue(result.requires_escalated_approval)
        self.assertEqual(result.approval_route, ("manager", "security_admin"))

    def test_unknown_request_defaults_to_safer_manual_review_path(self) -> None:
        result = self.engine.evaluate(
            PolicyEvaluationInput(
                request_text="帮我把那个权限赶紧处理一下。",
                requester_department="sales",
            )
        )

        self.assertIsNone(result.resource_key)
        self.assertIsNone(result.action)
        self.assertIsNone(result.suggested_permission)
        self.assertTrue(result.fallback_to_safe_path)
        self.assertEqual(result.risk_level, RiskLevel.HIGH)
        self.assertEqual(result.recommended_path, "manual_review")
        self.assertTrue(result.requires_manager_approval)
        self.assertTrue(result.requires_escalated_approval)


if __name__ == "__main__":
    unittest.main()
