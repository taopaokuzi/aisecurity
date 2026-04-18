from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable
from uuid import uuid4

from packages.domain import (
    ActorType,
    AgentStatus,
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
    AgentIdentityRecord,
    AuditRecordRecord,
    ConnectorTaskRecord,
    PermissionRequestEventRecord,
    PermissionRequestRecord,
    SessionContextRecord,
)
from packages.infrastructure.feishu_connector import (
    ConnectorSessionRevokeCommand,
    ConnectorSessionRevokeResponse,
    ConnectorUnavailableError,
    FeishuSessionConnector,
)
from packages.infrastructure.repositories import (
    AccessGrantRepository,
    AgentIdentityRepository,
    AuditRecordRepository,
    ConnectorTaskRepository,
    PermissionRequestEventRepository,
    PermissionRequestRepository,
    SessionContextRepository,
)

_SESSION_REVOKE_TASK_TYPE = "session_revoke"
_DEFAULT_REVOKE_MAX_RETRY_COUNT = 3
_MANUAL_REVOKE_OPERATORS = frozenset(
    {
        OperatorType.SYSTEM,
        OperatorType.IT_ADMIN,
        OperatorType.SECURITY_ADMIN,
    }
)
_AGENT_DISABLE_OPERATORS = frozenset(
    {
        OperatorType.SYSTEM,
        OperatorType.IT_ADMIN,
        OperatorType.SECURITY_ADMIN,
    }
)
_ACTIVE_SESSION_STATES = frozenset({SessionStatus.ACTIVE, SessionStatus.SYNC_FAILED})
_IN_PROGRESS_SESSION_STATES = frozenset({SessionStatus.REVOKING, SessionStatus.SYNCING})
_TERMINAL_SESSION_STATES = frozenset({SessionStatus.REVOKED, SessionStatus.EXPIRED})


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _generate_prefixed_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:24]}"


@dataclass(slots=True, frozen=True)
class SessionBindingInput:
    grant_id: str
    request_id: str
    agent_id: str
    user_id: str
    connector_session_ref: str | None = None
    task_session_id: str | None = None


@dataclass(slots=True, frozen=True)
class SessionBindingResult:
    global_session_id: str
    session_status: SessionStatus
    grant_id: str
    request_id: str


@dataclass(slots=True, frozen=True)
class SessionStatusResult:
    global_session_id: str
    session_status: SessionStatus
    grant_id: str
    request_id: str
    agent_id: str
    user_id: str


@dataclass(slots=True, frozen=True)
class SessionRevokeInput:
    global_session_id: str
    reason: str
    cascade_connector_sessions: bool
    api_request_id: str
    operator_user_id: str
    operator_type: OperatorType | str = OperatorType.SYSTEM
    trace_id: str | None = None
    trigger_source: str = "Manual"


@dataclass(slots=True, frozen=True)
class SessionRevokeRequestedResult:
    global_session_id: str
    session_status: SessionStatus
    grant_id: str
    request_id: str
    revoke_task_id: str | None


@dataclass(slots=True, frozen=True)
class SessionRevokeProcessResult:
    global_session_id: str
    session_status: SessionStatus
    grant_id: str
    request_id: str
    revoke_task_id: str
    grant_status: GrantStatus
    request_status: RequestStatus


@dataclass(slots=True, frozen=True)
class SessionRevokeBatchResult:
    processed_count: int
    revoked_count: int
    sync_failed_count: int


@dataclass(slots=True, frozen=True)
class AgentDisableInput:
    agent_id: str
    reason: str
    api_request_id: str
    operator_user_id: str
    operator_type: OperatorType | str = OperatorType.SYSTEM
    trace_id: str | None = None
    cascade_connector_sessions: bool = True


@dataclass(slots=True, frozen=True)
class AgentDisableResult:
    agent_id: str
    agent_status: AgentStatus
    revoked_session_count: int
    revoke_job_created: bool


class SessionAuthority:
    def __init__(
        self,
        *,
        permission_request_repository: PermissionRequestRepository,
        access_grant_repository: AccessGrantRepository,
        session_context_repository: SessionContextRepository,
        permission_request_event_repository: PermissionRequestEventRepository,
        audit_repository: AuditRecordRepository,
        connector_task_repository: ConnectorTaskRepository,
        agent_identity_repository: AgentIdentityRepository,
        connector: FeishuSessionConnector,
        now_provider: Callable[[], datetime] = _utc_now,
        revoke_max_retry_count: int = _DEFAULT_REVOKE_MAX_RETRY_COUNT,
    ) -> None:
        self.permission_request_repository = permission_request_repository
        self.access_grant_repository = access_grant_repository
        self.session_context_repository = session_context_repository
        self.permission_request_event_repository = permission_request_event_repository
        self.audit_repository = audit_repository
        self.connector_task_repository = connector_task_repository
        self.agent_identity_repository = agent_identity_repository
        self.connector = connector
        self.now_provider = now_provider
        self.revoke_max_retry_count = revoke_max_retry_count

    def bind_active_session(self, command: SessionBindingInput) -> SessionBindingResult:
        grant_record = self._get_grant_record(command.grant_id)
        request_record = self._get_request_record(command.request_id)
        if grant_record.request_id != request_record.request_id:
            raise DomainError(
                ErrorCode.REQUEST_STATUS_INVALID,
                message="Grant is not bound to the supplied request",
                details={
                    "grant_id": grant_record.grant_id,
                    "request_id": request_record.request_id,
                    "http_status": 409,
                },
            )
        if GrantStatus(grant_record.grant_status) is not GrantStatus.ACTIVE:
            raise DomainError(
                ErrorCode.REQUEST_STATUS_INVALID,
                message="Only active grants can bind a global session",
                details={
                    "grant_id": grant_record.grant_id,
                    "grant_status": grant_record.grant_status,
                    "http_status": 409,
                },
            )
        if RequestStatus(request_record.request_status) is not RequestStatus.ACTIVE:
            raise DomainError(
                ErrorCode.REQUEST_STATUS_INVALID,
                message="Only active requests can bind a global session",
                details={
                    "request_id": request_record.request_id,
                    "request_status": request_record.request_status,
                    "http_status": 409,
                },
            )

        current_time = self._current_time()
        record = self.session_context_repository.get_by_grant_id(command.grant_id)
        if record is None:
            record = SessionContextRecord(
                global_session_id=_generate_prefixed_id("gs"),
                grant_id=command.grant_id,
                request_id=command.request_id,
                agent_id=command.agent_id,
                user_id=command.user_id,
                task_session_id=command.task_session_id,
                connector_session_ref=command.connector_session_ref,
                session_status=SessionStatus.ACTIVE.value,
                revocation_reason=None,
                last_sync_at=current_time,
                revoked_at=None,
                created_at=current_time,
                updated_at=current_time,
            )
            self.session_context_repository.add(record)
        else:
            record.request_id = command.request_id
            record.agent_id = command.agent_id
            record.user_id = command.user_id
            record.task_session_id = command.task_session_id
            record.connector_session_ref = command.connector_session_ref
            record.session_status = SessionStatus.ACTIVE.value
            record.revocation_reason = None
            record.last_sync_at = current_time
            record.revoked_at = None
            record.updated_at = current_time

        return SessionBindingResult(
            global_session_id=record.global_session_id,
            session_status=SessionStatus(record.session_status),
            grant_id=record.grant_id,
            request_id=record.request_id,
        )

    def refresh_session_request_binding(
        self,
        *,
        grant_id: str,
        request_id: str,
        operator_user_id: str,
        api_request_id: str,
        operator_type: OperatorType | str = OperatorType.SYSTEM,
        trace_id: str | None = None,
    ) -> SessionBindingResult | None:
        record = self.session_context_repository.get_by_grant_id(grant_id)
        if record is None:
            return None

        current_time = self._current_time()
        previous_request_id = record.request_id
        record.request_id = request_id
        record.updated_at = current_time

        request_record = self._get_request_record(request_id)
        normalized_operator_type = self._coerce_operator_type(operator_type)
        self._record_event(
            request_record=request_record,
            occurred_at=current_time,
            event_type="session.binding_refreshed",
            operator_type=normalized_operator_type,
            operator_id=operator_user_id,
            from_request_status=request_record.request_status,
            to_request_status=request_record.request_status,
            metadata={
                "api_request_id": api_request_id,
                "trace_id": trace_id,
                "global_session_id": record.global_session_id,
                "grant_id": grant_id,
                "previous_request_id": previous_request_id,
                "request_id": request_id,
            },
        )
        self._record_audit(
            request_record=request_record,
            created_at=current_time,
            event_type="session.binding_refreshed",
            actor_type=self._to_actor_type(normalized_operator_type),
            actor_id=operator_user_id,
            result=AuditResult.SUCCESS.value,
            metadata={
                "api_request_id": api_request_id,
                "trace_id": trace_id,
                "global_session_id": record.global_session_id,
                "grant_id": grant_id,
                "previous_request_id": previous_request_id,
                "request_id": request_id,
            },
            global_session_id=record.global_session_id,
        )

        return SessionBindingResult(
            global_session_id=record.global_session_id,
            session_status=SessionStatus(record.session_status),
            grant_id=record.grant_id,
            request_id=record.request_id,
        )

    def get_session_status(self, global_session_id: str) -> SessionStatusResult:
        record = self._get_session_record(global_session_id)
        return SessionStatusResult(
            global_session_id=record.global_session_id,
            session_status=SessionStatus(record.session_status),
            grant_id=record.grant_id,
            request_id=record.request_id,
            agent_id=record.agent_id,
            user_id=record.user_id,
        )

    def require_active_session(
        self,
        *,
        global_session_id: str,
        action_name: str,
    ) -> SessionStatusResult:
        result = self.get_session_status(global_session_id)
        if result.session_status is not SessionStatus.ACTIVE:
            raise DomainError(
                ErrorCode.FORBIDDEN,
                message="Session is not active for the requested high-risk action",
                details={
                    "global_session_id": global_session_id,
                    "session_status": result.session_status.value,
                    "action_name": action_name,
                    "http_status": 409,
                },
            )
        return result

    def request_session_revoke(self, command: SessionRevokeInput) -> SessionRevokeRequestedResult:
        operator_type = self._coerce_operator_type(command.operator_type)
        self._require_manual_revoke_operator(operator_type)
        record = self._get_session_record(command.global_session_id)
        request_record = self._get_request_record(record.request_id)
        grant_record = self._get_grant_record(record.grant_id)
        if grant_record.request_id != request_record.request_id:
            raise DomainError(
                ErrorCode.REQUEST_STATUS_INVALID,
                message="Session request chain is inconsistent with the current grant",
                details={
                    "global_session_id": record.global_session_id,
                    "grant_id": grant_record.grant_id,
                    "request_id": request_record.request_id,
                    "http_status": 409,
                },
            )

        return self._request_revoke_for_session(
            session_record=record,
            request_record=request_record,
            grant_record=grant_record,
            reason=command.reason,
            trigger_source=command.trigger_source,
            cascade_connector_sessions=command.cascade_connector_sessions,
            operator_user_id=command.operator_user_id,
            operator_type=operator_type,
            api_request_id=command.api_request_id,
            trace_id=command.trace_id,
        )

    def request_revoke_for_grant_expiration(
        self,
        *,
        grant_id: str,
        reason: str,
        api_request_id: str,
        operator_user_id: str = "grant_lifecycle_worker",
        operator_type: OperatorType | str = OperatorType.SYSTEM,
        trace_id: str | None = None,
    ) -> SessionRevokeRequestedResult | None:
        session_record = self.session_context_repository.get_by_grant_id(grant_id)
        if session_record is None:
            return None
        if SessionStatus(session_record.session_status) in _TERMINAL_SESSION_STATES:
            return None

        request_record = self._get_request_record(session_record.request_id)
        grant_record = self._get_grant_record(grant_id)
        normalized_operator_type = self._coerce_operator_type(operator_type)
        return self._request_revoke_for_session(
            session_record=session_record,
            request_record=request_record,
            grant_record=grant_record,
            reason=reason,
            trigger_source="GrantExpired",
            cascade_connector_sessions=True,
            operator_user_id=operator_user_id,
            operator_type=normalized_operator_type,
            api_request_id=api_request_id,
            trace_id=trace_id,
        )

    def disable_agent_and_request_revoke(self, command: AgentDisableInput) -> AgentDisableResult:
        operator_type = self._coerce_operator_type(command.operator_type)
        self._require_agent_disable_operator(operator_type)
        agent_record = self._get_agent_record(command.agent_id)

        current_time = self._current_time()
        agent_record.agent_status = AgentStatus.DISABLED.value
        agent_record.updated_at = current_time

        sessions = self.session_context_repository.list_for_agent(
            command.agent_id,
            statuses=[status.value for status in _ACTIVE_SESSION_STATES],
            limit=None,
        )
        revoked_session_count = 0
        revoke_job_created = False
        for session_record in sessions:
            request_record = self._get_request_record(session_record.request_id)
            grant_record = self._get_grant_record(session_record.grant_id)
            result = self._request_revoke_for_session(
                session_record=session_record,
                request_record=request_record,
                grant_record=grant_record,
                reason=command.reason,
                trigger_source="AgentDisabled",
                cascade_connector_sessions=command.cascade_connector_sessions,
                operator_user_id=command.operator_user_id,
                operator_type=operator_type,
                api_request_id=command.api_request_id,
                trace_id=command.trace_id,
            )
            revoked_session_count += 1
            revoke_job_created = revoke_job_created or result.revoke_task_id is not None

        return AgentDisableResult(
            agent_id=agent_record.agent_id,
            agent_status=AgentStatus(agent_record.agent_status),
            revoked_session_count=revoked_session_count,
            revoke_job_created=revoke_job_created,
        )

    def process_pending_revoke_tasks(
        self,
        *,
        limit: int | None = 100,
    ) -> SessionRevokeBatchResult:
        tasks = self.connector_task_repository.list_pending_session_revoke_tasks(limit=limit)
        revoked_count = 0
        sync_failed_count = 0
        for task in tasks:
            result = self.process_session_revoke_task(task.task_id)
            if result.session_status is SessionStatus.REVOKED:
                revoked_count += 1
            elif result.session_status is SessionStatus.SYNC_FAILED:
                sync_failed_count += 1
        return SessionRevokeBatchResult(
            processed_count=len(tasks),
            revoked_count=revoked_count,
            sync_failed_count=sync_failed_count,
        )

    def process_session_revoke_task(self, task_id: str) -> SessionRevokeProcessResult:
        task = self.connector_task_repository.get(task_id)
        if task is None or task.task_type != _SESSION_REVOKE_TASK_TYPE:
            raise DomainError(
                ErrorCode.REQUEST_STATUS_INVALID,
                message="Session revoke task was not found",
                details={"task_id": task_id, "http_status": 404},
            )

        payload = dict(task.payload_json or {})
        global_session_id = payload.get("global_session_id")
        if not isinstance(global_session_id, str) or not global_session_id.strip():
            raise DomainError(
                ErrorCode.REQUEST_STATUS_INVALID,
                message="Session revoke task payload is missing global_session_id",
                details={"task_id": task_id, "http_status": 409},
            )

        session_record = self._get_session_record(global_session_id)
        request_record = self._get_request_record(session_record.request_id)
        grant_record = self._get_grant_record(session_record.grant_id)
        current_time = self._current_time()
        task.task_status = TaskStatus.RUNNING.value
        task.updated_at = current_time

        try:
            response = self.connector.revoke_session(
                ConnectorSessionRevokeCommand(
                    global_session_id=session_record.global_session_id,
                    grant_id=grant_record.grant_id,
                    request_id=request_record.request_id,
                    agent_id=session_record.agent_id,
                    user_id=session_record.user_id,
                    reason=str(payload.get("reason") or session_record.revocation_reason or "Session revoked"),
                    cascade_connector_sessions=bool(payload.get("cascade_connector_sessions", True)),
                    api_request_id=str(payload.get("api_request_id") or ""),
                    connector_session_ref=session_record.connector_session_ref,
                    task_session_id=session_record.task_session_id,
                    trace_id=payload.get("trace_id") if isinstance(payload.get("trace_id"), str) else None,
                )
            )
        except ConnectorUnavailableError as exc:
            return self._mark_revoke_sync_failed(
                session_record=session_record,
                request_record=request_record,
                grant_record=grant_record,
                task=task,
                error_code="CONNECTOR_UNAVAILABLE",
                error_message=str(exc),
                provider_response=None,
                current_time=self._current_time(),
                payload=payload,
            )

        if response.error_code is not None:
            return self._mark_revoke_sync_failed(
                session_record=session_record,
                request_record=request_record,
                grant_record=grant_record,
                task=task,
                error_code=response.error_code,
                error_message=response.error_message or "Session revoke sync failed",
                provider_response=response,
                current_time=self._current_time(),
                payload=payload,
            )

        return self._mark_revoke_succeeded(
            session_record=session_record,
            request_record=request_record,
            grant_record=grant_record,
            task=task,
            response=response,
            current_time=self._current_time(),
            payload=payload,
        )

    def _request_revoke_for_session(
        self,
        *,
        session_record: SessionContextRecord,
        request_record: PermissionRequestRecord,
        grant_record: AccessGrantRecord,
        reason: str,
        trigger_source: str,
        cascade_connector_sessions: bool,
        operator_user_id: str,
        operator_type: OperatorType,
        api_request_id: str,
        trace_id: str | None,
    ) -> SessionRevokeRequestedResult:
        normalized_reason = self._normalize_reason(reason)
        session_status = SessionStatus(session_record.session_status)
        if session_status in _TERMINAL_SESSION_STATES:
            raise DomainError(
                ErrorCode.SESSION_ALREADY_REVOKED,
                details={
                    "global_session_id": session_record.global_session_id,
                    "session_status": session_status.value,
                    "http_status": 409,
                },
            )

        latest_task = self.connector_task_repository.get_latest_session_revoke_for_session(
            global_session_id=session_record.global_session_id,
        )
        if session_status in _IN_PROGRESS_SESSION_STATES:
            return SessionRevokeRequestedResult(
                global_session_id=session_record.global_session_id,
                session_status=session_status,
                grant_id=grant_record.grant_id,
                request_id=request_record.request_id,
                revoke_task_id=latest_task.task_id if latest_task is not None else None,
            )

        current_time = self._current_time()
        retrying = session_status is SessionStatus.SYNC_FAILED
        next_session_status = SessionStatus.SYNCING if retrying else SessionStatus.REVOKING
        session_record.session_status = next_session_status.value
        session_record.revocation_reason = normalized_reason
        session_record.updated_at = current_time

        if GrantStatus(grant_record.grant_status) is not GrantStatus.EXPIRED:
            grant_record.grant_status = GrantStatus.REVOKING.value
            grant_record.revocation_reason = normalized_reason
            grant_record.updated_at = current_time

        request_record.grant_status = grant_record.grant_status
        request_record.current_task_state = TaskStatus.RUNNING.value
        request_record.failed_reason = None
        request_record.updated_at = current_time

        task = self._create_session_revoke_task(
            session_record=session_record,
            request_record=request_record,
            grant_record=grant_record,
            latest_task=latest_task,
            current_time=current_time,
            api_request_id=api_request_id,
            trace_id=trace_id,
            trigger_source=trigger_source,
            reason=normalized_reason,
            cascade_connector_sessions=cascade_connector_sessions,
            retrying=retrying,
        )
        if task is not None:
            self.connector_task_repository.add(task)

        self._record_event(
            request_record=request_record,
            occurred_at=current_time,
            event_type="session.retry_started" if retrying else "session.revoke_requested",
            operator_type=operator_type,
            operator_id=operator_user_id,
            from_request_status=request_record.request_status,
            to_request_status=request_record.request_status,
            metadata={
                "api_request_id": api_request_id,
                "trace_id": trace_id,
                "global_session_id": session_record.global_session_id,
                "grant_id": grant_record.grant_id,
                "revoke_task_id": task.task_id if task is not None else latest_task.task_id if latest_task else None,
                "trigger_source": trigger_source,
                "cascade_connector_sessions": cascade_connector_sessions,
            },
        )
        self._record_audit(
            request_record=request_record,
            created_at=current_time,
            event_type="session.retry_started" if retrying else "session.revoke_requested",
            actor_type=self._to_actor_type(operator_type),
            actor_id=operator_user_id,
            result=AuditResult.SUCCESS.value,
            metadata={
                "api_request_id": api_request_id,
                "trace_id": trace_id,
                "global_session_id": session_record.global_session_id,
                "grant_id": grant_record.grant_id,
                "revoke_task_id": task.task_id if task is not None else latest_task.task_id if latest_task else None,
                "trigger_source": trigger_source,
                "cascade_connector_sessions": cascade_connector_sessions,
            },
            global_session_id=session_record.global_session_id,
        )

        return SessionRevokeRequestedResult(
            global_session_id=session_record.global_session_id,
            session_status=next_session_status,
            grant_id=grant_record.grant_id,
            request_id=request_record.request_id,
            revoke_task_id=task.task_id if task is not None else None,
        )

    def _mark_revoke_succeeded(
        self,
        *,
        session_record: SessionContextRecord,
        request_record: PermissionRequestRecord,
        grant_record: AccessGrantRecord,
        task: ConnectorTaskRecord,
        response: ConnectorSessionRevokeResponse,
        current_time: datetime,
        payload: dict[str, object],
    ) -> SessionRevokeProcessResult:
        task.task_status = TaskStatus.SUCCEEDED.value
        task.last_error_code = None
        task.last_error_message = None
        task.processed_at = current_time
        task.updated_at = current_time
        task.payload_json = self._merge_task_payload(
            payload,
            response=response,
            current_time=current_time,
        )

        session_record.session_status = SessionStatus.REVOKED.value
        session_record.last_sync_at = current_time
        session_record.revoked_at = response.revoked_at or current_time
        session_record.updated_at = current_time
        if response.connector_session_ref is not None:
            session_record.connector_session_ref = response.connector_session_ref

        final_request_status = self._resolve_success_request_status(
            request_record=request_record,
            trigger_source=str(payload.get("trigger_source") or ""),
        )
        final_grant_status = self._resolve_success_grant_status(
            grant_record=grant_record,
            trigger_source=str(payload.get("trigger_source") or ""),
        )
        previous_request_status = request_record.request_status
        grant_record.grant_status = final_grant_status.value
        if final_grant_status is GrantStatus.REVOKED:
            grant_record.revoked_at = response.revoked_at or current_time
            grant_record.revocation_reason = session_record.revocation_reason
        grant_record.updated_at = current_time

        request_record.request_status = final_request_status.value
        request_record.grant_status = final_grant_status.value
        request_record.current_task_state = TaskStatus.SUCCEEDED.value
        request_record.failed_reason = None
        request_record.updated_at = current_time

        metadata = {
            "api_request_id": payload.get("api_request_id"),
            "trace_id": payload.get("trace_id"),
            "global_session_id": session_record.global_session_id,
            "grant_id": grant_record.grant_id,
            "revoke_task_id": task.task_id,
            "trigger_source": payload.get("trigger_source"),
            "provider_request_id": response.provider_request_id,
            "provider_task_id": response.provider_task_id,
            "cascade_connector_sessions": payload.get("cascade_connector_sessions"),
            "revoked_at": (response.revoked_at or current_time).isoformat().replace("+00:00", "Z"),
        }
        self._record_event(
            request_record=request_record,
            occurred_at=current_time,
            event_type="session.revoked",
            operator_type=OperatorType.SYSTEM,
            operator_id="session_revoke_worker",
            from_request_status=previous_request_status,
            to_request_status=final_request_status.value,
            metadata=metadata,
        )
        self._record_audit(
            request_record=request_record,
            created_at=current_time,
            event_type="session.revoked",
            actor_type=ActorType.SYSTEM,
            actor_id="session_revoke_worker",
            result=AuditResult.SUCCESS.value,
            metadata=metadata,
            global_session_id=session_record.global_session_id,
        )
        return SessionRevokeProcessResult(
            global_session_id=session_record.global_session_id,
            session_status=SessionStatus(session_record.session_status),
            grant_id=grant_record.grant_id,
            request_id=request_record.request_id,
            revoke_task_id=task.task_id,
            grant_status=GrantStatus(grant_record.grant_status),
            request_status=RequestStatus(request_record.request_status),
        )

    def _mark_revoke_sync_failed(
        self,
        *,
        session_record: SessionContextRecord,
        request_record: PermissionRequestRecord,
        grant_record: AccessGrantRecord,
        task: ConnectorTaskRecord,
        error_code: str,
        error_message: str,
        provider_response: ConnectorSessionRevokeResponse | None,
        current_time: datetime,
        payload: dict[str, object],
    ) -> SessionRevokeProcessResult:
        normalized_message = error_message[:256]
        task.task_status = TaskStatus.FAILED.value
        task.last_error_code = error_code[:64]
        task.last_error_message = normalized_message
        task.processed_at = current_time
        task.updated_at = current_time
        task.payload_json = self._merge_task_payload(
            payload,
            response=provider_response,
            current_time=current_time,
            error_code=task.last_error_code,
            error_message=normalized_message,
        )

        session_record.session_status = SessionStatus.SYNC_FAILED.value
        session_record.last_sync_at = current_time
        session_record.updated_at = current_time

        trigger_source = str(payload.get("trigger_source") or "")
        if self._resolve_success_grant_status(
            grant_record=grant_record,
            trigger_source=trigger_source,
        ) is not GrantStatus.EXPIRED:
            grant_record.grant_status = GrantStatus.REVOKE_FAILED.value
            grant_record.revocation_reason = session_record.revocation_reason
            grant_record.updated_at = current_time
            request_record.grant_status = GrantStatus.REVOKE_FAILED.value
        request_record.current_task_state = TaskStatus.FAILED.value
        request_record.failed_reason = normalized_message
        request_record.updated_at = current_time

        metadata = {
            "api_request_id": payload.get("api_request_id"),
            "trace_id": payload.get("trace_id"),
            "global_session_id": session_record.global_session_id,
            "grant_id": grant_record.grant_id,
            "revoke_task_id": task.task_id,
            "trigger_source": trigger_source,
            "cascade_connector_sessions": payload.get("cascade_connector_sessions"),
            "error_code": task.last_error_code,
        }
        self._record_event(
            request_record=request_record,
            occurred_at=current_time,
            event_type="session.sync_failed",
            operator_type=OperatorType.SYSTEM,
            operator_id="session_revoke_worker",
            from_request_status=request_record.request_status,
            to_request_status=request_record.request_status,
            metadata=metadata | {"failed_reason": normalized_message},
        )
        self._record_audit(
            request_record=request_record,
            created_at=current_time,
            event_type="session.sync_failed",
            actor_type=ActorType.SYSTEM,
            actor_id="session_revoke_worker",
            result=AuditResult.FAIL.value,
            metadata=metadata,
            reason=normalized_message,
            global_session_id=session_record.global_session_id,
        )
        return SessionRevokeProcessResult(
            global_session_id=session_record.global_session_id,
            session_status=SessionStatus(session_record.session_status),
            grant_id=grant_record.grant_id,
            request_id=request_record.request_id,
            revoke_task_id=task.task_id,
            grant_status=GrantStatus(grant_record.grant_status),
            request_status=RequestStatus(request_record.request_status),
        )

    def _create_session_revoke_task(
        self,
        *,
        session_record: SessionContextRecord,
        request_record: PermissionRequestRecord,
        grant_record: AccessGrantRecord,
        latest_task: ConnectorTaskRecord | None,
        current_time: datetime,
        api_request_id: str,
        trace_id: str | None,
        trigger_source: str,
        reason: str,
        cascade_connector_sessions: bool,
        retrying: bool,
    ) -> ConnectorTaskRecord | None:
        if latest_task is not None and TaskStatus(latest_task.task_status) in {
            TaskStatus.PENDING,
            TaskStatus.RUNNING,
            TaskStatus.RETRYING,
        }:
            return None

        retry_count = 0
        if latest_task is not None:
            retry_count = latest_task.retry_count + 1 if retrying else latest_task.retry_count
            if retrying and retry_count > latest_task.max_retry_count:
                raise DomainError(
                    ErrorCode.RETRY_NOT_ALLOWED,
                    message="Session revoke retry count has been exhausted",
                    details={
                        "global_session_id": session_record.global_session_id,
                        "retry_count": retry_count,
                        "max_retry_count": latest_task.max_retry_count,
                        "http_status": 409,
                    },
                )

        return ConnectorTaskRecord(
            task_id=_generate_prefixed_id("ctk"),
            grant_id=grant_record.grant_id,
            request_id=request_record.request_id,
            task_type=_SESSION_REVOKE_TASK_TYPE,
            task_status=TaskStatus.RETRYING.value if retrying else TaskStatus.PENDING.value,
            retry_count=retry_count,
            max_retry_count=latest_task.max_retry_count if latest_task is not None else self.revoke_max_retry_count,
            last_error_code=None,
            last_error_message=None,
            payload_json={
                "global_session_id": session_record.global_session_id,
                "grant_id": grant_record.grant_id,
                "request_id": request_record.request_id,
                "api_request_id": api_request_id,
                "trace_id": trace_id,
                "trigger_source": trigger_source,
                "reason": reason,
                "cascade_connector_sessions": cascade_connector_sessions,
                "retry_of_task_id": latest_task.task_id if latest_task is not None and retrying else None,
            },
            scheduled_at=current_time,
            processed_at=None,
            created_at=current_time,
            updated_at=current_time,
        )

    def _merge_task_payload(
        self,
        original_payload: dict[str, object],
        *,
        current_time: datetime,
        response: ConnectorSessionRevokeResponse | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> dict[str, object]:
        payload = dict(original_payload)
        payload["processed_at"] = current_time.isoformat().replace("+00:00", "Z")
        if response is not None:
            payload["provider_request_id"] = response.provider_request_id
            payload["provider_task_id"] = response.provider_task_id
            payload["connector_session_ref"] = response.connector_session_ref
            payload["retryable"] = response.retryable
            payload["raw_payload"] = dict(response.raw_payload)
            if response.revoked_at is not None:
                payload["revoked_at"] = response.revoked_at.isoformat().replace("+00:00", "Z")
        if error_code is not None:
            payload["error_code"] = error_code
        if error_message is not None:
            payload["error_message"] = error_message
        return payload

    def _resolve_success_request_status(
        self,
        *,
        request_record: PermissionRequestRecord,
        trigger_source: str,
    ) -> RequestStatus:
        if trigger_source == "GrantExpired" or RequestStatus(request_record.request_status) is RequestStatus.EXPIRED:
            return RequestStatus.EXPIRED
        return RequestStatus.REVOKED

    def _resolve_success_grant_status(
        self,
        *,
        grant_record: AccessGrantRecord,
        trigger_source: str,
    ) -> GrantStatus:
        if trigger_source == "GrantExpired" or GrantStatus(grant_record.grant_status) is GrantStatus.EXPIRED:
            return GrantStatus.EXPIRED
        return GrantStatus.REVOKED

    def _normalize_reason(self, reason: str) -> str:
        normalized = (reason or "").strip()
        if not normalized:
            raise DomainError(
                ErrorCode.REQUEST_MESSAGE_EMPTY,
                message="Session revoke reason is required",
                details={"field": "reason", "http_status": 400},
            )
        return normalized[:256]

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
        global_session_id: str | None = None,
    ) -> None:
        self.audit_repository.add(
            AuditRecordRecord(
                audit_id=_generate_prefixed_id("aud"),
                request_id=request_record.request_id,
                event_type=event_type,
                actor_type=actor_type.value,
                actor_id=actor_id,
                subject_chain=self._subject_chain(request_record, global_session_id=global_session_id),
                result=result,
                reason=reason,
                metadata_json=self._compact_metadata(metadata),
                created_at=created_at,
            )
        )

    def _subject_chain(
        self,
        request_record: PermissionRequestRecord,
        *,
        global_session_id: str | None = None,
    ) -> str:
        base_chain = (
            f"user:{request_record.user_id}->"
            f"agent:{request_record.agent_id}->"
            f"request:{request_record.request_id}"
        )
        if global_session_id is None:
            return base_chain
        return f"{base_chain}->session:{global_session_id}"

    def _compact_metadata(self, metadata: dict[str, object | None]) -> dict[str, object]:
        return {key: value for key, value in metadata.items() if value is not None}

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

    def _require_manual_revoke_operator(self, operator_type: OperatorType) -> None:
        if operator_type not in _MANUAL_REVOKE_OPERATORS:
            raise DomainError(
                ErrorCode.FORBIDDEN,
                details={"operator_type": operator_type.value, "http_status": 403},
            )

    def _require_agent_disable_operator(self, operator_type: OperatorType) -> None:
        if operator_type not in _AGENT_DISABLE_OPERATORS:
            raise DomainError(
                ErrorCode.FORBIDDEN,
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

    def _get_agent_record(self, agent_id: str) -> AgentIdentityRecord:
        record = self.agent_identity_repository.get(agent_id)
        if record is None:
            raise DomainError(
                ErrorCode.REQUEST_STATUS_INVALID,
                message="Agent identity was not found",
                details={"agent_id": agent_id, "http_status": 404},
            )
        return record

    def _to_actor_type(self, operator_type: OperatorType) -> ActorType:
        return ActorType(operator_type.value)

    def _current_time(self) -> datetime:
        return self.now_provider().astimezone(timezone.utc)
