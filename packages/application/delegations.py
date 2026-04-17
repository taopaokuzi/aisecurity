from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Mapping
from uuid import uuid4

from packages.domain import (
    ActorType,
    AgentStatus,
    AuditResult,
    DelegationCredential,
    DelegationStatus,
    DomainError,
    ErrorCode,
    OperatorType,
    UserStatus,
)
from packages.infrastructure.db.models import (
    AgentIdentityRecord,
    AuditRecordRecord,
    DelegationCredentialRecord,
    UserRecord,
)
from packages.infrastructure.repositories import (
    AgentIdentityRepository,
    AuditRecordRepository,
    DelegationCredentialRepository,
    UserRepository,
)

_ALLOWED_TASK_SCOPES = frozenset({"permission_self_service"})
_SCOPE_RESOURCE_TYPES_KEY = "resource_types"
_SCOPE_ALLOWED_ACTIONS_KEY = "allowed_actions"
_SCOPE_KEYS = frozenset({_SCOPE_RESOURCE_TYPES_KEY, _SCOPE_ALLOWED_ACTIONS_KEY})
_ADMIN_OPERATORS = frozenset({OperatorType.IT_ADMIN, OperatorType.SECURITY_ADMIN})


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _generate_prefixed_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:24]}"


def _normalize_string_list(field_name: str, value: Any) -> list[str]:
    if not isinstance(value, list) or not value:
        raise DomainError(
            ErrorCode.DELEGATION_SCOPE_INVALID,
            details={"field": field_name, "http_status": 400},
        )

    normalized: list[str] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            raise DomainError(
                ErrorCode.DELEGATION_SCOPE_INVALID,
                details={"field": field_name, "http_status": 400},
            )
        candidate = item.strip()
        if not candidate:
            raise DomainError(
                ErrorCode.DELEGATION_SCOPE_INVALID,
                details={"field": field_name, "http_status": 400},
            )
        if candidate in seen:
            continue
        seen.add(candidate)
        normalized.append(candidate)
    return normalized


@dataclass(slots=True, frozen=True)
class DelegationCreateInput:
    user_id: str
    agent_id: str
    task_scope: str
    scope: Mapping[str, Any]
    expire_at: datetime
    request_id: str
    trace_id: str | None = None
    idempotency_key: str | None = None


class DelegationService:
    def __init__(
        self,
        *,
        user_repository: UserRepository,
        agent_repository: AgentIdentityRepository,
        delegation_repository: DelegationCredentialRepository,
        audit_repository: AuditRecordRepository,
        now_provider: Callable[[], datetime] = _utc_now,
    ) -> None:
        self.user_repository = user_repository
        self.agent_repository = agent_repository
        self.delegation_repository = delegation_repository
        self.audit_repository = audit_repository
        self.now_provider = now_provider

    def create_delegation(self, command: DelegationCreateInput) -> DelegationCredential:
        if command.idempotency_key:
            existing = self._get_idempotent_delegation(
                user_id=command.user_id,
                idempotency_key=command.idempotency_key,
            )
            if existing is not None:
                return existing

        now = self._current_time()
        self._require_active_user(command.user_id)
        agent = self._require_active_agent(command.agent_id)
        normalized_scope = self._validate_scope(
            command.scope,
            capability_scope=agent.capability_scope_json,
        )
        normalized_expire_at = self._validate_expire_at(command.expire_at, current_time=now)
        self._validate_task_scope(command.task_scope)

        record = DelegationCredentialRecord(
            delegation_id=_generate_prefixed_id("dlg"),
            user_id=command.user_id,
            agent_id=command.agent_id,
            task_scope=command.task_scope.strip(),
            scope_json=normalized_scope,
            delegation_status=DelegationStatus.ACTIVE.value,
            issued_at=now,
            expire_at=normalized_expire_at,
            revoked_at=None,
            revocation_reason=None,
            created_at=now,
            updated_at=now,
        )
        self.delegation_repository.add(record)

        audit_record = AuditRecordRecord(
            audit_id=_generate_prefixed_id("aud"),
            request_id=None,
            event_type="delegation.created",
            actor_type=ActorType.USER.value,
            actor_id=command.user_id,
            subject_chain=self._subject_chain(command.user_id, command.agent_id),
            result=AuditResult.SUCCESS.value,
            reason=None,
            metadata_json={
                "delegation_id": record.delegation_id,
                "agent_id": command.agent_id,
                "task_scope": command.task_scope.strip(),
                "scope": normalized_scope,
                "expire_at": normalized_expire_at.isoformat(),
                "request_id": command.request_id,
                "trace_id": command.trace_id,
                "idempotency_key": command.idempotency_key,
            },
            created_at=now,
        )
        self.audit_repository.add(audit_record)
        return self._to_domain(record)

    def get_delegation(
        self,
        delegation_id: str,
        *,
        requester_user_id: str,
        operator_type: OperatorType | str = OperatorType.USER,
    ) -> DelegationCredential:
        operator = self._coerce_operator_type(operator_type)
        record = self.delegation_repository.get(delegation_id)
        if record is None:
            raise DomainError(
                ErrorCode.DELEGATION_INVALID,
                details={"delegation_id": delegation_id, "http_status": 404},
            )

        self._sync_expired_status(record, current_time=self._current_time())
        if not self._is_admin_operator(operator) and record.user_id != requester_user_id:
            raise DomainError(
                ErrorCode.FORBIDDEN,
                details={"delegation_id": delegation_id, "http_status": 403},
            )
        return self._to_domain(record)

    def validate_delegation(
        self,
        *,
        delegation_id: str,
        user_id: str,
        agent_id: str,
        task_scope: str | None = None,
        resource_type: str | None = None,
        action: str | None = None,
    ) -> DelegationCredential:
        record = self.delegation_repository.get(delegation_id)
        if record is None:
            raise DomainError(
                ErrorCode.DELEGATION_INVALID,
                details={"delegation_id": delegation_id, "http_status": 404},
            )

        now = self._current_time()
        self._sync_expired_status(record, current_time=now)
        if record.user_id != user_id or record.agent_id != agent_id:
            raise DomainError(
                ErrorCode.DELEGATION_INVALID,
                details={"delegation_id": delegation_id, "http_status": 400},
            )
        if record.delegation_status != DelegationStatus.ACTIVE.value or record.expire_at <= now:
            raise DomainError(
                ErrorCode.DELEGATION_INVALID,
                details={"delegation_id": delegation_id, "http_status": 400},
            )

        normalized_scope = self._validate_scope(record.scope_json)
        if task_scope is not None and record.task_scope != task_scope.strip():
            raise DomainError(
                ErrorCode.DELEGATION_SCOPE_INVALID,
                details={"delegation_id": delegation_id, "field": "task_scope", "http_status": 400},
            )
        if resource_type is not None and resource_type not in normalized_scope[_SCOPE_RESOURCE_TYPES_KEY]:
            raise DomainError(
                ErrorCode.DELEGATION_SCOPE_INVALID,
                details={"delegation_id": delegation_id, "field": _SCOPE_RESOURCE_TYPES_KEY, "http_status": 400},
            )
        if action is not None and action not in normalized_scope[_SCOPE_ALLOWED_ACTIONS_KEY]:
            raise DomainError(
                ErrorCode.DELEGATION_SCOPE_INVALID,
                details={"delegation_id": delegation_id, "field": _SCOPE_ALLOWED_ACTIONS_KEY, "http_status": 400},
            )
        return self._to_domain(record)

    def _get_idempotent_delegation(
        self,
        *,
        user_id: str,
        idempotency_key: str,
    ) -> DelegationCredential | None:
        audit_record = self.audit_repository.get_latest_by_event_and_idempotency_key(
            actor_type=ActorType.USER.value,
            actor_id=user_id,
            event_type="delegation.created",
            idempotency_key=idempotency_key,
        )
        if audit_record is None or not audit_record.metadata_json:
            return None
        delegation_id = audit_record.metadata_json.get("delegation_id")
        if not isinstance(delegation_id, str) or not delegation_id:
            return None
        record = self.delegation_repository.get(delegation_id)
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

    def _validate_task_scope(self, task_scope: str) -> str:
        normalized_task_scope = task_scope.strip()
        if normalized_task_scope not in _ALLOWED_TASK_SCOPES:
            raise DomainError(
                ErrorCode.DELEGATION_SCOPE_INVALID,
                details={"field": "task_scope", "http_status": 400},
            )
        return normalized_task_scope

    def _validate_scope(
        self,
        scope: Mapping[str, Any],
        *,
        capability_scope: Mapping[str, Any] | None = None,
    ) -> dict[str, list[str]]:
        if not isinstance(scope, Mapping):
            raise DomainError(
                ErrorCode.DELEGATION_SCOPE_INVALID,
                details={"field": "scope", "http_status": 400},
            )

        keys = set(scope.keys())
        if keys != _SCOPE_KEYS:
            raise DomainError(
                ErrorCode.DELEGATION_SCOPE_INVALID,
                details={"field": "scope", "http_status": 400},
            )

        normalized_scope = {
            _SCOPE_RESOURCE_TYPES_KEY: _normalize_string_list(
                _SCOPE_RESOURCE_TYPES_KEY,
                scope.get(_SCOPE_RESOURCE_TYPES_KEY),
            ),
            _SCOPE_ALLOWED_ACTIONS_KEY: _normalize_string_list(
                _SCOPE_ALLOWED_ACTIONS_KEY,
                scope.get(_SCOPE_ALLOWED_ACTIONS_KEY),
            ),
        }
        if capability_scope:
            self._validate_scope_subset(normalized_scope, capability_scope)
        return normalized_scope

    def _validate_scope_subset(
        self,
        scope: Mapping[str, list[str]],
        capability_scope: Mapping[str, Any],
    ) -> None:
        resource_types = capability_scope.get(_SCOPE_RESOURCE_TYPES_KEY)
        if isinstance(resource_types, list) and resource_types:
            allowed_resource_types = {item for item in resource_types if isinstance(item, str)}
            if not set(scope[_SCOPE_RESOURCE_TYPES_KEY]).issubset(allowed_resource_types):
                raise DomainError(
                    ErrorCode.DELEGATION_SCOPE_INVALID,
                    details={"field": _SCOPE_RESOURCE_TYPES_KEY, "http_status": 400},
                )

        allowed_actions = capability_scope.get(_SCOPE_ALLOWED_ACTIONS_KEY)
        if isinstance(allowed_actions, list) and allowed_actions:
            allowed_action_set = {item for item in allowed_actions if isinstance(item, str)}
            if not set(scope[_SCOPE_ALLOWED_ACTIONS_KEY]).issubset(allowed_action_set):
                raise DomainError(
                    ErrorCode.DELEGATION_SCOPE_INVALID,
                    details={"field": _SCOPE_ALLOWED_ACTIONS_KEY, "http_status": 400},
                )

    def _validate_expire_at(
        self,
        expire_at: datetime,
        *,
        current_time: datetime,
    ) -> datetime:
        if (
            not isinstance(expire_at, datetime)
            or expire_at.tzinfo is None
            or expire_at.utcoffset() is None
        ):
            raise DomainError(
                ErrorCode.DELEGATION_EXPIRE_AT_INVALID,
                details={"field": "expire_at", "http_status": 400},
            )
        normalized_expire_at = expire_at.astimezone(timezone.utc)
        if normalized_expire_at <= current_time:
            raise DomainError(
                ErrorCode.DELEGATION_EXPIRE_AT_INVALID,
                details={"field": "expire_at", "http_status": 400},
            )
        return normalized_expire_at

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

    def _is_admin_operator(self, operator_type: OperatorType) -> bool:
        return operator_type in _ADMIN_OPERATORS

    def _to_domain(self, record: DelegationCredentialRecord) -> DelegationCredential:
        return DelegationCredential(
            delegation_id=record.delegation_id,
            user_id=record.user_id,
            agent_id=record.agent_id,
            task_scope=record.task_scope,
            scope=record.scope_json,
            delegation_status=record.delegation_status,
            issued_at=record.issued_at,
            expire_at=record.expire_at,
            revoked_at=record.revoked_at,
            revocation_reason=record.revocation_reason,
            created_at=record.created_at,
            updated_at=record.updated_at,
        )

    def _current_time(self) -> datetime:
        return self.now_provider().astimezone(timezone.utc)

    def _subject_chain(self, user_id: str, agent_id: str) -> str:
        return f"user:{user_id}->agent:{agent_id}"
