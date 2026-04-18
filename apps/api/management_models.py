from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class PermissionRequestReferenceModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str
    user_id: str
    agent_id: str
    delegation_id: str
    request_status: str
    approval_status: str
    grant_status: str
    current_task_state: str | None = None
    failed_reason: str | None = None
    created_at: datetime
    updated_at: datetime


class AccessGrantReferenceModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    grant_id: str
    request_id: str
    resource_key: str
    resource_type: str
    action: str
    grant_status: str
    connector_status: str
    reconcile_status: str
    effective_at: datetime | None = None
    expire_at: datetime
    revoked_at: datetime | None = None
    revocation_reason: str | None = None
    created_at: datetime
    updated_at: datetime


class ConnectorTaskReferenceModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: str
    grant_id: str
    request_id: str
    task_type: str
    task_status: str
    retry_count: int
    max_retry_count: int
    last_error_code: str | None = None
    last_error_message: str | None = None
    scheduled_at: datetime
    processed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class SessionContextReferenceModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    global_session_id: str
    grant_id: str
    request_id: str
    agent_id: str
    user_id: str
    task_session_id: str | None = None
    connector_session_ref: str | None = None
    session_status: str
    revocation_reason: str | None = None
    last_sync_at: datetime | None = None
    revoked_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class ApprovalRecordReferenceModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    approval_id: str
    request_id: str
    external_approval_id: str | None = None
    approval_node: str
    approver_id: str | None = None
    approval_status: str
    submitted_at: datetime | None = None
    approved_at: datetime | None = None
    rejected_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class AuditRecordItemModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    audit_id: str
    request_id: str | None = None
    event_type: str
    actor_type: str
    actor_id: str | None = None
    subject_chain: str | None = None
    result: str
    reason: str | None = None
    metadata: dict[str, Any] | None = None
    created_at: datetime
    request: PermissionRequestReferenceModel | None = None
    grant: AccessGrantReferenceModel | None = None
    connector_task: ConnectorTaskReferenceModel | None = None
    session_context: SessionContextReferenceModel | None = None
    approval_record: ApprovalRecordReferenceModel | None = None


class FailedTaskItemModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_source: str
    task_id: str
    task_type: str
    task_status: str
    request_id: str
    grant_id: str | None = None
    global_session_id: str | None = None
    failure_code: str | None = None
    failure_reason: str | None = None
    retryable: bool
    occurred_at: datetime
    request: PermissionRequestReferenceModel | None = None
    grant: AccessGrantReferenceModel | None = None
    connector_task: ConnectorTaskReferenceModel | None = None
    session_context: SessionContextReferenceModel | None = None
    approval_record: ApprovalRecordReferenceModel | None = None
