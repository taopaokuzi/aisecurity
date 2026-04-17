from __future__ import annotations

import json
import re
from dataclasses import dataclass
from json import JSONDecodeError
from typing import Any, Mapping

from packages.prompts import PromptNotFoundError, PromptRenderError

from .llm_gateway import LLMGateway, LLMGatewayError, LLMRequest

_READONLY_TERMS = (
    "只读",
    "只查看",
    "仅查看",
    "只看",
    "不需要修改",
    "无需修改",
    "不修改",
    "只看不改",
)
_REQUEST_EDIT_TERMS = ("申请修改", "申请编辑", "request_edit")
_WRITE_TERMS = ("修改", "编辑", "变更", "更新", "write", "edit")
_READ_TERMS = ("查看", "查阅", "浏览", "read", "view", "看一下")
_RESOURCE_HINTS = (
    {
        "resource_key": "sales.q3_report",
        "resource_type": "report",
        "target_department": "sales",
        "resource_sensitivity": "internal",
        "terms": ("销售部", "q3", "报表"),
    },
    {
        "resource_key": "finance.payroll",
        "resource_type": "report",
        "target_department": "finance",
        "resource_sensitivity": "high",
        "terms": ("薪资", "工资", "薪酬", "payroll", "报表"),
    },
    {
        "resource_key": "shared.team_doc",
        "resource_type": "doc",
        "target_department": "shared",
        "resource_sensitivity": "low",
        "terms": ("共享文档", "团队文档", "文档"),
    },
)
_DEPARTMENT_TERMS = {
    "sales": ("销售部", "销售"),
    "finance": ("财务部", "财务", "finance"),
    "shared": ("共享", "团队"),
    "security": ("安全部", "安全", "security"),
}
_ALLOWED_ACTIONS = frozenset({"read", "write", "request_edit"})
_ALLOWED_RESOURCE_TYPES = frozenset({"report", "doc"})
_ALLOWED_SENSITIVITIES = frozenset({"low", "internal", "high", "restricted"})
_DEFAULT_CONFIDENCE = 0.35


@dataclass(slots=True, frozen=True)
class PermissionRequestParseResult:
    source: str
    resource_type: str | None
    resource_key: str | None
    action: str | None
    requested_duration: str | None
    constraints: dict[str, Any] | None
    reason: str | None
    confidence: float
    target_department: str | None = None
    resource_sensitivity: str | None = None
    llm_model: str | None = None
    llm_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "resource_type": self.resource_type,
            "resource_key": self.resource_key,
            "action": self.action,
            "requested_duration": self.requested_duration,
            "constraints": dict(self.constraints) if self.constraints is not None else None,
            "reason": self.reason,
            "confidence": self.confidence,
            "target_department": self.target_department,
            "resource_sensitivity": self.resource_sensitivity,
            "llm_model": self.llm_model,
            "llm_error": self.llm_error,
        }


class PermissionRequestParser:
    def __init__(self, *, llm_gateway: LLMGateway | None = None) -> None:
        self.llm_gateway = llm_gateway

    def parse(self, request_text: str) -> PermissionRequestParseResult:
        normalized_text = request_text.strip()
        if not normalized_text:
            raise ValueError("request_text must not be empty")

        if self.llm_gateway is not None:
            try:
                response = self.llm_gateway.invoke(
                    LLMRequest(
                        prompt_name="parse_permission_request",
                        prompt_variables={"request_text": normalized_text},
                    )
                )
                payload = json.loads(response.content)
                if not isinstance(payload, Mapping):
                    raise ValueError("LLM parser output must be a JSON object.")
                return self._normalize_result(
                    payload,
                    request_text=normalized_text,
                    source="llm_gateway",
                    llm_model=response.model,
                )
            except (
                JSONDecodeError,
                LLMGatewayError,
                PromptNotFoundError,
                PromptRenderError,
                TypeError,
                ValueError,
            ) as exc:
                return self._heuristic_parse(normalized_text, llm_error=str(exc))

        return self._heuristic_parse(normalized_text)

    def _normalize_result(
        self,
        payload: Mapping[str, Any],
        *,
        request_text: str,
        source: str,
        llm_model: str | None = None,
        llm_error: str | None = None,
    ) -> PermissionRequestParseResult:
        resource_key = _normalize_optional_text(payload.get("resource_key"))
        action = _normalize_action(payload.get("action"))
        resource_type = _normalize_resource_type(payload.get("resource_type"))
        requested_duration = _normalize_duration(payload.get("requested_duration"))
        constraints = _normalize_constraints(payload.get("constraints"))
        reason = _normalize_optional_text(payload.get("reason"))
        confidence = _normalize_confidence(payload.get("confidence"))
        target_department = _normalize_department(payload.get("target_department"))
        resource_sensitivity = _normalize_sensitivity(payload.get("resource_sensitivity"))

        matched_hint = _match_resource_hint(request_text)
        if matched_hint is not None:
            resource_key = resource_key or matched_hint["resource_key"]
            resource_type = resource_type or matched_hint["resource_type"]
            target_department = target_department or matched_hint["target_department"]
            resource_sensitivity = resource_sensitivity or matched_hint["resource_sensitivity"]

        action = action or _infer_action(request_text)
        requested_duration = requested_duration or _infer_requested_duration(request_text)
        inferred_constraints = _infer_constraints(request_text, action=action)
        if inferred_constraints is not None:
            constraints = dict(constraints or {})
            constraints.update(inferred_constraints)
        target_department = target_department or _infer_department(request_text)
        resource_type = resource_type or _infer_resource_type(request_text)

        if reason is None:
            reason = _build_reason(
                resource_key=resource_key,
                action=action,
                llm_error=llm_error,
                fallback=False,
            )

        if confidence is None:
            confidence = _score_confidence(
                resource_key=resource_key,
                resource_type=resource_type,
                action=action,
                requested_duration=requested_duration,
            )

        return PermissionRequestParseResult(
            source=source,
            resource_type=resource_type,
            resource_key=resource_key,
            action=action,
            requested_duration=requested_duration,
            constraints=constraints,
            reason=reason,
            confidence=confidence,
            target_department=target_department,
            resource_sensitivity=resource_sensitivity,
            llm_model=llm_model,
            llm_error=llm_error,
        )

    def _heuristic_parse(
        self,
        request_text: str,
        *,
        llm_error: str | None = None,
    ) -> PermissionRequestParseResult:
        matched_hint = _match_resource_hint(request_text)
        resource_key = matched_hint["resource_key"] if matched_hint is not None else None
        resource_type = (
            matched_hint["resource_type"]
            if matched_hint is not None
            else _infer_resource_type(request_text)
        )
        target_department = (
            matched_hint["target_department"]
            if matched_hint is not None
            else _infer_department(request_text)
        )
        resource_sensitivity = (
            matched_hint["resource_sensitivity"]
            if matched_hint is not None
            else None
        )
        action = _infer_action(request_text)
        requested_duration = _infer_requested_duration(request_text)
        constraints = _infer_constraints(request_text, action=action)
        confidence = _score_confidence(
            resource_key=resource_key,
            resource_type=resource_type,
            action=action,
            requested_duration=requested_duration,
        )
        reason = _build_reason(
            resource_key=resource_key,
            action=action,
            llm_error=llm_error,
            fallback=True,
        )
        return PermissionRequestParseResult(
            source="heuristic",
            resource_type=resource_type,
            resource_key=resource_key,
            action=action,
            requested_duration=requested_duration,
            constraints=constraints,
            reason=reason,
            confidence=confidence,
            target_department=target_department,
            resource_sensitivity=resource_sensitivity,
            llm_error=llm_error,
        )


def _normalize_optional_text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _normalize_action(value: Any) -> str | None:
    normalized = _normalize_optional_text(value)
    if normalized is None:
        return None
    lowered = normalized.lower()
    return lowered if lowered in _ALLOWED_ACTIONS else None


def _normalize_resource_type(value: Any) -> str | None:
    normalized = _normalize_optional_text(value)
    if normalized is None:
        return None
    lowered = normalized.lower()
    return lowered if lowered in _ALLOWED_RESOURCE_TYPES else None


def _normalize_sensitivity(value: Any) -> str | None:
    normalized = _normalize_optional_text(value)
    if normalized is None:
        return None
    lowered = normalized.lower()
    return lowered if lowered in _ALLOWED_SENSITIVITIES else None


def _normalize_department(value: Any) -> str | None:
    normalized = _normalize_optional_text(value)
    if normalized is None:
        return None
    lowered = normalized.lower()
    for department, terms in _DEPARTMENT_TERMS.items():
        if lowered == department or lowered in terms:
            return department
    return lowered


def _normalize_constraints(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, Mapping):
        return dict(value)
    return None


def _normalize_confidence(value: Any) -> float | None:
    if value is None:
        return None
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return None
    if confidence < 0:
        return 0.0
    if confidence > 1:
        return 1.0
    return round(confidence, 2)


def _normalize_duration(value: Any) -> str | None:
    normalized = _normalize_optional_text(value)
    if normalized is None:
        return None
    if re.fullmatch(r"P\d+[DWM]", normalized) or re.fullmatch(r"PT\d+H", normalized):
        return normalized
    return _infer_requested_duration(normalized)


def _match_resource_hint(request_text: str) -> dict[str, str] | None:
    lowered = request_text.lower()
    best_match: tuple[int, dict[str, str]] | None = None
    for hint in _RESOURCE_HINTS:
        score = sum(1 for term in hint["terms"] if term.lower() in lowered)
        if score <= 0:
            continue
        if best_match is None or score > best_match[0]:
            best_match = (
                score,
                {
                    "resource_key": hint["resource_key"],
                    "resource_type": hint["resource_type"],
                    "target_department": hint["target_department"],
                    "resource_sensitivity": hint["resource_sensitivity"],
                },
            )
    return best_match[1] if best_match is not None else None


def _infer_action(request_text: str) -> str | None:
    lowered = request_text.lower()
    if any(term.lower() in lowered for term in _READONLY_TERMS):
        return "read"
    if any(term.lower() in lowered for term in _REQUEST_EDIT_TERMS):
        return "request_edit"
    if any(term.lower() in lowered for term in _WRITE_TERMS):
        return "write"
    if any(term.lower() in lowered for term in _READ_TERMS):
        return "read"
    return None


def _infer_resource_type(request_text: str) -> str | None:
    lowered = request_text.lower()
    if "报表" in lowered or "report" in lowered:
        return "report"
    if "文档" in lowered or "doc" in lowered:
        return "doc"
    return None


def _infer_department(request_text: str) -> str | None:
    lowered = request_text.lower()
    for department, terms in _DEPARTMENT_TERMS.items():
        if any(term.lower() in lowered for term in terms):
            return department
    return None


def _infer_constraints(
    request_text: str,
    *,
    action: str | None,
) -> dict[str, Any] | None:
    lowered = request_text.lower()
    constraints: dict[str, Any] = {}
    if any(term.lower() in lowered for term in _READONLY_TERMS):
        constraints["read_only"] = True
        constraints["no_modification"] = True
    if action == "read" and "只" in request_text:
        constraints.setdefault("read_only", True)
    return constraints or None


def _infer_requested_duration(request_text: str) -> str | None:
    normalized = request_text.strip().lower()

    hour_match = re.search(r"(\d+)\s*小时", normalized)
    if hour_match:
        return f"PT{int(hour_match.group(1))}H"

    month_match = re.search(r"(\d+)\s*个?月", normalized)
    if month_match:
        return f"P{int(month_match.group(1))}M"

    if "一周" in normalized or "七天" in normalized:
        return "P7D"

    week_match = re.search(r"(\d+)\s*周", normalized)
    if week_match:
        return f"P{int(week_match.group(1)) * 7}D"

    if "一天" in normalized:
        return "P1D"

    day_match = re.search(r"(\d+)\s*天", normalized)
    if day_match:
        return f"P{int(day_match.group(1))}D"

    return None


def _score_confidence(
    *,
    resource_key: str | None,
    resource_type: str | None,
    action: str | None,
    requested_duration: str | None,
) -> float:
    confidence = _DEFAULT_CONFIDENCE
    if resource_key is not None:
        confidence += 0.3
    if resource_type is not None:
        confidence += 0.1
    if action is not None:
        confidence += 0.2
    if requested_duration is not None:
        confidence += 0.05
    return round(min(confidence, 0.95), 2)


def _build_reason(
    *,
    resource_key: str | None,
    action: str | None,
    llm_error: str | None,
    fallback: bool,
) -> str:
    reasons: list[str] = []
    if fallback:
        reasons.append("使用规则回退解析申请文本。")
    else:
        reasons.append("使用结构化解析结果补全申请字段。")

    if resource_key is not None:
        reasons.append(f"识别到资源 `{resource_key}`。")
    if action is not None:
        reasons.append(f"识别到动作 `{action}`。")
    if resource_key is None and action is None:
        reasons.append("资源和动作都不明确，保留保守结果。")
    if llm_error:
        reasons.append(f"LLM 解析不可用，原因：{llm_error}")
    return " ".join(reasons)
