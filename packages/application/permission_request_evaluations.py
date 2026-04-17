from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Mapping
from uuid import uuid4

from packages.domain import (
    ActorType,
    ApprovalStatus,
    DomainError,
    ErrorCode,
    GrantStatus,
    OperatorType,
    RequestStatus,
    RiskLevel,
    TaskStatus,
)
from packages.infrastructure.db.models import (
    AuditRecordRecord,
    PermissionRequestEventRecord,
    PermissionRequestRecord,
    UserRecord,
)
from packages.infrastructure.permission_request_parser import (
    PermissionRequestParseResult,
    PermissionRequestParser,
)
from packages.infrastructure.repositories import (
    AuditRecordRepository,
    PermissionRequestEventRepository,
    PermissionRequestRepository,
    UserRepository,
)
from packages.policy import LLMPolicyHints, PolicyEngine, PolicyEvaluationInput

_DEFAULT_REQUESTED_DURATION = "P7D"
_EVALUATE_OPERATORS = frozenset(
    {
        OperatorType.SYSTEM,
        OperatorType.IT_ADMIN,
        OperatorType.SECURITY_ADMIN,
    }
)
_PRIVILEGED_QUERY_OPERATORS = frozenset(
    {
        OperatorType.IT_ADMIN,
        OperatorType.SECURITY_ADMIN,
        OperatorType.SYSTEM,
    }
)
_RETRYABLE_EVALUATION_STATUSES = frozenset({RequestStatus.FAILED})


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _generate_prefixed_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:24]}"


@dataclass(slots=True, frozen=True)
class PermissionRequestEvaluationInput:
    permission_request_id: str
    request_id: str
    operator_user_id: str
    operator_type: OperatorType | str = OperatorType.SYSTEM
    trace_id: str | None = None
    force_re_evaluate: bool = False


@dataclass(slots=True, frozen=True)
class PermissionRequestEvaluationResult:
    request_id: str
    resource_key: str | None
    resource_type: str | None
    action: str | None
    requested_duration: str | None
    suggested_permission: str | None
    risk_level: RiskLevel | None
    approval_route: tuple[str, ...]
    policy_version: str | None
    approval_status: ApprovalStatus
    request_status: RequestStatus
    structured_request: Mapping[str, object] | None
    evaluated_at: datetime | None
    failed_reason: str | None = None


class PermissionRequestEvaluationService:
    def __init__(
        self,
        *,
        user_repository: UserRepository,
        permission_request_repository: PermissionRequestRepository,
        permission_request_event_repository: PermissionRequestEventRepository,
        audit_repository: AuditRecordRepository,
        parser: PermissionRequestParser,
        policy_engine: PolicyEngine,
        now_provider: Callable[[], datetime] = _utc_now,
    ) -> None:
        self.user_repository = user_repository
        self.permission_request_repository = permission_request_repository
        self.permission_request_event_repository = permission_request_event_repository
        self.audit_repository = audit_repository
        self.parser = parser
        self.policy_engine = policy_engine
        self.now_provider = now_provider

    def evaluate_permission_request(
        self,
        command: PermissionRequestEvaluationInput,
    ) -> PermissionRequestEvaluationResult:
        operator_type = self._coerce_operator_type(command.operator_type)
        self._require_evaluate_operator(operator_type)

        record = self._get_request_record(command.permission_request_id)
        current_status = RequestStatus(record.request_status)
        if not self._can_start_evaluation(
            current_status=current_status,
            force_re_evaluate=command.force_re_evaluate,
            operator_type=operator_type,
        ):
            raise DomainError(
                ErrorCode.REQUEST_STATUS_INVALID,
                message="Current request status does not allow evaluation",
                details={
                    "request_id": command.permission_request_id,
                    "request_status": current_status.value,
                    "http_status": 409,
                },
            )

        now = self._current_time()
        completed_at = self._next_timestamp(now)
        operator_id = self._operator_id(
            operator_type=operator_type,
            operator_user_id=command.operator_user_id,
        )
        start_event_type = (
            "request.retry_accepted"
            if current_status in _RETRYABLE_EVALUATION_STATUSES and command.force_re_evaluate
            else "request.evaluation_started"
        )

        record.request_status = RequestStatus.EVALUATING.value
        record.current_task_state = TaskStatus.RUNNING.value
        record.updated_at = now
        record.failed_reason = None

        self.permission_request_event_repository.add(
            PermissionRequestEventRecord(
                event_id=_generate_prefixed_id("evt"),
                request_id=record.request_id,
                event_type=start_event_type,
                operator_type=operator_type.value,
                operator_id=operator_id,
                from_request_status=current_status.value,
                to_request_status=RequestStatus.EVALUATING.value,
                metadata_json=self._compact_metadata(
                    {
                        "api_request_id": command.request_id,
                        "trace_id": command.trace_id,
                        "force_re_evaluate": command.force_re_evaluate,
                    }
                ),
                occurred_at=now,
                created_at=now,
            )
        )

        try:
            result = self._run_evaluation(record, evaluated_at=now)
        except DomainError as exc:
            self._mark_evaluation_failed(
                record=record,
                evaluated_at=completed_at,
                operator_type=operator_type,
                operator_id=operator_id,
                api_request_id=command.request_id,
                trace_id=command.trace_id,
                failure_reason=exc.message,
            )
            raise
        except Exception as exc:
            self._mark_evaluation_failed(
                record=record,
                evaluated_at=completed_at,
                operator_type=operator_type,
                operator_id=operator_id,
                api_request_id=command.request_id,
                trace_id=command.trace_id,
                failure_reason=str(exc),
            )
            raise DomainError(
                ErrorCode.RISK_EVALUATION_FAILED,
                details={
                    "request_id": record.request_id,
                    "http_status": 500,
                },
            ) from exc

        approval_status = (
            ApprovalStatus.PENDING
            if result["approval_required"]
            else ApprovalStatus.NOT_REQUIRED
        )
        structured_request = self._build_structured_request_snapshot(
            parsed=result["parsed"],
            policy_result=result["policy_result"],
            requested_duration=result["requested_duration"],
            evaluated_at=completed_at,
        )

        record.resource_key = result["resource_key"]
        record.resource_type = result["resource_type"]
        record.action = result["action"]
        record.constraints_json = result["constraints"]
        record.requested_duration = result["requested_duration"]
        record.structured_request_json = structured_request
        record.suggested_permission = result["suggested_permission"]
        record.risk_level = result["risk_level"].value
        record.approval_status = approval_status.value
        record.request_status = RequestStatus.PENDING_APPROVAL.value
        record.current_task_state = TaskStatus.SUCCEEDED.value
        record.policy_version = result["policy_version"]
        record.updated_at = completed_at
        record.failed_reason = None

        self.permission_request_event_repository.add(
            PermissionRequestEventRecord(
                event_id=_generate_prefixed_id("evt"),
                request_id=record.request_id,
                event_type="request.evaluated",
                operator_type=operator_type.value,
                operator_id=operator_id,
                from_request_status=RequestStatus.EVALUATING.value,
                to_request_status=RequestStatus.PENDING_APPROVAL.value,
                metadata_json=self._compact_metadata(
                    {
                        "api_request_id": command.request_id,
                        "trace_id": command.trace_id,
                        "resource_key": result["resource_key"],
                        "resource_type": result["resource_type"],
                        "action": result["action"],
                        "requested_duration": result["requested_duration"],
                        "suggested_permission": result["suggested_permission"],
                        "risk_level": result["risk_level"].value,
                        "approval_route": list(result["approval_route"]),
                        "policy_version": result["policy_version"],
                        "parser_source": result["parsed"].source,
                    }
                ),
                occurred_at=completed_at,
                created_at=completed_at,
            )
        )
        self.audit_repository.add(
            AuditRecordRecord(
                audit_id=_generate_prefixed_id("aud"),
                request_id=record.request_id,
                event_type="request.evaluated",
                actor_type=self._to_actor_type(operator_type).value,
                actor_id=operator_id,
                subject_chain=self._subject_chain(record),
                result="Success",
                reason=None,
                metadata_json=self._compact_metadata(
                    {
                        "api_request_id": command.request_id,
                        "trace_id": command.trace_id,
                        "approval_status": approval_status.value,
                        "approval_route": list(result["approval_route"]),
                        "policy_version": result["policy_version"],
                    }
                ),
                created_at=completed_at,
            )
        )

        return self._build_evaluation_result(record)

    def get_permission_request_evaluation(
        self,
        permission_request_id: str,
        *,
        requester_user_id: str,
        operator_type: OperatorType | str = OperatorType.USER,
    ) -> PermissionRequestEvaluationResult:
        operator = self._coerce_operator_type(operator_type)
        record = self._get_request_record(permission_request_id)
        self._assert_view_allowed(
            record=record,
            requester_user_id=requester_user_id,
            operator_type=operator,
        )

        if record.structured_request_json is None:
            raise DomainError(
                ErrorCode.REQUEST_STATUS_INVALID,
                message="Evaluation result is not available yet",
                details={
                    "request_id": permission_request_id,
                    "request_status": record.request_status,
                    "http_status": 409,
                },
            )
        return self._build_evaluation_result(record)

    def _run_evaluation(
        self,
        record: PermissionRequestRecord,
        *,
        evaluated_at: datetime,
    ) -> dict[str, object]:
        requester = self._require_request_owner(record.user_id)
        parsed = self.parser.parse(record.raw_text)
        policy_request_text = self._build_policy_request_text(
            raw_text=record.raw_text,
            parsed=parsed,
        )
        policy_result = self.policy_engine.evaluate(
            PolicyEvaluationInput(
                request_text=policy_request_text,
                requester_department=self._normalize_department(
                    requester.department_name or requester.department_id
                ),
                resource_key=parsed.resource_key,
                resource_type=parsed.resource_type,
                requested_action=parsed.action,
                target_department=parsed.target_department,
                resource_sensitivity=parsed.resource_sensitivity,
                llm_hints=LLMPolicyHints(
                    resource_key=parsed.resource_key,
                    resource_type=parsed.resource_type,
                    action=parsed.action,
                    target_department=parsed.target_department,
                    resource_sensitivity=parsed.resource_sensitivity,
                ),
            )
        )

        return {
            "parsed": parsed,
            "policy_result": policy_result,
            "resource_key": policy_result.resource_key,
            "resource_type": policy_result.resource_type,
            "action": policy_result.action,
            "constraints": parsed.constraints,
            "requested_duration": parsed.requested_duration or _DEFAULT_REQUESTED_DURATION,
            "suggested_permission": policy_result.suggested_permission,
            "risk_level": policy_result.risk_level,
            "approval_required": policy_result.approval_required,
            "approval_route": policy_result.approval_route,
            "policy_version": policy_result.policy_version,
            "evaluated_at": evaluated_at,
        }

    def _mark_evaluation_failed(
        self,
        *,
        record: PermissionRequestRecord,
        evaluated_at: datetime,
        operator_type: OperatorType,
        operator_id: str | None,
        api_request_id: str,
        trace_id: str | None,
        failure_reason: str | None,
    ) -> None:
        normalized_reason = (failure_reason or ErrorCode.RISK_EVALUATION_FAILED.value).strip()[:256]
        record.request_status = RequestStatus.FAILED.value
        record.current_task_state = TaskStatus.FAILED.value
        record.approval_status = ApprovalStatus.NOT_REQUIRED.value
        record.failed_reason = normalized_reason
        record.updated_at = evaluated_at

        self.permission_request_event_repository.add(
            PermissionRequestEventRecord(
                event_id=_generate_prefixed_id("evt"),
                request_id=record.request_id,
                event_type="request.evaluation_failed",
                operator_type=operator_type.value,
                operator_id=operator_id,
                from_request_status=RequestStatus.EVALUATING.value,
                to_request_status=RequestStatus.FAILED.value,
                metadata_json=self._compact_metadata(
                    {
                        "api_request_id": api_request_id,
                        "trace_id": trace_id,
                        "failed_reason": normalized_reason,
                    }
                ),
                occurred_at=evaluated_at,
                created_at=evaluated_at,
            )
        )
        self.audit_repository.add(
            AuditRecordRecord(
                audit_id=_generate_prefixed_id("aud"),
                request_id=record.request_id,
                event_type="request.evaluation_failed",
                actor_type=self._to_actor_type(operator_type).value,
                actor_id=operator_id,
                subject_chain=self._subject_chain(record),
                result="Fail",
                reason=normalized_reason,
                metadata_json=self._compact_metadata(
                    {
                        "api_request_id": api_request_id,
                        "trace_id": trace_id,
                    }
                ),
                created_at=evaluated_at,
            )
        )

    def _build_structured_request_snapshot(
        self,
        *,
        parsed: PermissionRequestParseResult,
        policy_result: object,
        requested_duration: str,
        evaluated_at: datetime,
    ) -> dict[str, object]:
        policy = policy_result
        return {
            "parser": parsed.to_dict(),
            "policy_evaluation": {
                "policy_version": policy.policy_version,
                "policy_digest": policy.policy_digest,
                "decision_source": policy.decision_source,
                "resource_key": policy.resource_key,
                "resource_type": policy.resource_type,
                "action": policy.action,
                "suggested_permission": policy.suggested_permission,
                "risk_score": policy.risk_score,
                "risk_level": policy.risk_level.value,
                "approval_required": policy.approval_required,
                "approval_route": list(policy.approval_route),
                "requires_manager_approval": policy.requires_manager_approval,
                "requires_escalated_approval": policy.requires_escalated_approval,
                "recommended_path": policy.recommended_path,
                "cross_department": policy.cross_department,
                "fallback_to_safe_path": policy.fallback_to_safe_path,
                "llm_final_decision_ignored": policy.llm_final_decision_ignored,
                "mapping_rule": policy.mapping_rule,
                "approval_rule": policy.approval_rule,
                "triggered_risk_rules": list(policy.triggered_risk_rules),
                "reasons": list(policy.reasons),
            },
            "approval_route": list(policy.approval_route),
            "requested_duration": requested_duration,
            "evaluated_at": evaluated_at.isoformat().replace("+00:00", "Z"),
        }

    def _build_evaluation_result(
        self,
        record: PermissionRequestRecord,
    ) -> PermissionRequestEvaluationResult:
        structured_request = (
            dict(record.structured_request_json)
            if record.structured_request_json is not None
            else None
        )
        approval_route = self._extract_approval_route(structured_request)
        evaluated_at = self._extract_evaluated_at(structured_request, record.updated_at)
        return PermissionRequestEvaluationResult(
            request_id=record.request_id,
            resource_key=record.resource_key,
            resource_type=record.resource_type,
            action=record.action,
            requested_duration=record.requested_duration,
            suggested_permission=record.suggested_permission,
            risk_level=RiskLevel(record.risk_level) if record.risk_level is not None else None,
            approval_route=approval_route,
            policy_version=record.policy_version,
            approval_status=ApprovalStatus(record.approval_status),
            request_status=RequestStatus(record.request_status),
            structured_request=structured_request,
            evaluated_at=evaluated_at,
            failed_reason=record.failed_reason,
        )

    def _extract_approval_route(
        self,
        structured_request: Mapping[str, object] | None,
    ) -> tuple[str, ...]:
        if not isinstance(structured_request, Mapping):
            return ()
        raw_route = structured_request.get("approval_route")
        if not isinstance(raw_route, list):
            policy_payload = structured_request.get("policy_evaluation")
            if isinstance(policy_payload, Mapping):
                raw_route = policy_payload.get("approval_route")
        if not isinstance(raw_route, list):
            return ()
        return tuple(str(item) for item in raw_route if str(item).strip())

    def _extract_evaluated_at(
        self,
        structured_request: Mapping[str, object] | None,
        fallback: datetime,
    ) -> datetime:
        if isinstance(structured_request, Mapping):
            raw_value = structured_request.get("evaluated_at")
            if isinstance(raw_value, str) and raw_value.strip():
                try:
                    normalized = raw_value.replace("Z", "+00:00")
                    return datetime.fromisoformat(normalized)
                except ValueError:
                    pass
        return fallback

    def _get_request_record(self, permission_request_id: str) -> PermissionRequestRecord:
        record = self.permission_request_repository.get(permission_request_id)
        if record is None:
            raise DomainError(
                ErrorCode.REQUEST_STATUS_INVALID,
                message="Permission request was not found",
                details={"request_id": permission_request_id, "http_status": 404},
            )
        return record

    def _require_request_owner(self, user_id: str) -> UserRecord:
        user = self.user_repository.get(user_id)
        if user is None:
            raise DomainError(
                ErrorCode.RISK_EVALUATION_FAILED,
                message="Request owner was not found",
                details={"user_id": user_id, "http_status": 500},
            )
        return user

    def _require_evaluate_operator(self, operator_type: OperatorType) -> None:
        if operator_type in _EVALUATE_OPERATORS:
            return
        raise DomainError(
            ErrorCode.FORBIDDEN,
            message="Only internal operators can evaluate permission requests",
            details={"operator_type": operator_type.value, "http_status": 403},
        )

    def _assert_view_allowed(
        self,
        *,
        record: PermissionRequestRecord,
        requester_user_id: str,
        operator_type: OperatorType,
    ) -> None:
        if operator_type in _PRIVILEGED_QUERY_OPERATORS or record.user_id == requester_user_id:
            return
        raise DomainError(
            ErrorCode.FORBIDDEN,
            details={"request_id": record.request_id, "http_status": 403},
        )

    def _can_start_evaluation(
        self,
        *,
        current_status: RequestStatus,
        force_re_evaluate: bool,
        operator_type: OperatorType,
    ) -> bool:
        if current_status is RequestStatus.SUBMITTED:
            return True
        if (
            force_re_evaluate
            and operator_type in _EVALUATE_OPERATORS
            and current_status in _RETRYABLE_EVALUATION_STATUSES
        ):
            return True
        return False

    def _coerce_operator_type(self, operator_type: OperatorType | str) -> OperatorType:
        if isinstance(operator_type, OperatorType):
            return operator_type
        try:
            return OperatorType(operator_type)
        except ValueError as exc:
            raise DomainError(
                ErrorCode.FORBIDDEN,
                message="Operator type is invalid",
                details={"operator_type": operator_type, "http_status": 400},
            ) from exc

    def _operator_id(
        self,
        *,
        operator_type: OperatorType,
        operator_user_id: str,
    ) -> str | None:
        if operator_type is OperatorType.SYSTEM:
            return None
        return operator_user_id

    def _to_actor_type(self, operator_type: OperatorType) -> ActorType:
        return ActorType(operator_type.value)

    def _subject_chain(self, record: PermissionRequestRecord) -> str:
        return f"user:{record.user_id}->agent:{record.agent_id}->request:{record.request_id}"

    def _compact_metadata(self, metadata: dict[str, object]) -> dict[str, object]:
        return {key: value for key, value in metadata.items() if value is not None}

    def _normalize_department(self, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().lower()
        if not normalized:
            return None
        if normalized in {"销售部", "销售", "sales"}:
            return "sales"
        if normalized in {"财务部", "财务", "finance"}:
            return "finance"
        if normalized in {"共享", "团队", "shared"}:
            return "shared"
        if normalized in {"安全部", "安全", "security"}:
            return "security"
        return normalized

    def _build_policy_request_text(
        self,
        *,
        raw_text: str,
        parsed: PermissionRequestParseResult,
    ) -> str:
        normalized_text = raw_text.strip()
        constraints = parsed.constraints or {}
        if parsed.action == "read" and bool(constraints.get("read_only")):
            if "只读" not in normalized_text and "不修改" not in normalized_text:
                return f"{normalized_text} 只读"
        return normalized_text

    def _current_time(self) -> datetime:
        return self.now_provider().astimezone(timezone.utc)

    def _next_timestamp(self, value: datetime) -> datetime:
        return value + timedelta(microseconds=1)
