from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from packages.domain import RiskLevel


class PolicyLoaderError(RuntimeError):
    """Raised when the policy bundle cannot be loaded from configuration."""


@dataclass(slots=True, frozen=True)
class PolicyManifest:
    policy_id: str
    policy_version: str
    permission_mappings_file: str
    risk_rules_file: str
    approval_rules_file: str


@dataclass(slots=True, frozen=True)
class PermissionMappingRule:
    name: str
    resource_key: str
    resource_type: str
    department: str | None
    sensitivity: str
    resource_terms: tuple[str, ...]
    permission_map: dict[str, str]


@dataclass(slots=True, frozen=True)
class RiskRule:
    name: str
    score_delta: int
    minimum_level: RiskLevel | None
    reason: str
    cross_department: bool | None = None
    sensitivities: tuple[str, ...] = ()
    fallback_only: bool | None = None


@dataclass(slots=True, frozen=True)
class ApprovalRule:
    name: str
    approval_required: bool
    route: tuple[str, ...]
    requires_manager_approval: bool
    requires_escalated_approval: bool
    recommended_path: str
    reason: str
    risk_levels: tuple[RiskLevel, ...] = ()
    actions: tuple[str, ...] = ()
    sensitivities: tuple[str, ...] = ()
    cross_department: bool | None = None
    fallback_only: bool | None = None


@dataclass(slots=True, frozen=True)
class PolicyBundle:
    manifest: PolicyManifest
    policy_dir: Path
    source_files: tuple[Path, ...]
    policy_digest: str
    action_terms: dict[str, tuple[str, ...]]
    readonly_priority_terms: tuple[str, ...]
    permission_mappings: tuple[PermissionMappingRule, ...]
    base_risk_scores: dict[str, int]
    risk_level_thresholds: dict[str, int]
    risk_rules: tuple[RiskRule, ...]
    approval_rules: tuple[ApprovalRule, ...]

    @property
    def policy_version(self) -> str:
        return self.manifest.policy_version


@dataclass(slots=True, frozen=True)
class LLMPolicyHints:
    resource_key: str | None = None
    resource_type: str | None = None
    action: str | None = None
    target_department: str | None = None
    resource_sensitivity: str | None = None
    suggested_permission: str | None = None
    risk_level: str | None = None
    authorization_decision: str | None = None


@dataclass(slots=True, frozen=True)
class PolicyEvaluationInput:
    request_text: str
    requester_department: str | None = None
    resource_key: str | None = None
    resource_type: str | None = None
    requested_action: str | None = None
    target_department: str | None = None
    resource_sensitivity: str | None = None
    llm_hints: LLMPolicyHints | None = None


@dataclass(slots=True, frozen=True)
class PolicyEvaluationResult:
    policy_version: str
    policy_digest: str
    decision_source: str
    resource_key: str | None
    resource_type: str | None
    action: str | None
    suggested_permission: str | None
    risk_score: int
    risk_level: RiskLevel
    approval_required: bool
    approval_route: tuple[str, ...]
    requires_manager_approval: bool
    requires_escalated_approval: bool
    recommended_path: str
    cross_department: bool
    fallback_to_safe_path: bool
    llm_final_decision_ignored: bool
    mapping_rule: str | None
    approval_rule: str
    triggered_risk_rules: tuple[str, ...]
    reasons: tuple[str, ...]
