from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable
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
    SessionStatus,
    TaskStatus,
)
from packages.infrastructure.db.models import (
    AccessGrantRecord,
    ApprovalRecordRecord,
    AuditRecordRecord,
    ConnectorTaskRecord,
    PermissionRequestRecord,
    SessionContextRecord,
)
from packages.infrastructure.repositories import (
    AccessGrantRepository,
    ApprovalRecordRepository,
    AuditRecordRepository,
    ConnectorTaskRepository,
    PermissionRequestRepository,
    SessionContextRepository,
)

from ._chain_views import (
    AccessGrantReference,
    ApprovalRecordReference,
    ConnectorTaskReference,
    PermissionRequestReference,
    SessionContextReference,
    build_access_grant_reference,
    build_approval_record_reference,
    build_connector_task_reference,
    build_permission_request_reference,
    build_session_context_reference,
)
from .provisioning import GrantProvisionInput, ProvisioningService
from .session_authority import SessionAuthority, SessionRevokeInput

_APPROVAL_CALLBACK_TASK_TYPE = "approval_callback"
_RETRY_OPERATORS = frozenset({OperatorType.IT_ADMIN, OperatorType.SYSTEM})


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _generate_prefixed_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:24]}"


@dataclass(slots=True, frozen=True)
class FailedTaskQueryInput:
    task_type: str | None = None
    task_status: str | None = None
    request_id: str | None = None
    grant_id: str | None = None
    page: int = 1
    page_size: int = 20


@dataclass(slots=True, frozen=True)
class FailedTaskView:
    task_source: str
    task_id: str
    task_type: str
    task_status: str
    request_id: str
    grant_id: str | None
    global_session_id: str | None
    failure_code: str | None
    failure_reason: str | None
    retryable: bool
    occurred_at: datetime
    request: PermissionRequestReference | None
    grant: AccessGrantReference | None
    connector_task: ConnectorTaskReference | None
    session_context: SessionContextReference | None
    approval_record: ApprovalRecordReference | None


@dataclass(slots=True, frozen=True)
class FailedTaskQueryResult:
    items: list[FailedTaskView]
    page: int
    page_size: int
    total: int


@dataclass(slots=True, frozen=True)
class RetryConnectorTaskInput:
    task_id: str
    reason: str
    api_request_id: str
    operator_user_id: str
    operator_type: OperatorType | str = OperatorType.IT_ADMIN
    trace_id: str | None = None


@dataclass(slots=True, frozen=True)
class RetryConnectorTaskResult:
    original_task_id: str
    retry_task_id: str | None
    task_type: str
    task_status: str
    request_id: str
    grant_id: str
    global_session_id: str | None
    request_status: str
    grant_status: str
    session_status: str | None


class FailedTaskService:
    def __init__(
        self,
        *,
        permission_request_repository: PermissionRequestRepository,
        access_grant_repository: AccessGrantRepository,
        connector_task_repository: ConnectorTaskRepository,
        session_context_repository: SessionContextRepository,
        approval_record_repository: ApprovalRecordRepository,
        audit_repository: AuditRecordRepository,
        provisioning_service: ProvisioningService,
        session_authority: SessionAuthority,
        now_provider: Callable[[], datetime] = _utc_now,
    ) -> None:
        self.permission_request_repository = permission_request_repository
        self.access_grant_repository = access_grant_repository
        self.connector_task_repository = connector_task_repository
        self.session_context_repository = session_context_repository
        self.approval_record_repository = approval_record_repository
        self.audit_repository = audit_repository
        self.provisioning_service = provisioning_service
        self.session_authority = session_authority
        self.now_provider = now_provider

    def list_failed_tasks(self, command: FailedTaskQueryInput) -> FailedTaskQueryResult:
        connector_items = self._load_failed_connector_items(command)
        approval_items = self._load_failed_approval_items(command)
        items = connector_items + approval_items
        items.sort(key=lambda item: item.occurred_at, reverse=True)

        total = len(items)
        start = (command.page - 1) * command.page_size
        end = start + command.page_size
        return FailedTaskQueryResult(
            items=items[start:end],
            page=command.page,
            page_size=command.page_size,
            total=total,
        )

    def retry_connector_task(self, command: RetryConnectorTaskInput) -> RetryConnectorTaskResult:
        operator_type = self._coerce_operator_type(command.operator_type)
        self._require_retry_operator(operator_type)
        normalized_reason = self._normalize_reason(command.reason)

        task = self.connector_task_repository.get(command.task_id)
        if task is None:
            raise DomainError(
                ErrorCode.REQUEST_STATUS_INVALID,
                message="Connector task was not found",
                details={"task_id": command.task_id, "http_status": 404},
            )

        request_record = self._get_request_record(task.request_id)
        grant_record = self._get_grant_record(task.grant_id)

        if task.task_type == "provision":
            denial_reason = self._get_provision_retry_denial_reason(
                task=task,
                request_record=request_record,
                grant_record=grant_record,
            )
            if denial_reason is not None:
                self._record_retry_audit(
                    request_record=request_record,
                    operator_type=operator_type,
                    operator_id=command.operator_user_id,
                    result=AuditResult.DENIED.value,
                    reason=denial_reason,
                    task=task,
                    api_request_id=command.api_request_id,
                    trace_id=command.trace_id,
                    global_session_id=None,
                )
                raise DomainError(
                    ErrorCode.RETRY_NOT_ALLOWED,
                    message=denial_reason,
                    details={"task_id": task.task_id, "grant_id": task.grant_id, "http_status": 409},
                )
            self._record_retry_audit(
                request_record=request_record,
                operator_type=operator_type,
                operator_id=command.operator_user_id,
                result=AuditResult.SUCCESS.value,
                reason=normalized_reason,
                task=task,
                api_request_id=command.api_request_id,
                trace_id=command.trace_id,
                global_session_id=None,
            )
            result = self.provisioning_service.provision_grant(
                GrantProvisionInput(
                    grant_id=task.grant_id,
                    permission_request_id=task.request_id,
                    policy_version=request_record.policy_version or "",
                    delegation_id=request_record.delegation_id,
                    api_request_id=command.api_request_id,
                    operator_user_id=command.operator_user_id,
                    operator_type=operator_type,
                    force_retry=True,
                    trace_id=command.trace_id,
                )
            )
            retry_task_id = result.connector_task_id
            retry_task = (
                self.connector_task_repository.get(retry_task_id)
                if isinstance(retry_task_id, str) and retry_task_id
                else None
            )
            current_request = self._get_request_record(task.request_id)
            current_grant = self._get_grant_record(task.grant_id)
            return RetryConnectorTaskResult(
                original_task_id=task.task_id,
                retry_task_id=retry_task_id,
                task_type=task.task_type,
                task_status=retry_task.task_status if retry_task is not None else task.task_status,
                request_id=current_request.request_id,
                grant_id=current_grant.grant_id,
                global_session_id=None,
                request_status=current_request.request_status,
                grant_status=current_grant.grant_status,
                session_status=None,
            )

        if task.task_type == "session_revoke":
            global_session_id = self._require_global_session_id(task)
            session_record = self._get_session_record(global_session_id)
            denial_reason = self._get_session_retry_denial_reason(
                task=task,
                session_record=session_record,
            )
            if denial_reason is not None:
                self._record_retry_audit(
                    request_record=request_record,
                    operator_type=operator_type,
                    operator_id=command.operator_user_id,
                    result=AuditResult.DENIED.value,
                    reason=denial_reason,
                    task=task,
                    api_request_id=command.api_request_id,
                    trace_id=command.trace_id,
                    global_session_id=global_session_id,
                )
                raise DomainError(
                    ErrorCode.RETRY_NOT_ALLOWED,
                    message=denial_reason,
                    details={"task_id": task.task_id, "grant_id": task.grant_id, "http_status": 409},
                )
            self._record_retry_audit(
                request_record=request_record,
                operator_type=operator_type,
                operator_id=command.operator_user_id,
                result=AuditResult.SUCCESS.value,
                reason=normalized_reason,
                task=task,
                api_request_id=command.api_request_id,
                trace_id=command.trace_id,
                global_session_id=global_session_id,
            )
            requested = self.session_authority.request_session_revoke(
                SessionRevokeInput(
                    global_session_id=global_session_id,
                    reason=normalized_reason,
                    cascade_connector_sessions=bool((task.payload_json or {}).get("cascade_connector_sessions", True)),
                    api_request_id=command.api_request_id,
                    operator_user_id=command.operator_user_id,
                    operator_type=operator_type,
                    trace_id=command.trace_id,
                    trigger_source="ManualRetry",
                )
            )
            retry_task_id = requested.revoke_task_id
            if retry_task_id is None:
                raise DomainError(
                    ErrorCode.RETRY_NOT_ALLOWED,
                    message="Retry task was not created for the requested session revoke",
                    details={"task_id": task.task_id, "http_status": 409},
                )
            self.session_authority.process_session_revoke_task(retry_task_id)
            retry_task = self.connector_task_repository.get(retry_task_id)
            current_request = self._get_request_record(task.request_id)
            current_grant = self._get_grant_record(task.grant_id)
            current_session = self._get_session_record(global_session_id)
            return RetryConnectorTaskResult(
                original_task_id=task.task_id,
                retry_task_id=retry_task_id,
                task_type=task.task_type,
                task_status=retry_task.task_status if retry_task is not None else task.task_status,
                request_id=current_request.request_id,
                grant_id=current_grant.grant_id,
                global_session_id=global_session_id,
                request_status=current_request.request_status,
                grant_status=current_grant.grant_status,
                session_status=current_session.session_status,
            )

        raise DomainError(
            ErrorCode.RETRY_NOT_ALLOWED,
            message="Current connector task type does not support retry",
            details={"task_id": task.task_id, "task_type": task.task_type, "http_status": 409},
        )

    def _load_failed_connector_items(self, command: FailedTaskQueryInput) -> list[FailedTaskView]:
        if command.task_type == _APPROVAL_CALLBACK_TASK_TYPE:
            return []

        records = self.connector_task_repository.list_failed(
            task_type=command.task_type,
            task_status=command.task_status,
            request_id=command.request_id,
            grant_id=command.grant_id,
        )
        if not records:
            return []

        request_ids = {record.request_id for record in records}
        grant_ids = {record.grant_id for record in records}
        requests_by_id = {
            record.request_id: record
            for record in self.permission_request_repository.list_by_ids(request_ids)
        }
        grants_by_id = {
            record.grant_id: record
            for record in self.access_grant_repository.list_by_ids(grant_ids)
        }
        sessions_by_grant = {
            record.grant_id: record
            for record in self.session_context_repository.list_by_grant_ids(grant_ids)
        }

        items: list[FailedTaskView] = []
        for record in records:
            request_record = requests_by_id.get(record.request_id)
            grant_record = grants_by_id.get(record.grant_id)
            session_record = sessions_by_grant.get(record.grant_id)
            global_session_id = self._extract_global_session_id(record)
            retryable = self._is_connector_task_retryable(
                task=record,
                request_record=request_record,
                grant_record=grant_record,
                session_record=session_record,
            )
            items.append(
                FailedTaskView(
                    task_source="connector_task",
                    task_id=record.task_id,
                    task_type=record.task_type,
                    task_status=record.task_status,
                    request_id=record.request_id,
                    grant_id=record.grant_id,
                    global_session_id=global_session_id,
                    failure_code=record.last_error_code,
                    failure_reason=record.last_error_message,
                    retryable=retryable,
                    occurred_at=record.processed_at or record.updated_at,
                    request=build_permission_request_reference(request_record),
                    grant=build_access_grant_reference(grant_record),
                    connector_task=build_connector_task_reference(record),
                    session_context=build_session_context_reference(session_record),
                    approval_record=None,
                )
            )
        return items

    def _load_failed_approval_items(self, command: FailedTaskQueryInput) -> list[FailedTaskView]:
        if command.task_type not in {None, _APPROVAL_CALLBACK_TASK_TYPE}:
            return []
        if command.task_status not in {None, ApprovalStatus.CALLBACK_FAILED.value}:
            return []

        records = self.approval_record_repository.list_callback_failed(request_id=command.request_id)
        if not records:
            return []

        request_ids = {record.request_id for record in records}
        requests_by_id = {
            record.request_id: record
            for record in self.permission_request_repository.list_by_ids(request_ids)
        }
        grants_by_request = self._first_grant_by_request(
            self.access_grant_repository.list_for_requests(request_ids)
        )

        items: list[FailedTaskView] = []
        for record in records:
            request_record = requests_by_id.get(record.request_id)
            grant_record = grants_by_request.get(record.request_id)
            if command.grant_id is not None and (
                grant_record is None or grant_record.grant_id != command.grant_id
            ):
                continue
            items.append(
                FailedTaskView(
                    task_source="approval_record",
                    task_id=record.approval_id,
                    task_type=_APPROVAL_CALLBACK_TASK_TYPE,
                    task_status=record.approval_status,
                    request_id=record.request_id,
                    grant_id=grant_record.grant_id if grant_record is not None else None,
                    global_session_id=None,
                    failure_code=None,
                    failure_reason=(
                        request_record.failed_reason
                        if request_record is not None
                        else None
                    ),
                    retryable=False,
                    occurred_at=record.updated_at,
                    request=build_permission_request_reference(request_record),
                    grant=build_access_grant_reference(grant_record),
                    connector_task=None,
                    session_context=None,
                    approval_record=build_approval_record_reference(record),
                )
            )
        return items

    def _is_connector_task_retryable(
        self,
        *,
        task: ConnectorTaskRecord,
        request_record: PermissionRequestRecord | None,
        grant_record: AccessGrantRecord | None,
        session_record: SessionContextRecord | None,
    ) -> bool:
        if task.task_status != TaskStatus.FAILED.value or task.retry_count >= task.max_retry_count:
            return False
        if task.task_type == "provision":
            latest_task = self.connector_task_repository.get_latest_for_grant(task.grant_id)
            if latest_task is None or latest_task.task_id != task.task_id:
                return False
            if request_record is None or grant_record is None:
                return False
            return (
                request_record.request_status == RequestStatus.FAILED.value
                and grant_record.grant_status == GrantStatus.PROVISION_FAILED.value
            )
        if task.task_type == "session_revoke":
            global_session_id = self._extract_global_session_id(task)
            if global_session_id is None or session_record is None:
                return False
            latest_task = self.connector_task_repository.get_latest_session_revoke_for_session(
                global_session_id=global_session_id
            )
            if latest_task is None or latest_task.task_id != task.task_id:
                return False
            return session_record.session_status == SessionStatus.SYNC_FAILED.value
        return False

    def _get_provision_retry_denial_reason(
        self,
        *,
        task: ConnectorTaskRecord,
        request_record: PermissionRequestRecord,
        grant_record: AccessGrantRecord,
    ) -> str | None:
        latest_task = self.connector_task_repository.get_latest_for_grant(task.grant_id)
        if task.task_status != TaskStatus.FAILED.value:
            return "Only failed provision tasks can be retried"
        if latest_task is None or latest_task.task_id != task.task_id:
            return "Only the latest failed provision task can be retried"
        if request_record.request_status != RequestStatus.FAILED.value:
            return "Permission request is not in Failed state"
        if grant_record.grant_status != GrantStatus.PROVISION_FAILED.value:
            return "Grant is not in ProvisionFailed state"
        if task.retry_count >= task.max_retry_count:
            return "Provision task has exhausted the configured retry count"
        return None

    def _get_session_retry_denial_reason(
        self,
        *,
        task: ConnectorTaskRecord,
        session_record: SessionContextRecord,
    ) -> str | None:
        global_session_id = self._extract_global_session_id(task)
        latest_task = (
            self.connector_task_repository.get_latest_session_revoke_for_session(
                global_session_id=global_session_id
            )
            if global_session_id is not None
            else None
        )
        if task.task_status != TaskStatus.FAILED.value:
            return "Only failed session revoke tasks can be retried"
        if global_session_id is None:
            return "Session revoke task payload is missing global_session_id"
        if latest_task is None or latest_task.task_id != task.task_id:
            return "Only the latest failed session revoke task can be retried"
        if session_record.session_status != SessionStatus.SYNC_FAILED.value:
            return "Session is not in SyncFailed state"
        if task.retry_count >= task.max_retry_count:
            return "Session revoke task has exhausted the configured retry count"
        return None

    def _record_retry_audit(
        self,
        *,
        request_record: PermissionRequestRecord,
        operator_type: OperatorType,
        operator_id: str,
        result: str,
        reason: str,
        task: ConnectorTaskRecord,
        api_request_id: str,
        trace_id: str | None,
        global_session_id: str | None,
    ) -> None:
        self.audit_repository.add(
            AuditRecordRecord(
                audit_id=_generate_prefixed_id("aud"),
                request_id=request_record.request_id,
                event_type="connector.retry_requested",
                actor_type=ActorType(operator_type.value).value,
                actor_id=operator_id,
                subject_chain=self._subject_chain(
                    request_record=request_record,
                    global_session_id=global_session_id,
                ),
                result=result,
                reason=reason,
                metadata_json={
                    "api_request_id": api_request_id,
                    "trace_id": trace_id,
                    "original_task_id": task.task_id,
                    "task_type": task.task_type,
                    "grant_id": task.grant_id,
                    "retry_count": task.retry_count,
                    "max_retry_count": task.max_retry_count,
                    "retry_reason": reason,
                    "global_session_id": global_session_id,
                },
                created_at=self._current_time(),
            )
        )

    def _extract_global_session_id(self, task: ConnectorTaskRecord) -> str | None:
        payload = dict(task.payload_json or {})
        value = payload.get("global_session_id")
        if not isinstance(value, str):
            return None
        normalized = value.strip()
        return normalized or None

    def _require_global_session_id(self, task: ConnectorTaskRecord) -> str:
        global_session_id = self._extract_global_session_id(task)
        if global_session_id is not None:
            return global_session_id
        raise DomainError(
            ErrorCode.REQUEST_STATUS_INVALID,
            message="Session revoke task payload is missing global_session_id",
            details={"task_id": task.task_id, "http_status": 409},
        )

    def _normalize_reason(self, reason: str) -> str:
        normalized = (reason or "").strip()
        if not normalized:
            raise DomainError(
                ErrorCode.REQUEST_MESSAGE_EMPTY,
                message="Retry reason is required",
                details={"field": "reason", "http_status": 400},
            )
        return normalized[:256]

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

    def _require_retry_operator(self, operator_type: OperatorType) -> None:
        if operator_type in _RETRY_OPERATORS:
            return
        raise DomainError(
            ErrorCode.FORBIDDEN,
            message="Operator is not allowed to retry connector tasks",
            details={"operator_type": operator_type.value, "http_status": 403},
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
                message="Access grant was not found",
                details={"grant_id": grant_id, "http_status": 404},
            )
        return record

    def _get_session_record(self, global_session_id: str) -> SessionContextRecord:
        record = self.session_context_repository.get(global_session_id)
        if record is None:
            raise DomainError(
                ErrorCode.REQUEST_STATUS_INVALID,
                message="Session context was not found",
                details={"global_session_id": global_session_id, "http_status": 404},
            )
        return record

    def _current_time(self) -> datetime:
        return self.now_provider().astimezone(timezone.utc)

    def _first_grant_by_request(
        self,
        records: list[AccessGrantRecord],
    ) -> dict[str, AccessGrantRecord]:
        items: dict[str, AccessGrantRecord] = {}
        for record in records:
            items.setdefault(record.request_id, record)
        return items

    def _subject_chain(
        self,
        *,
        request_record: PermissionRequestRecord,
        global_session_id: str | None,
    ) -> str:
        base_chain = (
            f"user:{request_record.user_id}->"
            f"agent:{request_record.agent_id}->"
            f"request:{request_record.request_id}"
        )
        if global_session_id is None:
            return base_chain
        return f"{base_chain}->session:{global_session_id}"
