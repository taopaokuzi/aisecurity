from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable
from uuid import uuid4

from packages.domain import (
    ActorType,
    AgentStatus,
    ApprovalStatus,
    DelegationStatus,
    DomainError,
    ErrorCode,
    GrantStatus,
    OperatorType,
    PermissionRequest,
    RequestStatus,
    UserStatus,
)
from packages.infrastructure.db.models import (
    AgentIdentityRecord,
    AuditRecordRecord,
    DelegationCredentialRecord,
    PermissionRequestEventRecord,
    PermissionRequestRecord,
    UserRecord,
)
from packages.infrastructure.repositories import (
    AgentIdentityRepository,
    AuditRecordRepository,
    DelegationCredentialRepository,
    PermissionRequestEventRepository,
    PermissionRequestRepository,
    UserRepository,
)

_PERMISSION_TASK_SCOPE = "permission_self_service"
_PRIVILEGED_QUERY_OPERATORS = frozenset(
    {
        OperatorType.IT_ADMIN,
        OperatorType.SECURITY_ADMIN,
        OperatorType.SYSTEM,
    }
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _generate_prefixed_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:24]}"


def _normalize_optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized or None


@dataclass(slots=True, frozen=True)
class PermissionRequestCreateInput:
    user_id: str
    agent_id: str
    delegation_id: str
    message: str
    request_id: str
    operator_type: OperatorType | str = OperatorType.USER
    trace_id: str | None = None
    idempotency_key: str | None = None
    conversation_id: str | None = None


@dataclass(slots=True, frozen=True)
class PermissionRequestListInput:
    requester_user_id: str
    operator_type: OperatorType | str = OperatorType.USER
    page: int = 1
    page_size: int = 20
    request_status: RequestStatus | str | None = None
    approval_status: ApprovalStatus | str | None = None
    mine_only: bool = True


@dataclass(slots=True, frozen=True)
class PermissionRequestListResult:
    items: list[PermissionRequest]
    page: int
    page_size: int
    total: int


class PermissionRequestService:
    def __init__(
        self,
        *,
        user_repository: UserRepository,
        agent_repository: AgentIdentityRepository,
        delegation_repository: DelegationCredentialRepository,
        permission_request_repository: PermissionRequestRepository,
        permission_request_event_repository: PermissionRequestEventRepository,
        audit_repository: AuditRecordRepository,
        now_provider: Callable[[], datetime] = _utc_now,
    ) -> None:
        self.user_repository = user_repository
        self.agent_repository = agent_repository
        self.delegation_repository = delegation_repository
        self.permission_request_repository = permission_request_repository
        self.permission_request_event_repository = permission_request_event_repository
        self.audit_repository = audit_repository
        self.now_provider = now_provider

    def create_permission_request(
        self,
        command: PermissionRequestCreateInput,
    ) -> PermissionRequest:
        operator_type = self._coerce_operator_type(command.operator_type)
        if command.idempotency_key:
            existing = self._get_idempotent_request(
                user_id=command.user_id,
                idempotency_key=command.idempotency_key,
            )
            if existing is not None:
                return existing

        now = self._current_time()
        normalized_message = self._validate_message(command.message)
        normalized_conversation_id = _normalize_optional_text(command.conversation_id)

        self._require_active_user(command.user_id)
        self._require_active_agent(command.agent_id)
        self._require_valid_delegation(
            delegation_id=command.delegation_id,
            user_id=command.user_id,
            agent_id=command.agent_id,
            current_time=now,
        )

        # New requests start from the Submitted state; approval is undecided until evaluation.
        record = PermissionRequestRecord(
            request_id=_generate_prefixed_id("req"),
            user_id=command.user_id,
            agent_id=command.agent_id,
            delegation_id=command.delegation_id,
            raw_text=normalized_message,
            resource_key=None,
            resource_type=None,
            action=None,
            constraints_json=None,
            requested_duration=None,
            structured_request_json=None,
            suggested_permission=None,
            risk_level=None,
            approval_status=ApprovalStatus.NOT_REQUIRED.value,
            grant_status=GrantStatus.NOT_CREATED.value,
            request_status=RequestStatus.SUBMITTED.value,
            current_task_state=None,
            policy_version=None,
            renew_round=0,
            failed_reason=None,
            created_at=now,
            updated_at=now,
        )
        self.permission_request_repository.add(record)
        self._flush_permission_request_record()

        event_record = PermissionRequestEventRecord(
            event_id=_generate_prefixed_id("evt"),
            request_id=record.request_id,
            event_type="request.submitted",
            operator_type=operator_type.value,
            operator_id=self._operator_id(
                user_id=command.user_id,
                agent_id=command.agent_id,
                operator_type=operator_type,
            ),
            from_request_status=RequestStatus.DRAFT.value,
            to_request_status=RequestStatus.SUBMITTED.value,
            metadata_json=self._compact_metadata(
                {
                    "agent_id": command.agent_id,
                    "delegation_id": command.delegation_id,
                    "conversation_id": normalized_conversation_id,
                    "api_request_id": command.request_id,
                    "trace_id": command.trace_id,
                    "idempotency_key": command.idempotency_key,
                }
            ),
            occurred_at=now,
            created_at=now,
        )
        self.permission_request_event_repository.add(event_record)

        audit_record = AuditRecordRecord(
            audit_id=_generate_prefixed_id("aud"),
            request_id=record.request_id,
            event_type="request.submitted",
            actor_type=ActorType.USER.value,
            actor_id=command.user_id,
            subject_chain=self._subject_chain(
                user_id=command.user_id,
                agent_id=command.agent_id,
                request_id=record.request_id,
            ),
            result="Success",
            reason=None,
            metadata_json=self._compact_metadata(
                {
                    "agent_id": command.agent_id,
                    "delegation_id": command.delegation_id,
                    "conversation_id": normalized_conversation_id,
                    "operator_type": operator_type.value,
                    "operator_id": self._operator_id(
                        user_id=command.user_id,
                        agent_id=command.agent_id,
                        operator_type=operator_type,
                    ),
                    "api_request_id": command.request_id,
                    "trace_id": command.trace_id,
                    "idempotency_key": command.idempotency_key,
                }
            ),
            created_at=now,
        )
        self.audit_repository.add(audit_record)

        return self._to_domain(record)

    def get_permission_request(
        self,
        permission_request_id: str,
        *,
        requester_user_id: str,
        operator_type: OperatorType | str = OperatorType.USER,
    ) -> PermissionRequest:
        operator = self._coerce_operator_type(operator_type)
        record = self.permission_request_repository.get(permission_request_id)
        if record is None:
            raise DomainError(
                ErrorCode.REQUEST_STATUS_INVALID,
                message="Permission request was not found",
                details={"request_id": permission_request_id, "http_status": 404},
            )

        if not self._is_privileged_query_operator(operator) and record.user_id != requester_user_id:
            raise DomainError(
                ErrorCode.FORBIDDEN,
                details={"request_id": permission_request_id, "http_status": 403},
            )
        return self._to_domain(record)

    def list_permission_requests(
        self,
        query: PermissionRequestListInput,
    ) -> PermissionRequestListResult:
        operator_type = self._coerce_operator_type(query.operator_type)
        if query.page < 1 or query.page_size < 1 or query.page_size > 100:
            raise DomainError(
                ErrorCode.REQUEST_STATUS_INVALID,
                message="Pagination parameters are invalid",
                details={"http_status": 400},
            )

        request_status = self._coerce_request_status(query.request_status)
        approval_status = self._coerce_approval_status(query.approval_status)

        scoped_user_id: str | None
        if self._is_privileged_query_operator(operator_type) and not query.mine_only:
            scoped_user_id = None
        else:
            scoped_user_id = query.requester_user_id

        records, total = self.permission_request_repository.list_paginated(
            user_id=scoped_user_id,
            request_status=request_status.value if request_status is not None else None,
            approval_status=approval_status.value if approval_status is not None else None,
            page=query.page,
            page_size=query.page_size,
        )
        return PermissionRequestListResult(
            items=[self._to_domain(record) for record in records],
            page=query.page,
            page_size=query.page_size,
            total=total,
        )

    def _get_idempotent_request(
        self,
        *,
        user_id: str,
        idempotency_key: str,
    ) -> PermissionRequest | None:
        audit_record = self.audit_repository.get_latest_by_event_and_idempotency_key(
            actor_type=ActorType.USER.value,
            actor_id=user_id,
            event_type="request.submitted",
            idempotency_key=idempotency_key,
        )
        if audit_record is None:
            return None
        permission_request_id = audit_record.request_id
        if not permission_request_id:
            return None
        record = self.permission_request_repository.get(permission_request_id)
        if record is None:
            return None
        return self._to_domain(record)

    def _require_active_user(self, user_id: str) -> UserRecord:
        user = self.user_repository.get(user_id)
        if user is None or user.user_status != UserStatus.ACTIVE.value:
            raise DomainError(
                ErrorCode.DELEGATION_INVALID,
                message="User is invalid or disabled",
                details={"user_id": user_id, "http_status": 400},
            )
        return user

    def _require_active_agent(self, agent_id: str) -> AgentIdentityRecord:
        agent = self.agent_repository.get(agent_id)
        if agent is None:
            raise DomainError(
                ErrorCode.DELEGATION_INVALID,
                message="Agent was not found",
                details={"agent_id": agent_id, "http_status": 404},
            )
        if agent.agent_status != AgentStatus.ACTIVE.value:
            raise DomainError(
                ErrorCode.AGENT_DISABLED,
                details={"agent_id": agent_id, "http_status": 409},
            )
        return agent

    def _require_valid_delegation(
        self,
        *,
        delegation_id: str,
        user_id: str,
        agent_id: str,
        current_time: datetime,
    ) -> DelegationCredentialRecord:
        record = self.delegation_repository.get(delegation_id)
        if record is None:
            raise DomainError(
                ErrorCode.DELEGATION_INVALID,
                details={"delegation_id": delegation_id, "http_status": 404},
            )

        self._sync_expired_status(record, current_time=current_time)
        if record.user_id != user_id or record.agent_id != agent_id:
            raise DomainError(
                ErrorCode.DELEGATION_INVALID,
                details={"delegation_id": delegation_id, "http_status": 400},
            )
        if record.task_scope != _PERMISSION_TASK_SCOPE:
            raise DomainError(
                ErrorCode.DELEGATION_SCOPE_INVALID,
                details={"delegation_id": delegation_id, "field": "task_scope", "http_status": 400},
            )
        if (
            record.delegation_status != DelegationStatus.ACTIVE.value
            or record.expire_at <= current_time
        ):
            raise DomainError(
                ErrorCode.DELEGATION_INVALID,
                details={"delegation_id": delegation_id, "http_status": 400},
            )
        return record

    def _validate_message(self, message: str) -> str:
        if not isinstance(message, str) or not message.strip():
            raise DomainError(
                ErrorCode.REQUEST_MESSAGE_EMPTY,
                details={"field": "message", "http_status": 400},
            )
        return message.strip()

    def _sync_expired_status(
        self,
        record: DelegationCredentialRecord,
        *,
        current_time: datetime,
    ) -> None:
        if (
            record.delegation_status == DelegationStatus.ACTIVE.value
            and record.expire_at <= current_time
        ):
            record.delegation_status = DelegationStatus.EXPIRED.value
            record.updated_at = current_time

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

    def _coerce_request_status(
        self,
        request_status: RequestStatus | str | None,
    ) -> RequestStatus | None:
        if request_status is None or isinstance(request_status, RequestStatus):
            return request_status
        try:
            return RequestStatus(request_status)
        except ValueError as exc:
            raise DomainError(
                ErrorCode.REQUEST_STATUS_INVALID,
                details={"request_status": request_status, "http_status": 400},
            ) from exc

    def _coerce_approval_status(
        self,
        approval_status: ApprovalStatus | str | None,
    ) -> ApprovalStatus | None:
        if approval_status is None or isinstance(approval_status, ApprovalStatus):
            return approval_status
        try:
            return ApprovalStatus(approval_status)
        except ValueError as exc:
            raise DomainError(
                ErrorCode.REQUEST_STATUS_INVALID,
                details={"approval_status": approval_status, "http_status": 400},
            ) from exc

    def _operator_id(
        self,
        *,
        user_id: str,
        agent_id: str,
        operator_type: OperatorType,
    ) -> str:
        if operator_type is OperatorType.AGENT:
            return agent_id
        return user_id

    def _is_privileged_query_operator(self, operator_type: OperatorType) -> bool:
        return operator_type in _PRIVILEGED_QUERY_OPERATORS

    def _to_domain(self, record: PermissionRequestRecord) -> PermissionRequest:
        return PermissionRequest(
            request_id=record.request_id,
            user_id=record.user_id,
            agent_id=record.agent_id,
            delegation_id=record.delegation_id,
            raw_text=record.raw_text,
            resource_key=record.resource_key,
            resource_type=record.resource_type,
            action=record.action,
            constraints=record.constraints_json,
            requested_duration=record.requested_duration,
            structured_request=record.structured_request_json,
            suggested_permission=record.suggested_permission,
            risk_level=record.risk_level,
            approval_status=record.approval_status,
            grant_status=record.grant_status,
            request_status=record.request_status,
            current_task_state=record.current_task_state,
            policy_version=record.policy_version,
            renew_round=record.renew_round,
            failed_reason=record.failed_reason,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    def _current_time(self) -> datetime:
        return self.now_provider().astimezone(timezone.utc)

    def _flush_permission_request_record(self) -> None:
        session = getattr(self.permission_request_repository, "session", None)
        if session is not None:
            session.flush()

    def _subject_chain(self, *, user_id: str, agent_id: str, request_id: str) -> str:
        return f"user:{user_id}->agent:{agent_id}->request:{request_id}"

    def _compact_metadata(self, metadata: dict[str, str | None]) -> dict[str, str]:
        return {key: value for key, value in metadata.items() if value is not None}
