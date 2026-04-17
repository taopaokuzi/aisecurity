from __future__ import annotations

from enum import StrEnum


def enum_values(enum_cls: type[StrEnum]) -> tuple[str, ...]:
    return tuple(member.value for member in enum_cls)


class RequestStatus(StrEnum):
    DRAFT = "Draft"
    SUBMITTED = "Submitted"
    EVALUATING = "Evaluating"
    PENDING_APPROVAL = "PendingApproval"
    APPROVED = "Approved"
    PROVISIONING = "Provisioning"
    ACTIVE = "Active"
    EXPIRING = "Expiring"
    EXPIRED = "Expired"
    REVOKED = "Revoked"
    FAILED = "Failed"


class ApprovalStatus(StrEnum):
    NOT_REQUIRED = "NotRequired"
    PENDING = "Pending"
    APPROVED = "Approved"
    REJECTED = "Rejected"
    WITHDRAWN = "Withdrawn"
    EXPIRED = "Expired"
    CALLBACK_FAILED = "CallbackFailed"


class GrantStatus(StrEnum):
    NOT_CREATED = "NotCreated"
    PROVISIONING_REQUESTED = "ProvisioningRequested"
    PROVISIONING = "Provisioning"
    ACTIVE = "Active"
    EXPIRING = "Expiring"
    EXPIRED = "Expired"
    REVOKING = "Revoking"
    REVOKED = "Revoked"
    PROVISION_FAILED = "ProvisionFailed"
    REVOKE_FAILED = "RevokeFailed"


class SessionStatus(StrEnum):
    ACTIVE = "Active"
    REVOKING = "Revoking"
    REVOKED = "Revoked"
    SYNCING = "Syncing"
    SYNC_FAILED = "SyncFailed"
    EXPIRED = "Expired"


class TaskStatus(StrEnum):
    PENDING = "Pending"
    RUNNING = "Running"
    SUCCEEDED = "Succeeded"
    FAILED = "Failed"
    RETRYING = "Retrying"
    COMPENSATING = "Compensating"
    COMPENSATED = "Compensated"


class RiskLevel(StrEnum):
    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"
    CRITICAL = "Critical"


class ActorType(StrEnum):
    USER = "User"
    AGENT = "Agent"
    APPROVER = "Approver"
    IT_ADMIN = "ITAdmin"
    SECURITY_ADMIN = "SecurityAdmin"
    SYSTEM = "System"


class OperatorType(StrEnum):
    USER = "User"
    AGENT = "Agent"
    APPROVER = "Approver"
    IT_ADMIN = "ITAdmin"
    SECURITY_ADMIN = "SecurityAdmin"
    SYSTEM = "System"


class UserStatus(StrEnum):
    ACTIVE = "Active"
    DISABLED = "Disabled"


class IdentitySource(StrEnum):
    SSO = "SSO"
    IMPORTED = "Imported"


class AgentType(StrEnum):
    FIRST_PARTY = "first_party"


class AgentStatus(StrEnum):
    ACTIVE = "Active"
    DISABLED = "Disabled"


class DelegationStatus(StrEnum):
    ACTIVE = "Active"
    EXPIRED = "Expired"
    REVOKED = "Revoked"


class ConnectorStatus(StrEnum):
    ACCEPTED = "Accepted"
    APPLIED = "Applied"
    FAILED = "Failed"
    PARTIAL = "Partial"


class AuditResult(StrEnum):
    SUCCESS = "Success"
    FAIL = "Fail"
    DENIED = "Denied"


REQUEST_STATUS_VALUES = enum_values(RequestStatus)
APPROVAL_STATUS_VALUES = enum_values(ApprovalStatus)
GRANT_STATUS_VALUES = enum_values(GrantStatus)
SESSION_STATUS_VALUES = enum_values(SessionStatus)
TASK_STATUS_VALUES = enum_values(TaskStatus)
RISK_LEVEL_VALUES = enum_values(RiskLevel)
ACTOR_TYPE_VALUES = enum_values(ActorType)
OPERATOR_TYPE_VALUES = enum_values(OperatorType)
USER_STATUS_VALUES = enum_values(UserStatus)
IDENTITY_SOURCE_VALUES = enum_values(IdentitySource)
AGENT_TYPE_VALUES = enum_values(AgentType)
AGENT_STATUS_VALUES = enum_values(AgentStatus)
DELEGATION_STATUS_VALUES = enum_values(DelegationStatus)
CONNECTOR_STATUS_VALUES = enum_values(ConnectorStatus)
AUDIT_RESULT_VALUES = enum_values(AuditResult)

