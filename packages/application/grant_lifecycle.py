from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import re
from typing import Any, Callable
from uuid import uuid4

from packages.domain import (
    ActorType,
    ApprovalStatus,
    AuditResult,
    DomainError,
    ErrorCode,
    GrantStatus,
    OperatorType,
    RequestStatus,
    TaskStatus,
)
from packages.infrastructure.db.models import (
    AccessGrantRecord,
    AuditRecordRecord,
    NotificationTaskRecord,
    PermissionRequestEventRecord,
    PermissionRequestRecord,
)
from packages.infrastructure.repositories import (
    AccessGrantRepository,
    AuditRecordRepository,
    NotificationTaskRepository,
    PermissionRequestEventRepository,
    PermissionRequestRepository,
)

_REMINDER_TASK_TYPE = "GrantExpirationReminder"
_DURATION_PATTERN = re.compile(r"^P(?:(?P<days>\d+)D)?(?:T(?:(?P<hours>\d+)H)?)?$")
_DEFAULT_REMINDER_LEAD_TIME = timedelta(days=1)
_NOTIFICATION_STATUS_PENDING = "Pending"
_NOTIFICATION_STATUS_RUNNING = "Running"
_NOTIFICATION_STATUS_SUCCEEDED = "Succeeded"
_RENEW_OPERATORS = frozenset(
    {
        OperatorType.USER,
        OperatorType.IT_ADMIN,
        OperatorType.SECURITY_ADMIN,
        OperatorType.SYSTEM,
    }
)
_RENEWAL_COMPLETE_OPERATORS = frozenset(
    {
        OperatorType.IT_ADMIN,
        OperatorType.SECURITY_ADMIN,
        OperatorType.SYSTEM,
    }
)
_RENEWABLE_GRANT_STATUSES = frozenset({GrantStatus.ACTIVE, GrantStatus.EXPIRING})


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _generate_prefixed_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:24]}"


@dataclass(slots=True, frozen=True)
class GrantRenewInput:
    grant_id: str
    requested_duration: str
    reason: str
    api_request_id: str
    operator_user_id: str
    operator_type: OperatorType | str = OperatorType.USER
    trace_id: str | None = None
    idempotency_key: str | None = None


@dataclass(slots=True, frozen=True)
class GrantRenewResult:
    grant_id: str
    renewal_request_id: str
    renew_round: int
    request_status: RequestStatus


@dataclass(slots=True, frozen=True)
class GrantLifecycleProcessResult:
    expiring_count: int
    reminder_count: int
    expired_count: int


@dataclass(slots=True, frozen=True)
class GrantRenewalCompletionResult:
    grant_id: str
    renewal_request_id: str
    request_status: RequestStatus
    grant_status: GrantStatus
    expire_at: datetime


class GrantLifecycleService:
    def __init__(
        self,
        *,
        permission_request_repository: PermissionRequestRepository,
        access_grant_repository: AccessGrantRepository,
        permission_request_event_repository: PermissionRequestEventRepository,
        audit_repository: AuditRecordRepository,
        notification_task_repository: NotificationTaskRepository,
        now_provider: Callable[[], datetime] = _utc_now,
        reminder_lead_time: timedelta = _DEFAULT_REMINDER_LEAD_TIME,
    ) -> None:
        self.permission_request_repository = permission_request_repository
        self.access_grant_repository = access_grant_repository
        self.permission_request_event_repository = permission_request_event_repository
        self.audit_repository = audit_repository
        self.notification_task_repository = notification_task_repository
        self.now_provider = now_provider
        self.reminder_lead_time = reminder_lead_time

    def renew_grant(self, command: GrantRenewInput) -> GrantRenewResult:
        operator_type = self._coerce_operator_type(command.operator_type)
        self._require_renew_operator(operator_type)

        grant_record = self._get_grant_record(command.grant_id)
        source_request = self._get_request_record(grant_record.request_id)
        self._require_request_access(
            request_record=source_request,
            operator_type=operator_type,
            operator_user_id=command.operator_user_id,
        )
        self._require_renewable_grant(grant_record)

        if command.idempotency_key:
            existing_idempotent = self._get_idempotent_renewal_request(
                actor_type=self._to_actor_type(operator_type),
                actor_id=command.operator_user_id,
                idempotency_key=command.idempotency_key,
            )
            if existing_idempotent is not None:
                return self._build_renew_result(existing_idempotent, grant_record.grant_id)

        now = self._current_time()
        requested_duration = self._validate_requested_duration(command.requested_duration)
        normalized_reason = self._validate_reason(command.reason)
        next_round = source_request.renew_round + 1

        existing_round_request = self._find_existing_renewal_request(
            user_id=source_request.user_id,
            grant_id=grant_record.grant_id,
            source_request_id=source_request.request_id,
            renew_round=next_round,
        )
        if existing_round_request is not None:
            return self._build_renew_result(existing_round_request, grant_record.grant_id)

        renewal_context = self._build_renewal_context(
            grant_record=grant_record,
            source_request=source_request,
            requested_duration=requested_duration,
            reason=normalized_reason,
            renew_round=next_round,
        )
        renewal_request = PermissionRequestRecord(
            request_id=_generate_prefixed_id("req"),
            user_id=source_request.user_id,
            agent_id=source_request.agent_id,
            delegation_id=source_request.delegation_id,
            raw_text=normalized_reason,
            resource_key=grant_record.resource_key,
            resource_type=grant_record.resource_type,
            action=grant_record.action,
            constraints_json=deepcopy(source_request.constraints_json),
            requested_duration=requested_duration,
            structured_request_json=self._build_renewal_structured_request(
                source_request=source_request,
                renewal_context=renewal_context,
            ),
            suggested_permission=source_request.suggested_permission,
            risk_level=source_request.risk_level,
            approval_status=ApprovalStatus.PENDING.value,
            grant_status=grant_record.grant_status,
            request_status=RequestStatus.PENDING_APPROVAL.value,
            current_task_state=TaskStatus.PENDING.value,
            policy_version=source_request.policy_version,
            renew_round=next_round,
            failed_reason=None,
            created_at=now,
            updated_at=now,
        )
        self.permission_request_repository.add(renewal_request)
        self._flush_repository(self.permission_request_repository)

        self._record_event(
            request_record=source_request,
            occurred_at=now,
            event_type="grant.renew_requested",
            operator_type=operator_type,
            operator_id=command.operator_user_id,
            from_request_status=source_request.request_status,
            to_request_status=source_request.request_status,
            metadata={
                "api_request_id": command.api_request_id,
                "trace_id": command.trace_id,
                "grant_id": grant_record.grant_id,
                "renewal_request_id": renewal_request.request_id,
                "renew_round": next_round,
                "requested_duration": requested_duration,
            },
        )
        self._record_event(
            request_record=renewal_request,
            occurred_at=now,
            event_type="grant.renew_requested",
            operator_type=operator_type,
            operator_id=command.operator_user_id,
            from_request_status=RequestStatus.DRAFT.value,
            to_request_status=RequestStatus.PENDING_APPROVAL.value,
            metadata={
                "api_request_id": command.api_request_id,
                "trace_id": command.trace_id,
                "grant_id": grant_record.grant_id,
                "source_request_id": source_request.request_id,
                "root_request_id": renewal_context["root_request_id"],
                "renew_round": next_round,
                "requested_duration": requested_duration,
                "previous_expire_at": grant_record.expire_at.isoformat(),
                "idempotency_key": command.idempotency_key,
            },
        )
        self._record_audit(
            request_record=renewal_request,
            created_at=now,
            event_type="grant.renew_requested",
            actor_type=self._to_actor_type(operator_type),
            actor_id=command.operator_user_id,
            result=AuditResult.SUCCESS.value,
            metadata={
                "api_request_id": command.api_request_id,
                "trace_id": command.trace_id,
                "grant_id": grant_record.grant_id,
                "source_request_id": source_request.request_id,
                "root_request_id": renewal_context["root_request_id"],
                "renew_round": next_round,
                "requested_duration": requested_duration,
                "previous_expire_at": grant_record.expire_at.isoformat(),
                "idempotency_key": command.idempotency_key,
                "renewal_request_id": renewal_request.request_id,
            },
        )

        return self._build_renew_result(renewal_request, grant_record.grant_id)

    def process_grant_lifecycle(self) -> GrantLifecycleProcessResult:
        current_time = self._current_time()
        cutoff = current_time + self.reminder_lead_time
        expiring_count, reminder_count = self._mark_expiring_grants(
            current_time=current_time,
            cutoff=cutoff,
        )
        expired_count = self._expire_due_grants(current_time=current_time)
        return GrantLifecycleProcessResult(
            expiring_count=expiring_count,
            reminder_count=reminder_count,
            expired_count=expired_count,
        )

    def complete_approved_renewal(
        self,
        *,
        permission_request_id: str,
        api_request_id: str,
        operator_user_id: str,
        operator_type: OperatorType | str = OperatorType.SYSTEM,
        trace_id: str | None = None,
    ) -> GrantRenewalCompletionResult:
        normalized_operator_type = self._coerce_operator_type(operator_type)
        self._require_renewal_completion_operator(normalized_operator_type)

        renewal_request = self._get_request_record(permission_request_id)
        renewal_context = self.extract_renewal_context(renewal_request)
        if renewal_context is None:
            raise DomainError(
                ErrorCode.REQUEST_STATUS_INVALID,
                message="Permission request is not a renewal request",
                details={"request_id": permission_request_id, "http_status": 409},
            )

        if ApprovalStatus(renewal_request.approval_status) is not ApprovalStatus.APPROVED:
            raise DomainError(
                ErrorCode.REQUEST_STATUS_INVALID,
                message="Renewal requires an approved approval status",
                details={
                    "request_id": permission_request_id,
                    "approval_status": renewal_request.approval_status,
                    "http_status": 409,
                },
            )
        if RequestStatus(renewal_request.request_status) is not RequestStatus.APPROVED:
            raise DomainError(
                ErrorCode.REQUEST_STATUS_INVALID,
                message="Renewal request is not ready to be activated",
                details={
                    "request_id": permission_request_id,
                    "request_status": renewal_request.request_status,
                    "http_status": 409,
                },
            )

        grant_record = self._get_grant_record(renewal_context["grant_id"])
        source_request = self._get_request_record(renewal_context["source_request_id"])
        if grant_record.request_id != source_request.request_id:
            raise DomainError(
                ErrorCode.REQUEST_STATUS_INVALID,
                message="Renewal source request is no longer current for the grant",
                details={
                    "grant_id": grant_record.grant_id,
                    "request_id": renewal_request.request_id,
                    "source_request_id": source_request.request_id,
                    "current_request_id": grant_record.request_id,
                    "http_status": 409,
                },
            )
        self._require_renewable_grant(grant_record)

        now = self._current_time()
        previous_expire_at = grant_record.expire_at
        previous_source_request_status = source_request.request_status
        new_expire_at = previous_expire_at + self._parse_requested_duration(
            renewal_context["requested_duration"]
        )

        source_request.request_status = RequestStatus.EXPIRED.value
        source_request.grant_status = GrantStatus.EXPIRED.value
        source_request.current_task_state = TaskStatus.SUCCEEDED.value
        source_request.updated_at = now

        grant_record.request_id = renewal_request.request_id
        grant_record.grant_status = GrantStatus.ACTIVE.value
        grant_record.expire_at = new_expire_at
        grant_record.updated_at = now

        renewal_request.request_status = RequestStatus.ACTIVE.value
        renewal_request.grant_status = GrantStatus.ACTIVE.value
        renewal_request.current_task_state = TaskStatus.SUCCEEDED.value
        renewal_request.updated_at = now

        self._record_event(
            request_record=source_request,
            occurred_at=now,
            event_type="grant.renewed",
            operator_type=normalized_operator_type,
            operator_id=operator_user_id,
            from_request_status=previous_source_request_status,
            to_request_status=RequestStatus.EXPIRED.value,
            metadata={
                "api_request_id": api_request_id,
                "trace_id": trace_id,
                "grant_id": grant_record.grant_id,
                "renewal_request_id": renewal_request.request_id,
                "new_expire_at": new_expire_at.isoformat(),
            },
        )
        self._record_event(
            request_record=renewal_request,
            occurred_at=now,
            event_type="grant.renewed",
            operator_type=normalized_operator_type,
            operator_id=operator_user_id,
            from_request_status=RequestStatus.APPROVED.value,
            to_request_status=RequestStatus.ACTIVE.value,
            metadata={
                "api_request_id": api_request_id,
                "trace_id": trace_id,
                "grant_id": grant_record.grant_id,
                "source_request_id": source_request.request_id,
                "previous_expire_at": previous_expire_at.isoformat(),
                "new_expire_at": new_expire_at.isoformat(),
                "renew_round": renewal_request.renew_round,
            },
        )
        self._record_audit(
            request_record=renewal_request,
            created_at=now,
            event_type="grant.renewed",
            actor_type=self._to_actor_type(normalized_operator_type),
            actor_id=operator_user_id,
            result=AuditResult.SUCCESS.value,
            metadata={
                "api_request_id": api_request_id,
                "trace_id": trace_id,
                "grant_id": grant_record.grant_id,
                "source_request_id": source_request.request_id,
                "previous_expire_at": previous_expire_at.isoformat(),
                "new_expire_at": new_expire_at.isoformat(),
                "renew_round": renewal_request.renew_round,
            },
        )

        return GrantRenewalCompletionResult(
            grant_id=grant_record.grant_id,
            renewal_request_id=renewal_request.request_id,
            request_status=RequestStatus.ACTIVE,
            grant_status=GrantStatus.ACTIVE,
            expire_at=new_expire_at,
        )

    @staticmethod
    def extract_renewal_context(
        request_record: PermissionRequestRecord,
    ) -> dict[str, str] | None:
        payload = request_record.structured_request_json or {}
        renewal_context = payload.get("renewal_context")
        if not isinstance(renewal_context, dict):
            return None
        required_keys = {
            "grant_id",
            "source_request_id",
            "root_request_id",
            "requested_duration",
        }
        if not required_keys.issubset(renewal_context):
            return None
        normalized: dict[str, str] = {}
        for key in required_keys:
            value = renewal_context.get(key)
            if not isinstance(value, str) or not value.strip():
                return None
            normalized[key] = value.strip()
        return normalized

    def _mark_expiring_grants(
        self,
        *,
        current_time: datetime,
        cutoff: datetime,
    ) -> tuple[int, int]:
        expiring_count = 0
        reminder_count = 0
        grant_records = self.access_grant_repository.list_due_for_expiring(
            current_time=current_time,
            cutoff=cutoff,
        )
        for grant_record in grant_records:
            request_record = self._get_request_record(grant_record.request_id)
            transitioned, reminder_created = self._transition_grant_to_expiring(
                grant_record=grant_record,
                request_record=request_record,
                current_time=current_time,
                create_reminder=True,
            )
            if transitioned:
                expiring_count += 1
            if reminder_created:
                reminder_count += 1
        return expiring_count, reminder_count

    def _expire_due_grants(self, *, current_time: datetime) -> int:
        expired_count = 0
        grant_records = self.access_grant_repository.list_due_for_expiration(
            current_time=current_time,
        )
        for grant_record in grant_records:
            request_record = self._get_request_record(grant_record.request_id)
            current_grant_status = GrantStatus(grant_record.grant_status)
            if current_grant_status is GrantStatus.ACTIVE:
                self._transition_grant_to_expiring(
                    grant_record=grant_record,
                    request_record=request_record,
                    current_time=current_time,
                    create_reminder=False,
                )

            previous_request_status = request_record.request_status
            grant_record.grant_status = GrantStatus.EXPIRED.value
            grant_record.updated_at = current_time

            request_record.request_status = RequestStatus.EXPIRED.value
            request_record.grant_status = GrantStatus.EXPIRED.value
            request_record.current_task_state = TaskStatus.SUCCEEDED.value
            request_record.failed_reason = None
            request_record.updated_at = current_time

            self._record_event(
                request_record=request_record,
                occurred_at=current_time,
                event_type="grant.expired",
                operator_type=OperatorType.SYSTEM,
                operator_id="grant_lifecycle_worker",
                from_request_status=previous_request_status,
                to_request_status=RequestStatus.EXPIRED.value,
                metadata={
                    "grant_id": grant_record.grant_id,
                    "expire_at": grant_record.expire_at.isoformat(),
                    "auto_reclaimed": True,
                },
            )
            self._record_audit(
                request_record=request_record,
                created_at=current_time,
                event_type="grant.expired",
                actor_type=ActorType.SYSTEM,
                actor_id="grant_lifecycle_worker",
                result=AuditResult.SUCCESS.value,
                metadata={
                    "grant_id": grant_record.grant_id,
                    "expire_at": grant_record.expire_at.isoformat(),
                    "auto_reclaimed": True,
                },
            )
            expired_count += 1
        return expired_count

    def _transition_grant_to_expiring(
        self,
        *,
        grant_record: AccessGrantRecord,
        request_record: PermissionRequestRecord,
        current_time: datetime,
        create_reminder: bool,
    ) -> tuple[bool, bool]:
        current_grant_status = GrantStatus(grant_record.grant_status)
        transitioned = False
        reminder_created = False
        reminder_task_id: str | None = None

        if current_grant_status is GrantStatus.ACTIVE:
            previous_request_status = request_record.request_status
            grant_record.grant_status = GrantStatus.EXPIRING.value
            grant_record.updated_at = current_time

            request_record.request_status = RequestStatus.EXPIRING.value
            request_record.grant_status = GrantStatus.EXPIRING.value
            request_record.updated_at = current_time

            if create_reminder:
                reminder_task_id = self._create_expiration_reminder_task(
                    grant_record=grant_record,
                    request_record=request_record,
                    current_time=current_time,
                )
                reminder_created = reminder_task_id is not None

            self._record_event(
                request_record=request_record,
                occurred_at=current_time,
                event_type="grant.expiring",
                operator_type=OperatorType.SYSTEM,
                operator_id="grant_lifecycle_worker",
                from_request_status=previous_request_status,
                to_request_status=RequestStatus.EXPIRING.value,
                metadata={
                    "grant_id": grant_record.grant_id,
                    "expire_at": grant_record.expire_at.isoformat(),
                    "notification_task_id": reminder_task_id,
                },
            )
            transitioned = True
        elif create_reminder:
            reminder_task_id = self._create_expiration_reminder_task(
                grant_record=grant_record,
                request_record=request_record,
                current_time=current_time,
            )
            reminder_created = reminder_task_id is not None

        return transitioned, reminder_created

    def _create_expiration_reminder_task(
        self,
        *,
        grant_record: AccessGrantRecord,
        request_record: PermissionRequestRecord,
        current_time: datetime,
    ) -> str | None:
        for task in self.notification_task_repository.list_for_grant(grant_record.grant_id):
            payload = task.payload_json or {}
            if (
                task.task_type == _REMINDER_TASK_TYPE
                and payload.get("expire_at") == grant_record.expire_at.isoformat()
                and payload.get("renew_round") == request_record.renew_round
                and task.task_status
                in {
                    _NOTIFICATION_STATUS_PENDING,
                    _NOTIFICATION_STATUS_RUNNING,
                    _NOTIFICATION_STATUS_SUCCEEDED,
                }
            ):
                return None

        task = NotificationTaskRecord(
            task_id=_generate_prefixed_id("ntf"),
            grant_id=grant_record.grant_id,
            request_id=request_record.request_id,
            task_type=_REMINDER_TASK_TYPE,
            task_status=_NOTIFICATION_STATUS_PENDING,
            last_error_code=None,
            last_error_message=None,
            payload_json={
                "grant_id": grant_record.grant_id,
                "request_id": request_record.request_id,
                "expire_at": grant_record.expire_at.isoformat(),
                "renew_round": request_record.renew_round,
                "resource_key": grant_record.resource_key,
            },
            scheduled_at=current_time,
            processed_at=None,
            created_at=current_time,
            updated_at=current_time,
        )
        self.notification_task_repository.add(task)
        task.task_status = _NOTIFICATION_STATUS_RUNNING
        task.updated_at = current_time
        task.task_status = _NOTIFICATION_STATUS_SUCCEEDED
        task.processed_at = current_time
        task.updated_at = current_time
        return task.task_id

    def _find_existing_renewal_request(
        self,
        *,
        user_id: str,
        grant_id: str,
        source_request_id: str,
        renew_round: int,
    ) -> PermissionRequestRecord | None:
        for record in self.permission_request_repository.list_for_user(user_id, limit=200):
            if record.renew_round != renew_round:
                continue
            if RequestStatus(record.request_status) is RequestStatus.FAILED:
                continue
            renewal_context = self.extract_renewal_context(record)
            if renewal_context is None:
                continue
            if renewal_context["grant_id"] != grant_id:
                continue
            if renewal_context["source_request_id"] != source_request_id:
                continue
            return record
        return None

    def _get_idempotent_renewal_request(
        self,
        *,
        actor_type: ActorType,
        actor_id: str,
        idempotency_key: str,
    ) -> PermissionRequestRecord | None:
        audit_record = self.audit_repository.get_latest_by_event_and_idempotency_key(
            actor_type=actor_type.value,
            actor_id=actor_id,
            event_type="grant.renew_requested",
            idempotency_key=idempotency_key,
        )
        if audit_record is None:
            return None
        metadata = audit_record.metadata_json or {}
        renewal_request_id = metadata.get("renewal_request_id")
        if not isinstance(renewal_request_id, str) or not renewal_request_id.strip():
            return None
        return self.permission_request_repository.get(renewal_request_id)

    def _build_renewal_context(
        self,
        *,
        grant_record: AccessGrantRecord,
        source_request: PermissionRequestRecord,
        requested_duration: str,
        reason: str,
        renew_round: int,
    ) -> dict[str, object]:
        source_context = self.extract_renewal_context(source_request)
        root_request_id = (
            source_context["root_request_id"]
            if source_context is not None
            else source_request.request_id
        )
        return {
            "grant_id": grant_record.grant_id,
            "source_request_id": source_request.request_id,
            "root_request_id": root_request_id,
            "previous_expire_at": grant_record.expire_at.isoformat(),
            "requested_duration": requested_duration,
            "reason": reason,
            "renew_round": renew_round,
        }

    def _build_renewal_structured_request(
        self,
        *,
        source_request: PermissionRequestRecord,
        renewal_context: dict[str, object],
    ) -> dict[str, object]:
        payload = deepcopy(source_request.structured_request_json or {})
        if not isinstance(payload, dict):
            payload = {}
        payload["renewal_context"] = renewal_context
        payload.setdefault("original_request_id", renewal_context["root_request_id"])
        return payload

    def _build_renew_result(
        self,
        request_record: PermissionRequestRecord,
        grant_id: str,
    ) -> GrantRenewResult:
        return GrantRenewResult(
            grant_id=grant_id,
            renewal_request_id=request_record.request_id,
            renew_round=request_record.renew_round,
            request_status=RequestStatus(request_record.request_status),
        )

    def _get_request_record(self, request_id: str) -> PermissionRequestRecord:
        record = self.permission_request_repository.get(request_id)
        if record is None:
            raise DomainError(
                ErrorCode.REQUEST_STATUS_INVALID,
                message="Permission request was not found",
                details={"request_id": request_id, "http_status": 404},
            )
        return record

    def _get_grant_record(self, grant_id: str) -> AccessGrantRecord:
        record = self.access_grant_repository.get(grant_id)
        if record is None:
            raise DomainError(
                ErrorCode.REQUEST_STATUS_INVALID,
                message="Grant was not found",
                details={"grant_id": grant_id, "http_status": 404},
            )
        return record

    def _validate_reason(self, reason: str) -> str:
        normalized = reason.strip()
        if not normalized:
            raise DomainError(
                ErrorCode.REQUEST_MESSAGE_EMPTY,
                message="Renewal reason is required",
                details={"field": "reason", "http_status": 400},
            )
        return normalized

    def _validate_requested_duration(self, requested_duration: str) -> str:
        normalized = requested_duration.strip()
        try:
            self._parse_requested_duration(normalized)
        except ValueError as exc:
            raise DomainError(
                ErrorCode.REQUEST_STATUS_INVALID,
                message="requested_duration must be a positive ISO-8601 duration such as P7D",
                details={"field": "requested_duration", "http_status": 400},
            ) from exc
        return normalized

    def _parse_requested_duration(self, requested_duration: str) -> timedelta:
        match = _DURATION_PATTERN.fullmatch(requested_duration)
        if match is None:
            raise ValueError("Invalid requested_duration")
        days = int(match.group("days") or 0)
        hours = int(match.group("hours") or 0)
        duration = timedelta(days=days, hours=hours)
        if duration <= timedelta(0):
            raise ValueError("requested_duration must be positive")
        return duration

    def _require_request_access(
        self,
        *,
        request_record: PermissionRequestRecord,
        operator_type: OperatorType,
        operator_user_id: str,
    ) -> None:
        if operator_type in {
            OperatorType.IT_ADMIN,
            OperatorType.SECURITY_ADMIN,
            OperatorType.SYSTEM,
        }:
            return
        if request_record.user_id != operator_user_id:
            raise DomainError(
                ErrorCode.FORBIDDEN,
                details={"request_id": request_record.request_id, "http_status": 403},
            )

    def _require_renew_operator(self, operator_type: OperatorType) -> None:
        if operator_type not in _RENEW_OPERATORS:
            raise DomainError(
                ErrorCode.FORBIDDEN,
                details={"operator_type": operator_type.value, "http_status": 403},
            )

    def _require_renewal_completion_operator(self, operator_type: OperatorType) -> None:
        if operator_type not in _RENEWAL_COMPLETE_OPERATORS:
            raise DomainError(
                ErrorCode.FORBIDDEN,
                details={"operator_type": operator_type.value, "http_status": 403},
            )

    def _require_renewable_grant(self, grant_record: AccessGrantRecord) -> None:
        current_status = GrantStatus(grant_record.grant_status)
        if current_status not in _RENEWABLE_GRANT_STATUSES:
            raise DomainError(
                ErrorCode.REQUEST_STATUS_INVALID,
                message="Current grant status does not allow renewal",
                details={
                    "grant_id": grant_record.grant_id,
                    "grant_status": current_status.value,
                    "http_status": 409,
                },
            )

    def _record_event(
        self,
        *,
        request_record: PermissionRequestRecord,
        occurred_at: datetime,
        event_type: str,
        operator_type: OperatorType,
        operator_id: str,
        from_request_status: str | None,
        to_request_status: str | None,
        metadata: dict[str, object | None],
    ) -> None:
        self.permission_request_event_repository.add(
            PermissionRequestEventRecord(
                event_id=_generate_prefixed_id("evt"),
                request_id=request_record.request_id,
                event_type=event_type,
                operator_type=operator_type.value,
                operator_id=operator_id,
                from_request_status=from_request_status,
                to_request_status=to_request_status,
                metadata_json=self._compact_metadata(metadata),
                occurred_at=occurred_at,
                created_at=occurred_at,
            )
        )

    def _record_audit(
        self,
        *,
        request_record: PermissionRequestRecord,
        created_at: datetime,
        event_type: str,
        actor_type: ActorType,
        actor_id: str,
        result: str,
        metadata: dict[str, object | None],
        reason: str | None = None,
    ) -> None:
        self.audit_repository.add(
            AuditRecordRecord(
                audit_id=_generate_prefixed_id("aud"),
                request_id=request_record.request_id,
                event_type=event_type,
                actor_type=actor_type.value,
                actor_id=actor_id,
                subject_chain=self._subject_chain(request_record),
                result=result,
                reason=reason,
                metadata_json=self._compact_metadata(metadata),
                created_at=created_at,
            )
        )

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

    def _to_actor_type(self, operator_type: OperatorType) -> ActorType:
        return ActorType(operator_type.value)

    def _current_time(self) -> datetime:
        return self.now_provider().astimezone(timezone.utc)

    def _subject_chain(self, request_record: PermissionRequestRecord) -> str:
        return (
            f"user:{request_record.user_id}->"
            f"agent:{request_record.agent_id}->"
            f"request:{request_record.request_id}"
        )

    def _compact_metadata(self, metadata: dict[str, object | None]) -> dict[str, object]:
        return {key: value for key, value in metadata.items() if value is not None}

    def _flush_repository(self, repository: object) -> None:
        session = getattr(repository, "session", None)
        if session is not None:
            session.flush()
