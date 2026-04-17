from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ErrorCode(StrEnum):
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    DELEGATION_INVALID = "DELEGATION_INVALID"
    AGENT_DISABLED = "AGENT_DISABLED"
    REQUEST_MESSAGE_EMPTY = "REQUEST_MESSAGE_EMPTY"
    REQUEST_STATUS_INVALID = "REQUEST_STATUS_INVALID"
    POLICY_MAPPING_NOT_FOUND = "POLICY_MAPPING_NOT_FOUND"
    RISK_EVALUATION_FAILED = "RISK_EVALUATION_FAILED"
    CALLBACK_SIGNATURE_INVALID = "CALLBACK_SIGNATURE_INVALID"
    CALLBACK_SOURCE_INVALID = "CALLBACK_SOURCE_INVALID"
    CALLBACK_DUPLICATED = "CALLBACK_DUPLICATED"
    APPROVAL_NOT_APPROVED = "APPROVAL_NOT_APPROVED"
    PROVISION_POLICY_RECHECK_FAILED = "PROVISION_POLICY_RECHECK_FAILED"
    CONNECTOR_UNAVAILABLE = "CONNECTOR_UNAVAILABLE"
    SESSION_ALREADY_REVOKED = "SESSION_ALREADY_REVOKED"
    RETRY_NOT_ALLOWED = "RETRY_NOT_ALLOWED"
    DELEGATION_SCOPE_INVALID = "DELEGATION_SCOPE_INVALID"
    DELEGATION_EXPIRE_AT_INVALID = "DELEGATION_EXPIRE_AT_INVALID"
    APPROVAL_RECORD_NOT_FOUND = "APPROVAL_RECORD_NOT_FOUND"
    GRANT_ALREADY_ACTIVE = "GRANT_ALREADY_ACTIVE"


ERROR_MESSAGES: dict[ErrorCode, str] = {
    ErrorCode.UNAUTHORIZED: "Unauthenticated request",
    ErrorCode.FORBIDDEN: "Access is forbidden",
    ErrorCode.DELEGATION_INVALID: "Delegation is expired, revoked, or otherwise invalid",
    ErrorCode.AGENT_DISABLED: "Agent is disabled",
    ErrorCode.REQUEST_MESSAGE_EMPTY: "Request message is empty",
    ErrorCode.REQUEST_STATUS_INVALID: "Current request status does not allow this operation",
    ErrorCode.POLICY_MAPPING_NOT_FOUND: "Policy mapping rule was not found",
    ErrorCode.RISK_EVALUATION_FAILED: "Risk evaluation failed",
    ErrorCode.CALLBACK_SIGNATURE_INVALID: "Callback signature is invalid",
    ErrorCode.CALLBACK_SOURCE_INVALID: "Callback source is invalid",
    ErrorCode.CALLBACK_DUPLICATED: "Callback has already been processed",
    ErrorCode.APPROVAL_NOT_APPROVED: "Approval has not been granted",
    ErrorCode.PROVISION_POLICY_RECHECK_FAILED: "Provision policy recheck failed",
    ErrorCode.CONNECTOR_UNAVAILABLE: "External connector is unavailable",
    ErrorCode.SESSION_ALREADY_REVOKED: "Session has already been revoked",
    ErrorCode.RETRY_NOT_ALLOWED: "Retry is not allowed for the current task",
    ErrorCode.DELEGATION_SCOPE_INVALID: "Delegation scope is invalid",
    ErrorCode.DELEGATION_EXPIRE_AT_INVALID: "Delegation expire_at is invalid",
    ErrorCode.APPROVAL_RECORD_NOT_FOUND: "Approval record was not found",
    ErrorCode.GRANT_ALREADY_ACTIVE: "Grant is already active",
}

TASK_004_REQUIRED_ERROR_CODES = (
    ErrorCode.DELEGATION_INVALID,
    ErrorCode.AGENT_DISABLED,
    ErrorCode.REQUEST_STATUS_INVALID,
    ErrorCode.CALLBACK_DUPLICATED,
    ErrorCode.CONNECTOR_UNAVAILABLE,
    ErrorCode.SESSION_ALREADY_REVOKED,
)


@dataclass(slots=True)
class DomainError(Exception):
    code: ErrorCode | str
    message: str | None = None
    details: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.code, ErrorCode):
            self.code = ErrorCode(self.code)
        if self.message is None:
            self.message = ERROR_MESSAGES.get(self.code, self.code.value)
        Exception.__init__(self, self.message)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code.value,
            "message": self.message,
            "details": dict(self.details),
        }
