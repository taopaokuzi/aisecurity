from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Any, Mapping, TypeAlias, TypeVar

from .enums import (
    ActorType,
    AgentStatus,
    AgentType,
    ApprovalStatus,
    AuditResult,
    ConnectorStatus,
    DelegationStatus,
    GrantStatus,
    IdentitySource,
    RequestStatus,
    RiskLevel,
    SessionStatus,
    TaskStatus,
    UserStatus,
)

JsonPrimitive: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = Any
JsonObject: TypeAlias = dict[str, JsonValue]
JsonArray: TypeAlias = list[JsonValue]

EnumT = TypeVar("EnumT", bound=StrEnum)

_REQUEST_PROVISIONING_GRANT_STATUSES = frozenset(
    {GrantStatus.PROVISIONING_REQUESTED, GrantStatus.PROVISIONING}
)


def _require_text(field_name: str, value: str) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be empty")
    return normalized


def _optional_text(field_name: str, value: str | None) -> str | None:
    if value is None:
        return None
    return _require_text(field_name, value)


def _require_datetime(field_name: str, value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError(f"{field_name} must be a datetime")
    return value


def _validate_time_order(
    start_name: str,
    start_value: datetime | None,
    end_name: str,
    end_value: datetime | None,
) -> None:
    if start_value is None or end_value is None:
        return
    if end_value < start_value:
        raise ValueError(f"{end_name} must be greater than or equal to {start_name}")


def _coerce_enum(
    field_name: str,
    value: EnumT | str | None,
    enum_cls: type[EnumT],
    *,
    allow_none: bool = False,
) -> EnumT | None:
    if value is None:
        if allow_none:
            return None
        raise ValueError(f"{field_name} must not be None")
    if isinstance(value, enum_cls):
        return value
    if isinstance(value, str):
        try:
            return enum_cls(value)
        except ValueError as exc:
            allowed_values = ", ".join(member.value for member in enum_cls)
            raise ValueError(f"{field_name} must be one of: {allowed_values}") from exc
    raise TypeError(f"{field_name} must be a string or {enum_cls.__name__}")


def _coerce_json_object(
    field_name: str,
    value: Mapping[str, JsonValue] | None,
    *,
    required: bool = False,
) -> JsonObject | None:
    if value is None:
        if required:
            raise ValueError(f"{field_name} must not be None")
        return None
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a mapping")
    return dict(value)


def _require_non_negative(field_name: str, value: int) -> int:
    if not isinstance(value, int):
        raise TypeError(f"{field_name} must be an integer")
    if value < 0:
        raise ValueError(f"{field_name} must be greater than or equal to 0")
    return value


@dataclass(slots=True, frozen=True, kw_only=True)
class User:
    user_id: str
    employee_no: str | None
    display_name: str
    email: str | None
    department_id: str | None
    department_name: str | None
    manager_user_id: str | None
    user_status: UserStatus | str
    identity_source: IdentitySource | str
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "user_id", _require_text("user_id", self.user_id))
        object.__setattr__(self, "employee_no", _optional_text("employee_no", self.employee_no))
        object.__setattr__(self, "display_name", _require_text("display_name", self.display_name))
        object.__setattr__(self, "email", _optional_text("email", self.email))
        object.__setattr__(self, "department_id", _optional_text("department_id", self.department_id))
        object.__setattr__(
            self,
            "department_name",
            _optional_text("department_name", self.department_name),
        )
        object.__setattr__(
            self,
            "manager_user_id",
            _optional_text("manager_user_id", self.manager_user_id),
        )
        object.__setattr__(
            self,
            "user_status",
            _coerce_enum("user_status", self.user_status, UserStatus),
        )
        object.__setattr__(
            self,
            "identity_source",
            _coerce_enum("identity_source", self.identity_source, IdentitySource),
        )
        _require_datetime("created_at", self.created_at)
        _require_datetime("updated_at", self.updated_at)
        _validate_time_order("created_at", self.created_at, "updated_at", self.updated_at)


@dataclass(slots=True, frozen=True, kw_only=True)
class AgentIdentity:
    agent_id: str
    agent_name: str
    agent_version: str
    created_at: datetime
    updated_at: datetime
    agent_type: AgentType | str = AgentType.FIRST_PARTY
    agent_status: AgentStatus | str = AgentStatus.ACTIVE
    capability_scope: Mapping[str, JsonValue] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "agent_id", _require_text("agent_id", self.agent_id))
        object.__setattr__(self, "agent_name", _require_text("agent_name", self.agent_name))
        object.__setattr__(
            self,
            "agent_version",
            _require_text("agent_version", self.agent_version),
        )
        object.__setattr__(
            self,
            "agent_type",
            _coerce_enum("agent_type", self.agent_type, AgentType),
        )
        object.__setattr__(
            self,
            "agent_status",
            _coerce_enum("agent_status", self.agent_status, AgentStatus),
        )
        object.__setattr__(
            self,
            "capability_scope",
            _coerce_json_object("capability_scope", self.capability_scope),
        )
        _require_datetime("created_at", self.created_at)
        _require_datetime("updated_at", self.updated_at)
        _validate_time_order("created_at", self.created_at, "updated_at", self.updated_at)


@dataclass(slots=True, frozen=True, kw_only=True)
class DelegationCredential:
    delegation_id: str
    user_id: str
    agent_id: str
    task_scope: str
    scope: Mapping[str, JsonValue]
    delegation_status: DelegationStatus | str
    issued_at: datetime
    expire_at: datetime
    created_at: datetime
    updated_at: datetime
    revoked_at: datetime | None = None
    revocation_reason: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "delegation_id",
            _require_text("delegation_id", self.delegation_id),
        )
        object.__setattr__(self, "user_id", _require_text("user_id", self.user_id))
        object.__setattr__(self, "agent_id", _require_text("agent_id", self.agent_id))
        object.__setattr__(self, "task_scope", _require_text("task_scope", self.task_scope))
        object.__setattr__(self, "scope", _coerce_json_object("scope", self.scope, required=True))
        object.__setattr__(
            self,
            "delegation_status",
            _coerce_enum("delegation_status", self.delegation_status, DelegationStatus),
        )
        _require_datetime("issued_at", self.issued_at)
        _require_datetime("expire_at", self.expire_at)
        _validate_time_order("issued_at", self.issued_at, "expire_at", self.expire_at)
        if self.revoked_at is not None:
            _require_datetime("revoked_at", self.revoked_at)
            if self.delegation_status is not DelegationStatus.REVOKED:
                raise ValueError("revoked_at requires delegation_status to be Revoked")
        object.__setattr__(
            self,
            "revocation_reason",
            _optional_text("revocation_reason", self.revocation_reason),
        )
        _require_datetime("created_at", self.created_at)
        _require_datetime("updated_at", self.updated_at)
        _validate_time_order("created_at", self.created_at, "updated_at", self.updated_at)


@dataclass(slots=True, frozen=True, kw_only=True)
class PermissionRequest:
    request_id: str
    user_id: str
    agent_id: str
    delegation_id: str
    raw_text: str
    created_at: datetime
    updated_at: datetime
    resource_key: str | None = None
    resource_type: str | None = None
    action: str | None = None
    constraints: Mapping[str, JsonValue] | None = None
    requested_duration: str | None = None
    structured_request: Mapping[str, JsonValue] | None = None
    suggested_permission: str | None = None
    risk_level: RiskLevel | str | None = None
    approval_status: ApprovalStatus | str = ApprovalStatus.PENDING
    grant_status: GrantStatus | str = GrantStatus.NOT_CREATED
    request_status: RequestStatus | str = RequestStatus.SUBMITTED
    current_task_state: TaskStatus | str | None = None
    policy_version: str | None = None
    renew_round: int = 0
    failed_reason: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "request_id", _require_text("request_id", self.request_id))
        object.__setattr__(self, "user_id", _require_text("user_id", self.user_id))
        object.__setattr__(self, "agent_id", _require_text("agent_id", self.agent_id))
        object.__setattr__(
            self,
            "delegation_id",
            _require_text("delegation_id", self.delegation_id),
        )
        object.__setattr__(self, "raw_text", _require_text("raw_text", self.raw_text))
        object.__setattr__(self, "resource_key", _optional_text("resource_key", self.resource_key))
        object.__setattr__(
            self,
            "resource_type",
            _optional_text("resource_type", self.resource_type),
        )
        object.__setattr__(self, "action", _optional_text("action", self.action))
        object.__setattr__(
            self,
            "constraints",
            _coerce_json_object("constraints", self.constraints),
        )
        object.__setattr__(
            self,
            "requested_duration",
            _optional_text("requested_duration", self.requested_duration),
        )
        object.__setattr__(
            self,
            "structured_request",
            _coerce_json_object("structured_request", self.structured_request),
        )
        object.__setattr__(
            self,
            "suggested_permission",
            _optional_text("suggested_permission", self.suggested_permission),
        )
        object.__setattr__(
            self,
            "risk_level",
            _coerce_enum("risk_level", self.risk_level, RiskLevel, allow_none=True),
        )
        object.__setattr__(
            self,
            "approval_status",
            _coerce_enum("approval_status", self.approval_status, ApprovalStatus),
        )
        object.__setattr__(
            self,
            "grant_status",
            _coerce_enum("grant_status", self.grant_status, GrantStatus),
        )
        object.__setattr__(
            self,
            "request_status",
            _coerce_enum("request_status", self.request_status, RequestStatus),
        )
        object.__setattr__(
            self,
            "current_task_state",
            _coerce_enum(
                "current_task_state",
                self.current_task_state,
                TaskStatus,
                allow_none=True,
            ),
        )
        object.__setattr__(
            self,
            "policy_version",
            _optional_text("policy_version", self.policy_version),
        )
        object.__setattr__(
            self,
            "renew_round",
            _require_non_negative("renew_round", self.renew_round),
        )
        object.__setattr__(
            self,
            "failed_reason",
            _optional_text("failed_reason", self.failed_reason),
        )
        _require_datetime("created_at", self.created_at)
        _require_datetime("updated_at", self.updated_at)
        _validate_time_order("created_at", self.created_at, "updated_at", self.updated_at)
        if self.request_status is RequestStatus.ACTIVE and self.grant_status is not GrantStatus.ACTIVE:
            raise ValueError("Active requests require grant_status to be Active")
        if (
            self.request_status is RequestStatus.PROVISIONING
            and self.grant_status not in _REQUEST_PROVISIONING_GRANT_STATUSES
        ):
            raise ValueError(
                "Provisioning requests require grant_status to be ProvisioningRequested or Provisioning"
            )


@dataclass(slots=True, frozen=True, kw_only=True)
class ApprovalRecord:
    approval_id: str
    request_id: str
    approval_node: str
    approval_status: ApprovalStatus | str
    created_at: datetime
    updated_at: datetime
    external_approval_id: str | None = None
    approver_id: str | None = None
    callback_payload: Mapping[str, JsonValue] | None = None
    idempotency_key: str | None = None
    submitted_at: datetime | None = None
    approved_at: datetime | None = None
    rejected_at: datetime | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "approval_id", _require_text("approval_id", self.approval_id))
        object.__setattr__(self, "request_id", _require_text("request_id", self.request_id))
        object.__setattr__(
            self,
            "approval_node",
            _require_text("approval_node", self.approval_node),
        )
        object.__setattr__(
            self,
            "approval_status",
            _coerce_enum("approval_status", self.approval_status, ApprovalStatus),
        )
        object.__setattr__(
            self,
            "external_approval_id",
            _optional_text("external_approval_id", self.external_approval_id),
        )
        object.__setattr__(self, "approver_id", _optional_text("approver_id", self.approver_id))
        object.__setattr__(
            self,
            "callback_payload",
            _coerce_json_object("callback_payload", self.callback_payload),
        )
        object.__setattr__(
            self,
            "idempotency_key",
            _optional_text("idempotency_key", self.idempotency_key),
        )
        if self.submitted_at is not None:
            _require_datetime("submitted_at", self.submitted_at)
        if self.approved_at is not None:
            _require_datetime("approved_at", self.approved_at)
        if self.rejected_at is not None:
            _require_datetime("rejected_at", self.rejected_at)
        if self.approved_at is not None and self.rejected_at is not None:
            raise ValueError("approved_at and rejected_at cannot both be set")
        _require_datetime("created_at", self.created_at)
        _require_datetime("updated_at", self.updated_at)
        _validate_time_order("created_at", self.created_at, "updated_at", self.updated_at)


@dataclass(slots=True, frozen=True, kw_only=True)
class AccessGrant:
    grant_id: str
    request_id: str
    resource_key: str
    resource_type: str
    action: str
    grant_status: GrantStatus | str
    connector_status: ConnectorStatus | str
    expire_at: datetime
    created_at: datetime
    updated_at: datetime
    reconcile_status: str | None = None
    effective_at: datetime | None = None
    revoked_at: datetime | None = None
    revocation_reason: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "grant_id", _require_text("grant_id", self.grant_id))
        object.__setattr__(self, "request_id", _require_text("request_id", self.request_id))
        object.__setattr__(
            self,
            "resource_key",
            _require_text("resource_key", self.resource_key),
        )
        object.__setattr__(
            self,
            "resource_type",
            _require_text("resource_type", self.resource_type),
        )
        object.__setattr__(self, "action", _require_text("action", self.action))
        object.__setattr__(
            self,
            "grant_status",
            _coerce_enum("grant_status", self.grant_status, GrantStatus),
        )
        object.__setattr__(
            self,
            "connector_status",
            _coerce_enum("connector_status", self.connector_status, ConnectorStatus),
        )
        _require_datetime("expire_at", self.expire_at)
        object.__setattr__(
            self,
            "reconcile_status",
            _optional_text("reconcile_status", self.reconcile_status),
        )
        if self.effective_at is not None:
            _require_datetime("effective_at", self.effective_at)
            _validate_time_order("effective_at", self.effective_at, "expire_at", self.expire_at)
        if self.revoked_at is not None:
            _require_datetime("revoked_at", self.revoked_at)
            if self.grant_status is not GrantStatus.REVOKED:
                raise ValueError("revoked_at requires grant_status to be Revoked")
        object.__setattr__(
            self,
            "revocation_reason",
            _optional_text("revocation_reason", self.revocation_reason),
        )
        _require_datetime("created_at", self.created_at)
        _require_datetime("updated_at", self.updated_at)
        _validate_time_order("created_at", self.created_at, "updated_at", self.updated_at)
        if self.grant_status is GrantStatus.ACTIVE and self.connector_status is not ConnectorStatus.APPLIED:
            raise ValueError("Active grants require connector_status to be Applied")


@dataclass(slots=True, frozen=True, kw_only=True)
class SessionContext:
    global_session_id: str
    request_id: str
    agent_id: str
    user_id: str
    session_status: SessionStatus | str
    created_at: datetime
    updated_at: datetime
    task_session_id: str | None = None
    connector_session_ref: str | None = None
    revocation_reason: str | None = None
    last_sync_at: datetime | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "global_session_id",
            _require_text("global_session_id", self.global_session_id),
        )
        object.__setattr__(self, "request_id", _require_text("request_id", self.request_id))
        object.__setattr__(self, "agent_id", _require_text("agent_id", self.agent_id))
        object.__setattr__(self, "user_id", _require_text("user_id", self.user_id))
        object.__setattr__(
            self,
            "session_status",
            _coerce_enum("session_status", self.session_status, SessionStatus),
        )
        object.__setattr__(
            self,
            "task_session_id",
            _optional_text("task_session_id", self.task_session_id),
        )
        object.__setattr__(
            self,
            "connector_session_ref",
            _optional_text("connector_session_ref", self.connector_session_ref),
        )
        object.__setattr__(
            self,
            "revocation_reason",
            _optional_text("revocation_reason", self.revocation_reason),
        )
        if self.last_sync_at is not None:
            _require_datetime("last_sync_at", self.last_sync_at)
        _require_datetime("created_at", self.created_at)
        _require_datetime("updated_at", self.updated_at)
        _validate_time_order("created_at", self.created_at, "updated_at", self.updated_at)


@dataclass(slots=True, frozen=True, kw_only=True)
class AuditRecord:
    audit_id: str
    event_type: str
    actor_type: ActorType | str
    result: AuditResult | str
    created_at: datetime
    request_id: str | None = None
    actor_id: str | None = None
    subject_chain: str | None = None
    reason: str | None = None
    metadata: Mapping[str, JsonValue] | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "audit_id", _require_text("audit_id", self.audit_id))
        object.__setattr__(self, "event_type", _require_text("event_type", self.event_type))
        object.__setattr__(
            self,
            "actor_type",
            _coerce_enum("actor_type", self.actor_type, ActorType),
        )
        object.__setattr__(self, "result", _coerce_enum("result", self.result, AuditResult))
        object.__setattr__(self, "request_id", _optional_text("request_id", self.request_id))
        object.__setattr__(self, "actor_id", _optional_text("actor_id", self.actor_id))
        object.__setattr__(
            self,
            "subject_chain",
            _optional_text("subject_chain", self.subject_chain),
        )
        object.__setattr__(self, "reason", _optional_text("reason", self.reason))
        object.__setattr__(self, "metadata", _coerce_json_object("metadata", self.metadata))
        _require_datetime("created_at", self.created_at)
