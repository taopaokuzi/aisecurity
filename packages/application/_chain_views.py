from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from packages.infrastructure.db.models import (
    AccessGrantRecord,
    ApprovalRecordRecord,
    ConnectorTaskRecord,
    PermissionRequestRecord,
    SessionContextRecord,
)


@dataclass(slots=True, frozen=True)
class PermissionRequestReference:
    request_id: str
    user_id: str
    agent_id: str
    delegation_id: str
    request_status: str
    approval_status: str
    grant_status: str
    current_task_state: str | None
    failed_reason: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(slots=True, frozen=True)
class AccessGrantReference:
    grant_id: str
    request_id: str
    resource_key: str
    resource_type: str
    action: str
    grant_status: str
    connector_status: str
    reconcile_status: str
    effective_at: datetime | None
    expire_at: datetime
    revoked_at: datetime | None
    revocation_reason: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(slots=True, frozen=True)
class ConnectorTaskReference:
    task_id: str
    grant_id: str
    request_id: str
    task_type: str
    task_status: str
    retry_count: int
    max_retry_count: int
    last_error_code: str | None
    last_error_message: str | None
    scheduled_at: datetime
    processed_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(slots=True, frozen=True)
class SessionContextReference:
    global_session_id: str
    grant_id: str
    request_id: str
    agent_id: str
    user_id: str
    task_session_id: str | None
    connector_session_ref: str | None
    session_status: str
    revocation_reason: str | None
    last_sync_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime
    updated_at: datetime


@dataclass(slots=True, frozen=True)
class ApprovalRecordReference:
    approval_id: str
    request_id: str
    external_approval_id: str | None
    approval_node: str
    approver_id: str | None
    approval_status: str
    submitted_at: datetime | None
    approved_at: datetime | None
    rejected_at: datetime | None
    created_at: datetime
    updated_at: datetime


def build_permission_request_reference(
    record: PermissionRequestRecord | None,
) -> PermissionRequestReference | None:
    if record is None:
        return None
    return PermissionRequestReference(
        request_id=record.request_id,
        user_id=record.user_id,
        agent_id=record.agent_id,
        delegation_id=record.delegation_id,
        request_status=record.request_status,
        approval_status=record.approval_status,
        grant_status=record.grant_status,
        current_task_state=record.current_task_state,
        failed_reason=record.failed_reason,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def build_access_grant_reference(
    record: AccessGrantRecord | None,
) -> AccessGrantReference | None:
    if record is None:
        return None
    return AccessGrantReference(
        grant_id=record.grant_id,
        request_id=record.request_id,
        resource_key=record.resource_key,
        resource_type=record.resource_type,
        action=record.action,
        grant_status=record.grant_status,
        connector_status=record.connector_status,
        reconcile_status=record.reconcile_status,
        effective_at=record.effective_at,
        expire_at=record.expire_at,
        revoked_at=record.revoked_at,
        revocation_reason=record.revocation_reason,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def build_connector_task_reference(
    record: ConnectorTaskRecord | None,
) -> ConnectorTaskReference | None:
    if record is None:
        return None
    return ConnectorTaskReference(
        task_id=record.task_id,
        grant_id=record.grant_id,
        request_id=record.request_id,
        task_type=record.task_type,
        task_status=record.task_status,
        retry_count=record.retry_count,
        max_retry_count=record.max_retry_count,
        last_error_code=record.last_error_code,
        last_error_message=record.last_error_message,
        scheduled_at=record.scheduled_at,
        processed_at=record.processed_at,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def build_session_context_reference(
    record: SessionContextRecord | None,
) -> SessionContextReference | None:
    if record is None:
        return None
    return SessionContextReference(
        global_session_id=record.global_session_id,
        grant_id=record.grant_id,
        request_id=record.request_id,
        agent_id=record.agent_id,
        user_id=record.user_id,
        task_session_id=record.task_session_id,
        connector_session_ref=record.connector_session_ref,
        session_status=record.session_status,
        revocation_reason=record.revocation_reason,
        last_sync_at=record.last_sync_at,
        revoked_at=record.revoked_at,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


def build_approval_record_reference(
    record: ApprovalRecordRecord | None,
) -> ApprovalRecordReference | None:
    if record is None:
        return None
    return ApprovalRecordReference(
        approval_id=record.approval_id,
        request_id=record.request_id,
        external_approval_id=record.external_approval_id,
        approval_node=record.approval_node,
        approver_id=record.approver_id,
        approval_status=record.approval_status,
        submitted_at=record.submitted_at,
        approved_at=record.approved_at,
        rejected_at=record.rejected_at,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )
