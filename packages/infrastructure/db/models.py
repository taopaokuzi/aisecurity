from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    desc,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from packages.domain import (
    ACTOR_TYPE_VALUES,
    AGENT_STATUS_VALUES,
    AGENT_TYPE_VALUES,
    APPROVAL_STATUS_VALUES,
    AUDIT_RESULT_VALUES,
    CONNECTOR_STATUS_VALUES,
    DELEGATION_STATUS_VALUES,
    GRANT_STATUS_VALUES,
    IDENTITY_SOURCE_VALUES,
    OPERATOR_TYPE_VALUES,
    REQUEST_STATUS_VALUES,
    RISK_LEVEL_VALUES,
    TASK_STATUS_VALUES,
    USER_STATUS_VALUES,
)

from .base import Base, TimestampMixin, enum_check_constraint, prefixed_id_column

JSONObject = dict[str, Any]
NOTIFICATION_TASK_STATUS_VALUES = (*TASK_STATUS_VALUES, "Cancelled")


class UserRecord(TimestampMixin, Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("employee_no", name="uk_users_employee_no"),
        Index("idx_users_department_id", "department_id"),
        enum_check_constraint("user_status", USER_STATUS_VALUES, "ck_users_user_status"),
        enum_check_constraint(
            "identity_source",
            IDENTITY_SOURCE_VALUES,
            "ck_users_identity_source",
        ),
    )

    user_id: Mapped[str] = prefixed_id_column()
    employee_no: Mapped[str | None] = mapped_column(String(64), nullable=True)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    email: Mapped[str | None] = mapped_column(String(256), nullable=True)
    department_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    department_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    manager_user_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    user_status: Mapped[str] = mapped_column(String(32), nullable=False)
    identity_source: Mapped[str] = mapped_column(String(32), nullable=False)


class AgentIdentityRecord(TimestampMixin, Base):
    __tablename__ = "agent_identities"
    __table_args__ = (
        Index("idx_agent_identities_agent_status", "agent_status"),
        enum_check_constraint("agent_type", AGENT_TYPE_VALUES, "ck_agent_identities_agent_type"),
        enum_check_constraint(
            "agent_status",
            AGENT_STATUS_VALUES,
            "ck_agent_identities_agent_status",
        ),
    )

    agent_id: Mapped[str] = prefixed_id_column()
    agent_name: Mapped[str] = mapped_column(String(128), nullable=False)
    agent_version: Mapped[str] = mapped_column(String(32), nullable=False)
    agent_type: Mapped[str] = mapped_column(String(32), nullable=False)
    agent_status: Mapped[str] = mapped_column(String(32), nullable=False)
    capability_scope_json: Mapped[JSONObject | None] = mapped_column(JSONB, nullable=True)


class DelegationCredentialRecord(TimestampMixin, Base):
    __tablename__ = "delegation_credentials"
    __table_args__ = (
        Index(
            "idx_delegation_credentials_user_agent_status",
            "user_id",
            "agent_id",
            "delegation_status",
        ),
        Index("idx_delegation_credentials_expire_at", "expire_at"),
        enum_check_constraint(
            "delegation_status",
            DELEGATION_STATUS_VALUES,
            "ck_delegation_credentials_delegation_status",
        ),
    )

    delegation_id: Mapped[str] = prefixed_id_column()
    user_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("users.user_id", name="fk_delegation_credentials_users"),
        nullable=False,
    )
    agent_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("agent_identities.agent_id", name="fk_delegation_credentials_agents"),
        nullable=False,
    )
    task_scope: Mapped[str] = mapped_column(String(64), nullable=False)
    scope_json: Mapped[JSONObject] = mapped_column(JSONB, nullable=False)
    delegation_status: Mapped[str] = mapped_column(String(32), nullable=False)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expire_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revocation_reason: Mapped[str | None] = mapped_column(String(256), nullable=True)


class PermissionRequestRecord(TimestampMixin, Base):
    __tablename__ = "permission_requests"
    __table_args__ = (
        Index("idx_permission_requests_user_created_at", "user_id", desc("created_at")),
        Index(
            "idx_permission_requests_status_updated_at",
            "request_status",
            desc("updated_at"),
        ),
        Index("idx_permission_requests_approval_status", "approval_status"),
        Index("idx_permission_requests_risk_level", "risk_level"),
        enum_check_constraint(
            "approval_status",
            APPROVAL_STATUS_VALUES,
            "ck_permission_requests_approval_status",
        ),
        enum_check_constraint("grant_status", GRANT_STATUS_VALUES, "ck_permission_requests_grant_status"),
        enum_check_constraint(
            "request_status",
            REQUEST_STATUS_VALUES,
            "ck_permission_requests_request_status",
        ),
        enum_check_constraint("risk_level", RISK_LEVEL_VALUES, "ck_permission_requests_risk_level"),
        enum_check_constraint(
            "current_task_state",
            TASK_STATUS_VALUES,
            "ck_permission_requests_current_task_state",
        ),
        CheckConstraint("renew_round >= 0", name="ck_permission_requests_renew_round"),
    )

    request_id: Mapped[str] = prefixed_id_column()
    user_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("users.user_id", name="fk_permission_requests_users"),
        nullable=False,
    )
    agent_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("agent_identities.agent_id", name="fk_permission_requests_agents"),
        nullable=False,
    )
    delegation_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey(
            "delegation_credentials.delegation_id",
            name="fk_permission_requests_delegations",
        ),
        nullable=False,
    )
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    resource_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    resource_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    action: Mapped[str | None] = mapped_column(String(32), nullable=True)
    constraints_json: Mapped[JSONObject | None] = mapped_column(JSONB, nullable=True)
    requested_duration: Mapped[str | None] = mapped_column(String(32), nullable=True)
    structured_request_json: Mapped[JSONObject | None] = mapped_column(JSONB, nullable=True)
    suggested_permission: Mapped[str | None] = mapped_column(String(256), nullable=True)
    risk_level: Mapped[str | None] = mapped_column(String(32), nullable=True)
    approval_status: Mapped[str] = mapped_column(String(32), nullable=False)
    grant_status: Mapped[str] = mapped_column(String(32), nullable=False)
    request_status: Mapped[str] = mapped_column(String(32), nullable=False)
    current_task_state: Mapped[str | None] = mapped_column(String(32), nullable=True)
    policy_version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    renew_round: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    failed_reason: Mapped[str | None] = mapped_column(String(256), nullable=True)


class PermissionRequestEventRecord(Base):
    __tablename__ = "permission_request_events"
    __table_args__ = (
        Index(
            "idx_permission_request_events_request_id",
            "request_id",
            desc("occurred_at"),
        ),
        Index("idx_permission_request_events_event_type", "event_type"),
        enum_check_constraint(
            "operator_type",
            OPERATOR_TYPE_VALUES,
            "ck_permission_request_events_operator_type",
        ),
        enum_check_constraint(
            "from_request_status",
            REQUEST_STATUS_VALUES,
            "ck_permission_request_events_from_request_status",
        ),
        enum_check_constraint(
            "to_request_status",
            REQUEST_STATUS_VALUES,
            "ck_permission_request_events_to_request_status",
        ),
    )

    event_id: Mapped[str] = prefixed_id_column()
    request_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey(
            "permission_requests.request_id",
            name="fk_permission_request_events_requests",
        ),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    operator_type: Mapped[str] = mapped_column(String(32), nullable=False)
    operator_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    from_request_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    to_request_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    metadata_json: Mapped[JSONObject | None] = mapped_column(JSONB, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ApprovalRecordRecord(TimestampMixin, Base):
    __tablename__ = "approval_records"
    __table_args__ = (
        UniqueConstraint(
            "external_approval_id",
            name="uk_approval_records_external_approval_id",
        ),
        UniqueConstraint(
            "idempotency_key",
            name="uk_approval_records_idempotency_key",
        ),
        Index("idx_approval_records_request_id", "request_id"),
        Index("idx_approval_records_status", "approval_status"),
        enum_check_constraint(
            "approval_status",
            APPROVAL_STATUS_VALUES,
            "ck_approval_records_approval_status",
        ),
    )

    approval_id: Mapped[str] = prefixed_id_column()
    request_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("permission_requests.request_id", name="fk_approval_records_requests"),
        nullable=False,
    )
    external_approval_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    approval_node: Mapped[str] = mapped_column(String(64), nullable=False)
    approver_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    approval_status: Mapped[str] = mapped_column(String(32), nullable=False)
    callback_payload_json: Mapped[JSONObject | None] = mapped_column(JSONB, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(128), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AccessGrantRecord(TimestampMixin, Base):
    __tablename__ = "access_grants"
    __table_args__ = (
        Index("idx_access_grants_request_id", "request_id"),
        Index("idx_access_grants_status_expire_at", "grant_status", "expire_at"),
        Index("idx_access_grants_resource_action", "resource_key", "action"),
        enum_check_constraint("grant_status", GRANT_STATUS_VALUES, "ck_access_grants_grant_status"),
        enum_check_constraint(
            "connector_status",
            CONNECTOR_STATUS_VALUES,
            "ck_access_grants_connector_status",
        ),
    )

    grant_id: Mapped[str] = prefixed_id_column()
    request_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("permission_requests.request_id", name="fk_access_grants_requests"),
        nullable=False,
    )
    resource_key: Mapped[str] = mapped_column(String(128), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(32), nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    grant_status: Mapped[str] = mapped_column(String(32), nullable=False)
    connector_status: Mapped[str] = mapped_column(String(32), nullable=False)
    reconcile_status: Mapped[str] = mapped_column(String(32), nullable=False)
    effective_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expire_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revocation_reason: Mapped[str | None] = mapped_column(String(256), nullable=True)


class ConnectorTaskRecord(TimestampMixin, Base):
    __tablename__ = "connector_tasks"
    __table_args__ = (
        Index("idx_connector_tasks_grant_id_status", "grant_id", "task_status"),
        Index("idx_connector_tasks_scheduled_at", "task_status", "scheduled_at"),
        enum_check_constraint("task_status", TASK_STATUS_VALUES, "ck_connector_tasks_task_status"),
        CheckConstraint("retry_count >= 0", name="ck_connector_tasks_retry_count"),
        CheckConstraint("max_retry_count >= 0", name="ck_connector_tasks_max_retry_count"),
    )

    task_id: Mapped[str] = prefixed_id_column()
    grant_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("access_grants.grant_id", name="fk_connector_tasks_grants"),
        nullable=False,
    )
    request_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("permission_requests.request_id", name="fk_connector_tasks_requests"),
        nullable=False,
    )
    task_type: Mapped[str] = mapped_column(String(32), nullable=False)
    task_status: Mapped[str] = mapped_column(String(32), nullable=False)
    retry_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    max_retry_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=3,
        server_default=text("3"),
    )
    last_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_error_message: Mapped[str | None] = mapped_column(String(256), nullable=True)
    payload_json: Mapped[JSONObject | None] = mapped_column(JSONB, nullable=True)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class NotificationTaskRecord(TimestampMixin, Base):
    __tablename__ = "notification_tasks"
    __table_args__ = (
        Index("idx_notification_tasks_grant_id_status", "grant_id", "task_status"),
        Index("idx_notification_tasks_scheduled_at", "task_status", "scheduled_at"),
        enum_check_constraint(
            "task_status",
            NOTIFICATION_TASK_STATUS_VALUES,
            "ck_notification_tasks_task_status",
        ),
    )

    task_id: Mapped[str] = prefixed_id_column()
    grant_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("access_grants.grant_id", name="fk_notification_tasks_grants"),
        nullable=False,
    )
    request_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("permission_requests.request_id", name="fk_notification_tasks_requests"),
        nullable=False,
    )
    task_type: Mapped[str] = mapped_column(String(32), nullable=False)
    task_status: Mapped[str] = mapped_column(String(32), nullable=False)
    last_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_error_message: Mapped[str | None] = mapped_column(String(256), nullable=True)
    payload_json: Mapped[JSONObject | None] = mapped_column(JSONB, nullable=True)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditRecordRecord(Base):
    __tablename__ = "audit_records"
    __table_args__ = (
        Index("idx_audit_records_request_id_created_at", "request_id", desc("created_at")),
        Index("idx_audit_records_event_type_created_at", "event_type", desc("created_at")),
        Index("idx_audit_records_actor", "actor_type", "actor_id", desc("created_at")),
        enum_check_constraint("actor_type", ACTOR_TYPE_VALUES, "ck_audit_records_actor_type"),
        enum_check_constraint("result", AUDIT_RESULT_VALUES, "ck_audit_records_result"),
    )

    audit_id: Mapped[str] = prefixed_id_column()
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(32), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    subject_chain: Mapped[str | None] = mapped_column(String(512), nullable=True)
    result: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(256), nullable=True)
    metadata_json: Mapped[JSONObject | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
