from __future__ import annotations

from packages.domain import RiskLevel

from .loader import load_policy_bundle
from .models import (
    ApprovalRule,
    LLMPolicyHints,
    PermissionMappingRule,
    PolicyBundle,
    PolicyEvaluationInput,
    PolicyEvaluationResult,
    RiskRule,
)

_RISK_ORDER = {
    RiskLevel.LOW: 0,
    RiskLevel.MEDIUM: 1,
    RiskLevel.HIGH: 2,
    RiskLevel.CRITICAL: 3,
}


class PolicyEngine:
    def __init__(self, policy_bundle: PolicyBundle) -> None:
        self.policy_bundle = policy_bundle

    def evaluate(self, evaluation_input: PolicyEvaluationInput) -> PolicyEvaluationResult:
        request_text = self._normalize_text(evaluation_input.request_text)
        llm_hints = evaluation_input.llm_hints or LLMPolicyHints()
        action = self._resolve_action(evaluation_input, request_text, llm_hints)
        mapping = self._resolve_mapping(evaluation_input, request_text, llm_hints)

        resource_key = mapping.resource_key if mapping is not None else self._first_text(
            evaluation_input.resource_key,
            llm_hints.resource_key,
        )
        resource_type = mapping.resource_type if mapping is not None else self._normalize_optional(
            self._first_text(evaluation_input.resource_type, llm_hints.resource_type)
        )
        target_department = mapping.department if mapping is not None else self._normalize_optional(
            self._first_text(evaluation_input.target_department, llm_hints.target_department)
        )
        sensitivity = mapping.sensitivity if mapping is not None else self._normalize_optional(
            self._first_text(
                evaluation_input.resource_sensitivity,
                llm_hints.resource_sensitivity,
            )
        )
        requester_department = self._normalize_optional(evaluation_input.requester_department)
        cross_department = bool(
            requester_department
            and target_department
            and requester_department != target_department
        )

        suggested_permission = None
        fallback_to_safe_path = False
        reasons: list[str] = []

        if mapping is not None and action is not None:
            suggested_permission = mapping.permission_map.get(action)
        if suggested_permission is None:
            fallback_to_safe_path = True
            reasons.append("资源或动作无法稳定映射，已切换到更安全的人工复核路径。")

        risk_score, risk_level, triggered_risk_rules, risk_reasons = self._score_risk(
            action=action,
            sensitivity=sensitivity,
            cross_department=cross_department,
            fallback_to_safe_path=fallback_to_safe_path,
        )
        reasons.extend(risk_reasons)
        if not reasons:
            reasons.append("普通同部门只读请求，维持低风险。")

        approval_rule = self._select_approval_rule(
            risk_level=risk_level,
            action=action,
            sensitivity=sensitivity,
            cross_department=cross_department,
            fallback_to_safe_path=fallback_to_safe_path,
        )
        reasons.append(approval_rule.reason)

        return PolicyEvaluationResult(
            policy_version=self.policy_bundle.policy_version,
            policy_digest=self.policy_bundle.policy_digest,
            decision_source="policy_rules",
            resource_key=resource_key,
            resource_type=resource_type,
            action=action,
            suggested_permission=suggested_permission,
            risk_score=risk_score,
            risk_level=risk_level,
            approval_required=approval_rule.approval_required,
            approval_route=approval_rule.route,
            requires_manager_approval=approval_rule.requires_manager_approval,
            requires_escalated_approval=approval_rule.requires_escalated_approval,
            recommended_path=approval_rule.recommended_path,
            cross_department=cross_department,
            fallback_to_safe_path=fallback_to_safe_path,
            llm_final_decision_ignored=bool(llm_hints.authorization_decision),
            mapping_rule=mapping.name if mapping is not None else None,
            approval_rule=approval_rule.name,
            triggered_risk_rules=triggered_risk_rules,
            reasons=tuple(reasons),
        )

    def _resolve_action(
        self,
        evaluation_input: PolicyEvaluationInput,
        request_text: str,
        llm_hints: LLMPolicyHints,
    ) -> str | None:
        if self._matches_any(request_text, self.policy_bundle.readonly_priority_terms):
            return "read"
        if self._matches_any(request_text, self.policy_bundle.action_terms["request_edit"]):
            return "request_edit"
        if self._matches_any(request_text, self.policy_bundle.action_terms["write"]):
            return "write"
        if self._matches_any(request_text, self.policy_bundle.action_terms["read"]):
            return "read"

        return self._normalize_action(
            self._first_text(evaluation_input.requested_action, llm_hints.action)
        )

    def _resolve_mapping(
        self,
        evaluation_input: PolicyEvaluationInput,
        request_text: str,
        llm_hints: LLMPolicyHints,
    ) -> PermissionMappingRule | None:
        hinted_resource_type = self._normalize_optional(
            self._first_text(evaluation_input.resource_type, llm_hints.resource_type)
        )
        for resource_key in (
            self._normalize_optional(evaluation_input.resource_key),
            self._normalize_optional(llm_hints.resource_key),
        ):
            if resource_key is None:
                continue
            for mapping in self.policy_bundle.permission_mappings:
                if mapping.resource_key == resource_key:
                    if hinted_resource_type and mapping.resource_type != hinted_resource_type:
                        continue
                    return mapping

        best_match: tuple[int, int, PermissionMappingRule] | None = None
        for mapping in self.policy_bundle.permission_mappings:
            if hinted_resource_type and mapping.resource_type != hinted_resource_type:
                continue
            matched_terms = tuple(term for term in mapping.resource_terms if term in request_text)
            if not matched_terms:
                continue
            score = (len(matched_terms), sum(len(term) for term in matched_terms))
            if best_match is None or score > best_match[:2]:
                best_match = (score[0], score[1], mapping)
        return best_match[2] if best_match is not None else None

    def _score_risk(
        self,
        *,
        action: str | None,
        sensitivity: str | None,
        cross_department: bool,
        fallback_to_safe_path: bool,
    ) -> tuple[int, RiskLevel, tuple[str, ...], tuple[str, ...]]:
        base_scores = self.policy_bundle.base_risk_scores
        risk_score = base_scores.get(action or "unknown", base_scores["unknown"])
        minimum_level: RiskLevel | None = None
        triggered_risk_rules: list[str] = []
        reasons: list[str] = []

        for risk_rule in self.policy_bundle.risk_rules:
            if not self._risk_rule_matches(
                risk_rule,
                sensitivity=sensitivity,
                cross_department=cross_department,
                fallback_to_safe_path=fallback_to_safe_path,
            ):
                continue
            risk_score += risk_rule.score_delta
            triggered_risk_rules.append(risk_rule.name)
            reasons.append(risk_rule.reason)
            if risk_rule.minimum_level is not None:
                minimum_level = self._max_risk_level(minimum_level, risk_rule.minimum_level)

        inferred_level = self._risk_level_from_score(risk_score)
        final_level = self._max_risk_level(inferred_level, minimum_level)
        return risk_score, final_level, tuple(triggered_risk_rules), tuple(reasons)

    def _select_approval_rule(
        self,
        *,
        risk_level: RiskLevel,
        action: str | None,
        sensitivity: str | None,
        cross_department: bool,
        fallback_to_safe_path: bool,
    ) -> ApprovalRule:
        for approval_rule in self.policy_bundle.approval_rules:
            if not self._approval_rule_matches(
                approval_rule,
                risk_level=risk_level,
                action=action,
                sensitivity=sensitivity,
                cross_department=cross_department,
                fallback_to_safe_path=fallback_to_safe_path,
            ):
                continue
            return approval_rule

        return ApprovalRule(
            name="default_manual_review",
            approval_required=True,
            route=("manager", "security_admin"),
            requires_manager_approval=True,
            requires_escalated_approval=True,
            recommended_path="manual_review",
            reason="未匹配到审批规则，默认采用更安全的升级审批路径。",
        )

    def _risk_rule_matches(
        self,
        risk_rule: RiskRule,
        *,
        sensitivity: str | None,
        cross_department: bool,
        fallback_to_safe_path: bool,
    ) -> bool:
        if risk_rule.cross_department is not None and risk_rule.cross_department != cross_department:
            return False
        if risk_rule.fallback_only is not None and risk_rule.fallback_only != fallback_to_safe_path:
            return False
        if risk_rule.sensitivities:
            if sensitivity is None or sensitivity not in risk_rule.sensitivities:
                return False
        return True

    def _approval_rule_matches(
        self,
        approval_rule: ApprovalRule,
        *,
        risk_level: RiskLevel,
        action: str | None,
        sensitivity: str | None,
        cross_department: bool,
        fallback_to_safe_path: bool,
    ) -> bool:
        if approval_rule.fallback_only is not None and approval_rule.fallback_only != fallback_to_safe_path:
            return False
        if approval_rule.risk_levels and risk_level not in approval_rule.risk_levels:
            return False
        if approval_rule.actions:
            if action is None or action not in approval_rule.actions:
                return False
        if approval_rule.cross_department is not None and approval_rule.cross_department != cross_department:
            return False
        if approval_rule.sensitivities:
            if sensitivity is None or sensitivity not in approval_rule.sensitivities:
                return False
        return True

    def _risk_level_from_score(self, risk_score: int) -> RiskLevel:
        thresholds = self.policy_bundle.risk_level_thresholds
        if risk_score >= thresholds["critical"]:
            return RiskLevel.CRITICAL
        if risk_score >= thresholds["high"]:
            return RiskLevel.HIGH
        if risk_score >= thresholds["medium"]:
            return RiskLevel.MEDIUM
        return RiskLevel.LOW

    def _max_risk_level(
        self,
        left: RiskLevel | None,
        right: RiskLevel | None,
    ) -> RiskLevel:
        if left is None:
            if right is None:
                return RiskLevel.LOW
            return right
        if right is None:
            return left
        if _RISK_ORDER[left] >= _RISK_ORDER[right]:
            return left
        return right

    def _normalize_action(self, value: str | None) -> str | None:
        normalized = self._normalize_optional(value)
        if normalized in self.policy_bundle.action_terms:
            return normalized
        return None

    def _matches_any(self, request_text: str, terms: tuple[str, ...]) -> bool:
        return any(term in request_text for term in terms)

    def _first_text(self, *values: str | None) -> str | None:
        for value in values:
            if value is not None and value.strip():
                return value.strip()
        return None

    def _normalize_optional(self, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        return normalized or None

    def _normalize_text(self, value: str) -> str:
        return value.strip().lower()


def create_policy_engine(policy_dir: str | None = None) -> PolicyEngine:
    return PolicyEngine(load_policy_bundle(policy_dir))
