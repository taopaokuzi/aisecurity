from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable
from uuid import uuid4

from packages.domain import (
    ActorType,
    ApprovalStatus,
    AuditResult,
    ConnectorStatus,
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
    ConnectorTaskRecord,
    PermissionRequestEventRecord,
    PermissionRequestRecord,
)
from packages.infrastructure.feishu_connector import (
    ConnectorProvisionCommand,
    ConnectorProvisionResponse,
    ConnectorUnavailableError,
    FeishuPermissionConnector,
)
from packages.infrastructure.repositories import (
    AccessGrantRepository,
    AuditRecordRepository,
    ConnectorTaskRepository,
    PermissionRequestEventRepository,
    PermissionRequestRepository,
)

_PROVISION_OPERATORS = frozenset(
    {
        OperatorType.SYSTEM,
        OperatorType.IT_ADMIN,
        OperatorType.SECURITY_ADMIN,
    }
)
_DEFAULT_MAX_RETRY_COUNT = 3
_DEFAULT_DURATION = timedelta(days=7)
_RECONCILE_PENDING = "PendingDispatch"
_RECONCILE_AWAITING = "AwaitingConfirmation"
_RECONCILE_CONFIRMED = "Confirmed"
_RECONCILE_ERROR = "Error"
_SUPPORTED_RESOURCE_TYPES = frozenset({"doc", "report"})
_SUPPORTED_ACTIONS = frozenset({"read"})


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _generate_prefixed_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:24]}"


def default_grant_id_for_request(permission_request_id: str) -> str:
    normalized = permission_request_id.strip()
    if not normalized:
        raise ValueError("permission_request_id must not be empty")
    digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()[:24]
    return f"grt_{digest}"


@dataclass(slots=True, frozen=True)
class GrantProvisionInput:
    grant_id: str
    permission_request_id: str
    policy_version: str
    delegation_id: str
    api_request_id: str
    operator_user_id: str
    operator_type: OperatorType | str = OperatorType.SYSTEM
    force_retry: bool = False
    trace_id: str | None = None


@dataclass(slots=True, frozen=True)
class GrantProvisionResult:
    grant_id: str
    request_id: str
    grant_status: GrantStatus
    connector_status: ConnectorStatus
    request_status: RequestStatus
    connector_task_id: str | None
    connector_task_status: TaskStatus | None
    effective_at: datetime | None
    retry_count: int = 0


class ProvisioningService:
    def __init__(
        self,
        *,
        permission_request_repository: PermissionRequestRepository,
        access_grant_repository: AccessGrantRepository,
        connector_task_repository: ConnectorTaskRepository,
        permission_request_event_repository: PermissionRequestEventRepository,
        audit_repository: AuditRecordRepository,
        connector: FeishuPermissionConnector,
        now_provider: Callable[[], datetime] = _utc_now,
        max_retry_count: int = _DEFAULT_MAX_RETRY_COUNT,
    ) -> None:
        self.permission_request_repository = permission_request_repository
        self.access_grant_repository = access_grant_repository
        self.connector_task_repository = connector_task_repository
        self.permission_request_event_repository = permission_request_event_repository
        self.audit_repository = audit_repository
        self.connector = connector
        self.now_provider = now_provider
        self.max_retry_count = max_retry_count

    def provision_grant(self, command: GrantProvisionInput) -> GrantProvisionResult:
        operator_type = self._coerce_operator_type(command.operator_type)
        self._require_operator(operator_type)

        request_record = self._get_request_record(command.permission_request_id)
        self._recheck_policy(request_record=request_record, command=command)

        grant_record = self.access_grant_repository.get(command.grant_id)
        existing_request_grant = self.access_grant_repository.get_by_request_id(request_record.request_id)
        if existing_request_grant is not None and existing_request_grant.grant_id != command.grant_id:
            raise DomainError(
                ErrorCode.REQUEST_STATUS_INVALID,
                message="Permission request already has a different grant record",
                details={
                    "request_id": request_record.request_id,
                    "grant_id": existing_request_grant.grant_id,
                    "http_status": 409,
                },
            )

        latest_task = self.connector_task_repository.get_latest_for_grant(command.grant_id)
        if grant_record is not None:
            if grant_record.request_id != request_record.request_id:
                raise DomainError(
                    ErrorCode.REQUEST_STATUS_INVALID,
                    message="Grant does not belong to the supplied permission request",
                    details={
                        "grant_id": command.grant_id,
                        "request_id": request_record.request_id,
                        "http_status": 409,
                    },
                )
            current_grant_status = GrantStatus(grant_record.grant_status)
            if current_grant_status is GrantStatus.ACTIVE:
                raise DomainError(
                    ErrorCode.GRANT_ALREADY_ACTIVE,
                    details={
                        "grant_id": grant_record.grant_id,
                        "request_id": request_record.request_id,
                        "http_status": 409,
                    },
                )
            if current_grant_status in {
                GrantStatus.PROVISIONING_REQUESTED,
                GrantStatus.PROVISIONING,
            }:
                return self._build_result(request_record, grant_record, latest_task)
            if current_grant_status is GrantStatus.PROVISION_FAILED:
                if not command.force_retry:
                    raise DomainError(
                        ErrorCode.RETRY_NOT_ALLOWED,
                        message="Retry requires force_retry=true when the latest provisioning attempt failed",
                        details={
                            "grant_id": grant_record.grant_id,
                            "request_id": request_record.request_id,
                            "http_status": 409,
                        },
                    )
            else:
                raise DomainError(
                    ErrorCode.REQUEST_STATUS_INVALID,
                    message="Current grant status does not allow provisioning",
                    details={
                        "grant_id": grant_record.grant_id,
                        "grant_status": current_grant_status.value,
                        "http_status": 409,
                    },
                )
        else:
            self._require_approved_request_for_initial_provision(request_record)
            grant_record = self._create_grant_record(request_record=request_record, grant_id=command.grant_id)
            self.access_grant_repository.add(grant_record)
            latest_task = None

        if command.force_retry:
            self._require_retryable_state(request_record=request_record, grant_record=grant_record, latest_task=latest_task)

        task = self._create_connector_task(
            request_record=request_record,
            grant_record=grant_record,
            latest_task=latest_task,
            force_retry=command.force_retry,
        )
        self.connector_task_repository.add(task)
        self._flush_repository(self.connector_task_repository)

        started_at = self._current_time()
        previous_request_status = request_record.request_status
        request_record.request_status = RequestStatus.PROVISIONING.value
        request_record.grant_status = GrantStatus.PROVISIONING.value
        request_record.current_task_state = TaskStatus.RUNNING.value
        request_record.failed_reason = None
        request_record.updated_at = started_at

        grant_record.grant_status = GrantStatus.PROVISIONING.value
        grant_record.updated_at = started_at
        grant_record.reconcile_status = (
            _RECONCILE_AWAITING if command.force_retry else _RECONCILE_PENDING
        )

        task.task_status = TaskStatus.RUNNING.value
        task.updated_at = started_at

        if command.force_retry:
            self._record_event(
                request_record=request_record,
                occurred_at=started_at,
                event_type="grant.retry_requested",
                operator_type=operator_type,
                operator_id=command.operator_user_id,
                from_request_status=previous_request_status,
                to_request_status=RequestStatus.PROVISIONING.value,
                metadata={
                    "api_request_id": command.api_request_id,
                    "trace_id": command.trace_id,
                    "grant_id": grant_record.grant_id,
                    "task_id": task.task_id,
                    "retry_count": task.retry_count,
                },
            )
            self._record_audit(
                request_record=request_record,
                created_at=started_at,
                event_type="grant.retry_requested",
                actor_type=self._to_actor_type(operator_type),
                actor_id=command.operator_user_id,
                result=AuditResult.SUCCESS.value,
                metadata={
                    "api_request_id": command.api_request_id,
                    "trace_id": command.trace_id,
                    "grant_id": grant_record.grant_id,
                    "task_id": task.task_id,
                    "retry_count": task.retry_count,
                },
            )

        self._record_event(
            request_record=request_record,
            occurred_at=started_at,
            event_type="grant.provisioning_requested",
            operator_type=operator_type,
            operator_id=command.operator_user_id,
            from_request_status=previous_request_status,
            to_request_status=RequestStatus.PROVISIONING.value,
            metadata={
                "api_request_id": command.api_request_id,
                "trace_id": command.trace_id,
                "grant_id": grant_record.grant_id,
                "task_id": task.task_id,
                "retry_count": task.retry_count,
                "force_retry": command.force_retry,
            },
        )
        self._record_audit(
            request_record=request_record,
            created_at=started_at,
            event_type="grant.provisioning_requested",
            actor_type=self._to_actor_type(operator_type),
            actor_id=command.operator_user_id,
            result=AuditResult.SUCCESS.value,
            metadata={
                "api_request_id": command.api_request_id,
                "trace_id": command.trace_id,
                "grant_id": grant_record.grant_id,
                "task_id": task.task_id,
                "retry_count": task.retry_count,
                "force_retry": command.force_retry,
            },
        )

        try:
            response = self.connector.provision_access(
                ConnectorProvisionCommand(
                    request_id=request_record.request_id,
                    grant_id=grant_record.grant_id,
                    delegation_id=command.delegation_id,
                    policy_version=command.policy_version,
                    resource_key=grant_record.resource_key,
                    resource_type=grant_record.resource_type,
                    action=grant_record.action,
                    expire_at=grant_record.expire_at,
                    api_request_id=command.api_request_id,
                    trace_id=command.trace_id,
                )
            )
        except ConnectorUnavailableError as exc:
            finished_at = self._current_time()
            self._mark_connector_unavailable(
                request_record=request_record,
                grant_record=grant_record,
                task=task,
                operator_type=operator_type,
                operator_id=command.operator_user_id,
                api_request_id=command.api_request_id,
                trace_id=command.trace_id,
                reason=str(exc),
                occurred_at=finished_at,
            )
            raise DomainError(
                ErrorCode.CONNECTOR_UNAVAILABLE,
                details={
                    "grant_id": grant_record.grant_id,
                    "request_id": request_record.request_id,
                    "http_status": 503,
                },
            ) from exc

        finished_at = self._current_time()
        self._apply_connector_response(
            request_record=request_record,
            grant_record=grant_record,
            task=task,
            response=response,
            operator_type=operator_type,
            operator_id=command.operator_user_id,
            api_request_id=command.api_request_id,
            trace_id=command.trace_id,
            occurred_at=finished_at,
        )
        return self._build_result(request_record, grant_record, task)

    def _apply_connector_response(
        self,
        *,
        request_record: PermissionRequestRecord,
        grant_record: AccessGrantRecord,
        task: ConnectorTaskRecord,
        response: ConnectorProvisionResponse,
        operator_type: OperatorType,
        operator_id: str,
        api_request_id: str,
        trace_id: str | None,
        occurred_at: datetime,
    ) -> None:
        task.processed_at = occurred_at
        task.updated_at = occurred_at
        task.payload_json = self._build_task_payload(task=task, response=response)

        event_metadata = {
            "api_request_id": api_request_id,
            "trace_id": trace_id,
            "grant_id": grant_record.grant_id,
            "task_id": task.task_id,
            "retry_count": task.retry_count,
            "provider_request_id": response.provider_request_id,
            "provider_task_id": response.provider_task_id,
        }

        if response.connector_status is ConnectorStatus.ACCEPTED:
            grant_record.grant_status = GrantStatus.PROVISIONING.value
            grant_record.connector_status = ConnectorStatus.ACCEPTED.value
            grant_record.reconcile_status = _RECONCILE_AWAITING
            grant_record.effective_at = None
            grant_record.updated_at = occurred_at

            request_record.grant_status = GrantStatus.PROVISIONING.value
            request_record.request_status = RequestStatus.PROVISIONING.value
            request_record.current_task_state = TaskStatus.SUCCEEDED.value
            request_record.failed_reason = None
            request_record.updated_at = occurred_at

            task.task_status = TaskStatus.SUCCEEDED.value
            task.last_error_code = None
            task.last_error_message = None

            self._record_event(
                request_record=request_record,
                occurred_at=occurred_at,
                event_type="grant.accepted",
                operator_type=operator_type,
                operator_id=operator_id,
                from_request_status=RequestStatus.PROVISIONING.value,
                to_request_status=RequestStatus.PROVISIONING.value,
                metadata=event_metadata,
            )
            self._record_audit(
                request_record=request_record,
                created_at=occurred_at,
                event_type="grant.accepted",
                actor_type=self._to_actor_type(operator_type),
                actor_id=operator_id,
                result=AuditResult.SUCCESS.value,
                metadata=event_metadata,
            )
            return

        if response.connector_status is ConnectorStatus.APPLIED:
            effective_at = response.effective_at or occurred_at
            grant_record.grant_status = GrantStatus.ACTIVE.value
            grant_record.connector_status = ConnectorStatus.APPLIED.value
            grant_record.reconcile_status = _RECONCILE_CONFIRMED
            grant_record.effective_at = effective_at
            grant_record.updated_at = occurred_at

            request_record.grant_status = GrantStatus.ACTIVE.value
            request_record.request_status = RequestStatus.ACTIVE.value
            request_record.current_task_state = TaskStatus.SUCCEEDED.value
            request_record.failed_reason = None
            request_record.updated_at = occurred_at

            task.task_status = TaskStatus.SUCCEEDED.value
            task.last_error_code = None
            task.last_error_message = None

            self._record_event(
                request_record=request_record,
                occurred_at=occurred_at,
                event_type="grant.provisioned",
                operator_type=operator_type,
                operator_id=operator_id,
                from_request_status=RequestStatus.PROVISIONING.value,
                to_request_status=RequestStatus.ACTIVE.value,
                metadata=event_metadata | {"effective_at": effective_at.isoformat().replace("+00:00", "Z")},
            )
            self._record_audit(
                request_record=request_record,
                created_at=occurred_at,
                event_type="grant.provisioned",
                actor_type=self._to_actor_type(operator_type),
                actor_id=operator_id,
                result=AuditResult.SUCCESS.value,
                metadata=event_metadata | {"effective_at": effective_at.isoformat().replace("+00:00", "Z")},
            )
            return

        self._mark_provision_failure(
            request_record=request_record,
            grant_record=grant_record,
            task=task,
            operator_type=operator_type,
            operator_id=operator_id,
            api_request_id=api_request_id,
            trace_id=trace_id,
            error_code=response.error_code or "CONNECTOR_FAILED",
            error_message=response.error_message or "Provisioning failed",
            connector_status=response.connector_status,
            provider_request_id=response.provider_request_id,
            provider_task_id=response.provider_task_id,
            occurred_at=occurred_at,
        )

    def _mark_connector_unavailable(
        self,
        *,
        request_record: PermissionRequestRecord,
        grant_record: AccessGrantRecord,
        task: ConnectorTaskRecord,
        operator_type: OperatorType,
        operator_id: str,
        api_request_id: str,
        trace_id: str | None,
        reason: str,
        occurred_at: datetime,
    ) -> None:
        self._mark_provision_failure(
            request_record=request_record,
            grant_record=grant_record,
            task=task,
            operator_type=operator_type,
            operator_id=operator_id,
            api_request_id=api_request_id,
            trace_id=trace_id,
            error_code="CONNECTOR_UNAVAILABLE",
            error_message=reason or "Connector unavailable",
            connector_status=ConnectorStatus.FAILED,
            provider_request_id=None,
            provider_task_id=None,
            occurred_at=occurred_at,
        )

    def _mark_provision_failure(
        self,
        *,
        request_record: PermissionRequestRecord,
        grant_record: AccessGrantRecord,
        task: ConnectorTaskRecord,
        operator_type: OperatorType,
        operator_id: str,
        api_request_id: str,
        trace_id: str | None,
        error_code: str,
        error_message: str,
        connector_status: ConnectorStatus,
        provider_request_id: str | None,
        provider_task_id: str | None,
        occurred_at: datetime,
    ) -> None:
        normalized_reason = error_message[:256]
        grant_record.grant_status = GrantStatus.PROVISION_FAILED.value
        grant_record.connector_status = connector_status.value
        grant_record.reconcile_status = _RECONCILE_ERROR
        grant_record.effective_at = None
        grant_record.updated_at = occurred_at

        request_record.grant_status = GrantStatus.PROVISION_FAILED.value
        request_record.request_status = RequestStatus.FAILED.value
        request_record.current_task_state = TaskStatus.FAILED.value
        request_record.failed_reason = normalized_reason
        request_record.updated_at = occurred_at

        task.task_status = TaskStatus.FAILED.value
        task.last_error_code = error_code[:64]
        task.last_error_message = normalized_reason
        task.processed_at = occurred_at
        task.updated_at = occurred_at

        metadata = {
            "api_request_id": api_request_id,
            "trace_id": trace_id,
            "grant_id": grant_record.grant_id,
            "task_id": task.task_id,
            "retry_count": task.retry_count,
            "error_code": task.last_error_code,
            "provider_request_id": provider_request_id,
            "provider_task_id": provider_task_id,
        }
        self._record_event(
            request_record=request_record,
            occurred_at=occurred_at,
            event_type="grant.provision_failed",
            operator_type=operator_type,
            operator_id=operator_id,
            from_request_status=RequestStatus.PROVISIONING.value,
            to_request_status=RequestStatus.FAILED.value,
            metadata=metadata | {"failed_reason": normalized_reason},
        )
        self._record_audit(
            request_record=request_record,
            created_at=occurred_at,
            event_type="grant.provision_failed",
            actor_type=self._to_actor_type(operator_type),
            actor_id=operator_id,
            result=AuditResult.FAIL.value,
            reason=normalized_reason,
            metadata=metadata,
        )

    def _create_grant_record(
        self,
        *,
        request_record: PermissionRequestRecord,
        grant_id: str,
    ) -> AccessGrantRecord:
        created_at = self._current_time()
        return AccessGrantRecord(
            grant_id=grant_id,
            request_id=request_record.request_id,
            resource_key=request_record.resource_key or "",
            resource_type=request_record.resource_type or "",
            action=request_record.action or "",
            grant_status=GrantStatus.PROVISIONING_REQUESTED.value,
            connector_status=ConnectorStatus.ACCEPTED.value,
            reconcile_status=_RECONCILE_PENDING,
            effective_at=None,
            expire_at=self._resolve_expire_at(request_record, created_at),
            revoked_at=None,
            revocation_reason=None,
            created_at=created_at,
            updated_at=created_at,
        )

    def _create_connector_task(
        self,
        *,
        request_record: PermissionRequestRecord,
        grant_record: AccessGrantRecord,
        latest_task: ConnectorTaskRecord | None,
        force_retry: bool,
    ) -> ConnectorTaskRecord:
        scheduled_at = self._current_time()
        retry_count = (latest_task.retry_count + 1) if latest_task is not None and force_retry else 0
        return ConnectorTaskRecord(
            task_id=_generate_prefixed_id("ctk"),
            grant_id=grant_record.grant_id,
            request_id=request_record.request_id,
            task_type="provision",
            task_status=TaskStatus.RETRYING.value if force_retry else TaskStatus.PENDING.value,
            retry_count=retry_count,
            max_retry_count=self.max_retry_count,
            last_error_code=None,
            last_error_message=None,
            payload_json={
                "grant_id": grant_record.grant_id,
                "request_id": request_record.request_id,
                "force_retry": force_retry,
                "retry_of_task_id": latest_task.task_id if latest_task is not None and force_retry else None,
            },
            scheduled_at=scheduled_at,
            processed_at=None,
            created_at=scheduled_at,
            updated_at=scheduled_at,
        )

    def _build_task_payload(
        self,
        *,
        task: ConnectorTaskRecord,
        response: ConnectorProvisionResponse,
    ) -> dict[str, object]:
        base_payload = dict(task.payload_json or {})
        base_payload.update(
            {
                "provider_request_id": response.provider_request_id,
                "provider_task_id": response.provider_task_id,
                "connector_status": response.connector_status.value,
                "retryable": response.retryable,
                "raw_payload": dict(response.raw_payload),
            }
        )
        if response.effective_at is not None:
            base_payload["effective_at"] = response.effective_at.isoformat().replace("+00:00", "Z")
        if response.error_code is not None:
            base_payload["error_code"] = response.error_code
        if response.error_message is not None:
            base_payload["error_message"] = response.error_message
        return base_payload

    def _recheck_policy(
        self,
        *,
        request_record: PermissionRequestRecord,
        command: GrantProvisionInput,
    ) -> None:
        if ApprovalStatus(request_record.approval_status) is not ApprovalStatus.APPROVED:
            raise DomainError(
                ErrorCode.APPROVAL_NOT_APPROVED,
                details={
                    "request_id": request_record.request_id,
                    "approval_status": request_record.approval_status,
                    "http_status": 409,
                },
            )
        if request_record.policy_version != command.policy_version:
            raise DomainError(
                ErrorCode.PROVISION_POLICY_RECHECK_FAILED,
                message="Policy version no longer matches the evaluated request",
                details={
                    "request_id": request_record.request_id,
                    "policy_version": request_record.policy_version,
                    "http_status": 409,
                },
            )
        if request_record.delegation_id != command.delegation_id:
            raise DomainError(
                ErrorCode.PROVISION_POLICY_RECHECK_FAILED,
                message="Delegation mismatch blocks provisioning",
                details={
                    "request_id": request_record.request_id,
                    "delegation_id": request_record.delegation_id,
                    "http_status": 409,
                },
            )
        if request_record.resource_type not in _SUPPORTED_RESOURCE_TYPES or request_record.action not in _SUPPORTED_ACTIONS:
            raise DomainError(
                ErrorCode.PROVISION_POLICY_RECHECK_FAILED,
                message="Provisioning only supports Feishu doc/report read permissions in V1",
                details={
                    "request_id": request_record.request_id,
                    "resource_type": request_record.resource_type,
                    "action": request_record.action,
                    "http_status": 409,
                },
            )
        if not request_record.resource_key:
            raise DomainError(
                ErrorCode.PROVISION_POLICY_RECHECK_FAILED,
                message="Resource key is required before provisioning",
                details={"request_id": request_record.request_id, "http_status": 409},
            )

    def _require_approved_request_for_initial_provision(
        self,
        request_record: PermissionRequestRecord,
    ) -> None:
        if RequestStatus(request_record.request_status) is not RequestStatus.APPROVED:
            raise DomainError(
                ErrorCode.REQUEST_STATUS_INVALID,
                message="Current request status does not allow initial provisioning",
                details={
                    "request_id": request_record.request_id,
                    "request_status": request_record.request_status,
                    "http_status": 409,
                },
            )
        if GrantStatus(request_record.grant_status) is not GrantStatus.NOT_CREATED:
            raise DomainError(
                ErrorCode.REQUEST_STATUS_INVALID,
                message="Current request grant status does not allow initial provisioning",
                details={
                    "request_id": request_record.request_id,
                    "grant_status": request_record.grant_status,
                    "http_status": 409,
                },
            )

    def _require_retryable_state(
        self,
        *,
        request_record: PermissionRequestRecord,
        grant_record: AccessGrantRecord,
        latest_task: ConnectorTaskRecord | None,
    ) -> None:
        if RequestStatus(request_record.request_status) is not RequestStatus.FAILED:
            raise DomainError(
                ErrorCode.RETRY_NOT_ALLOWED,
                message="Retry is only allowed after a failed provisioning request",
                details={
                    "request_id": request_record.request_id,
                    "request_status": request_record.request_status,
                    "http_status": 409,
                },
            )
        if GrantStatus(grant_record.grant_status) is not GrantStatus.PROVISION_FAILED:
            raise DomainError(
                ErrorCode.RETRY_NOT_ALLOWED,
                message="Retry is only allowed after a failed grant",
                details={
                    "grant_id": grant_record.grant_id,
                    "grant_status": grant_record.grant_status,
                    "http_status": 409,
                },
            )
        if latest_task is None or TaskStatus(latest_task.task_status) is not TaskStatus.FAILED:
            raise DomainError(
                ErrorCode.RETRY_NOT_ALLOWED,
                message="Retry requires a previously failed connector task",
                details={
                    "grant_id": grant_record.grant_id,
                    "http_status": 409,
                },
            )
        if latest_task.retry_count + 1 > latest_task.max_retry_count:
            raise DomainError(
                ErrorCode.RETRY_NOT_ALLOWED,
                message="Connector task has exhausted the configured retry count",
                details={
                    "grant_id": grant_record.grant_id,
                    "retry_count": latest_task.retry_count,
                    "max_retry_count": latest_task.max_retry_count,
                    "http_status": 409,
                },
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

    def _build_result(
        self,
        request_record: PermissionRequestRecord,
        grant_record: AccessGrantRecord,
        task: ConnectorTaskRecord | None,
    ) -> GrantProvisionResult:
        return GrantProvisionResult(
            grant_id=grant_record.grant_id,
            request_id=request_record.request_id,
            grant_status=GrantStatus(grant_record.grant_status),
            connector_status=ConnectorStatus(grant_record.connector_status),
            request_status=RequestStatus(request_record.request_status),
            connector_task_id=task.task_id if task is not None else None,
            connector_task_status=TaskStatus(task.task_status) if task is not None else None,
            effective_at=grant_record.effective_at,
            retry_count=task.retry_count if task is not None else 0,
        )

    def _resolve_expire_at(
        self,
        request_record: PermissionRequestRecord,
        started_at: datetime,
    ) -> datetime:
        return started_at + self._parse_duration(request_record.requested_duration)

    def _parse_duration(self, raw_duration: str | None) -> timedelta:
        if raw_duration is None or not raw_duration.strip():
            return _DEFAULT_DURATION
        normalized = raw_duration.strip().upper()
        if match := re.fullmatch(r"P(\d+)D", normalized):
            return timedelta(days=int(match.group(1)))
        if match := re.fullmatch(r"P(\d+)W", normalized):
            return timedelta(weeks=int(match.group(1)))
        if match := re.fullmatch(r"P(\d+)M", normalized):
            return timedelta(days=int(match.group(1)) * 30)
        if match := re.fullmatch(r"PT(\d+)H", normalized):
            return timedelta(hours=int(match.group(1)))
        return _DEFAULT_DURATION

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

    def _require_operator(self, operator_type: OperatorType) -> None:
        if operator_type not in _PROVISION_OPERATORS:
            raise DomainError(
                ErrorCode.FORBIDDEN,
                details={"operator_type": operator_type.value, "http_status": 403},
            )

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
