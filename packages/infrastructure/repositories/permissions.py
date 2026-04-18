from __future__ import annotations

from datetime import datetime

from sqlalchemy import Select, func, select

from packages.infrastructure.db.models import (
    AccessGrantRecord,
    ApprovalRecordRecord,
    AuditRecordRecord,
    ConnectorTaskRecord,
    NotificationTaskRecord,
    PermissionRequestEventRecord,
    PermissionRequestRecord,
    SessionContextRecord,
)

from .base import SqlAlchemyRepository


class PermissionRequestRepository(SqlAlchemyRepository[PermissionRequestRecord]):
    model = PermissionRequestRecord

    def list_paginated(
        self,
        *,
        user_id: str | None = None,
        request_status: str | None = None,
        approval_status: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[PermissionRequestRecord], int]:
        filters = []
        if user_id is not None:
            filters.append(PermissionRequestRecord.user_id == user_id)
        if request_status is not None:
            filters.append(PermissionRequestRecord.request_status == request_status)
        if approval_status is not None:
            filters.append(PermissionRequestRecord.approval_status == approval_status)

        statement = self._apply_filters(select(PermissionRequestRecord), filters).order_by(
            PermissionRequestRecord.created_at.desc()
        )
        statement = statement.offset((page - 1) * page_size).limit(page_size)

        count_statement = self._apply_filters(
            select(func.count()).select_from(PermissionRequestRecord),
            filters,
        )
        total = self.session.scalar(count_statement) or 0
        return self.scalars(statement), int(total)

    def list_for_user(self, user_id: str, *, limit: int | None = 100) -> list[PermissionRequestRecord]:
        statement = (
            select(PermissionRequestRecord)
            .where(PermissionRequestRecord.user_id == user_id)
            .order_by(PermissionRequestRecord.created_at.desc())
        )
        if limit is not None:
            statement = statement.limit(limit)
        return self.scalars(statement)

    def _apply_filters(
        self,
        statement: Select,
        filters: list[object],
    ) -> Select:
        if not filters:
            return statement
        return statement.where(*filters)

    def list_by_status(
        self,
        request_status: str,
        *,
        limit: int | None = 100,
    ) -> list[PermissionRequestRecord]:
        statement = (
            select(PermissionRequestRecord)
            .where(PermissionRequestRecord.request_status == request_status)
            .order_by(PermissionRequestRecord.updated_at.desc())
        )
        if limit is not None:
            statement = statement.limit(limit)
        return self.scalars(statement)


class PermissionRequestEventRepository(SqlAlchemyRepository[PermissionRequestEventRecord]):
    model = PermissionRequestEventRecord

    def list_for_request(self, request_id: str, *, limit: int | None = 100) -> list[PermissionRequestEventRecord]:
        statement = (
            select(PermissionRequestEventRecord)
            .where(PermissionRequestEventRecord.request_id == request_id)
            .order_by(PermissionRequestEventRecord.occurred_at.desc())
        )
        if limit is not None:
            statement = statement.limit(limit)
        return self.scalars(statement)


class ApprovalRecordRepository(SqlAlchemyRepository[ApprovalRecordRecord]):
    model = ApprovalRecordRecord

    def get_by_external_approval_id(self, external_approval_id: str) -> ApprovalRecordRecord | None:
        statement = select(ApprovalRecordRecord).where(
            ApprovalRecordRecord.external_approval_id == external_approval_id
        )
        return self.session.scalar(statement)

    def get_by_idempotency_key(self, idempotency_key: str) -> ApprovalRecordRecord | None:
        statement = select(ApprovalRecordRecord).where(
            ApprovalRecordRecord.idempotency_key == idempotency_key
        )
        return self.session.scalar(statement)

    def list_for_request(self, request_id: str) -> list[ApprovalRecordRecord]:
        statement = (
            select(ApprovalRecordRecord)
            .where(ApprovalRecordRecord.request_id == request_id)
            .order_by(ApprovalRecordRecord.created_at.desc())
        )
        return self.scalars(statement)


class AccessGrantRepository(SqlAlchemyRepository[AccessGrantRecord]):
    model = AccessGrantRecord

    def get_by_request_id(self, request_id: str) -> AccessGrantRecord | None:
        statement = (
            select(AccessGrantRecord)
            .where(AccessGrantRecord.request_id == request_id)
            .order_by(AccessGrantRecord.created_at.desc())
        )
        return self.session.scalar(statement)

    def list_for_request(self, request_id: str) -> list[AccessGrantRecord]:
        statement = (
            select(AccessGrantRecord)
            .where(AccessGrantRecord.request_id == request_id)
            .order_by(AccessGrantRecord.created_at.desc())
        )
        return self.scalars(statement)

    def list_expiring_before(self, cutoff: datetime) -> list[AccessGrantRecord]:
        statement = (
            select(AccessGrantRecord)
            .where(AccessGrantRecord.expire_at <= cutoff)
            .order_by(AccessGrantRecord.expire_at.asc())
        )
        return self.scalars(statement)

    def list_due_for_expiring(
        self,
        *,
        current_time: datetime,
        cutoff: datetime,
    ) -> list[AccessGrantRecord]:
        statement = (
            select(AccessGrantRecord)
            .where(AccessGrantRecord.expire_at > current_time)
            .where(AccessGrantRecord.expire_at <= cutoff)
            .where(
                AccessGrantRecord.grant_status.in_(
                    [
                        "Active",
                        "Expiring",
                    ]
                )
            )
            .order_by(AccessGrantRecord.expire_at.asc())
        )
        return self.scalars(statement)

    def list_due_for_expiration(self, *, current_time: datetime) -> list[AccessGrantRecord]:
        statement = (
            select(AccessGrantRecord)
            .where(AccessGrantRecord.expire_at <= current_time)
            .where(
                AccessGrantRecord.grant_status.in_(
                    [
                        "Active",
                        "Expiring",
                    ]
                )
            )
            .order_by(AccessGrantRecord.expire_at.asc())
        )
        return self.scalars(statement)


class ConnectorTaskRepository(SqlAlchemyRepository[ConnectorTaskRecord]):
    model = ConnectorTaskRecord

    def list_for_grant(self, grant_id: str) -> list[ConnectorTaskRecord]:
        statement = (
            select(ConnectorTaskRecord)
            .where(ConnectorTaskRecord.grant_id == grant_id)
            .order_by(ConnectorTaskRecord.created_at.desc())
        )
        return self.scalars(statement)

    def get_latest_for_grant(self, grant_id: str) -> ConnectorTaskRecord | None:
        statement = (
            select(ConnectorTaskRecord)
            .where(ConnectorTaskRecord.grant_id == grant_id)
            .order_by(ConnectorTaskRecord.created_at.desc())
        )
        return self.session.scalar(statement)

    def list_for_request(self, request_id: str) -> list[ConnectorTaskRecord]:
        statement = (
            select(ConnectorTaskRecord)
            .where(ConnectorTaskRecord.request_id == request_id)
            .order_by(ConnectorTaskRecord.created_at.desc())
        )
        return self.scalars(statement)

    def get_latest_session_revoke_for_session(
        self,
        *,
        global_session_id: str,
    ) -> ConnectorTaskRecord | None:
        statement = (
            select(ConnectorTaskRecord)
            .where(ConnectorTaskRecord.task_type == "session_revoke")
            .where(ConnectorTaskRecord.payload_json.contains({"global_session_id": global_session_id}))
            .order_by(ConnectorTaskRecord.created_at.desc())
        )
        return self.session.scalar(statement)

    def list_pending_session_revoke_tasks(
        self,
        *,
        limit: int | None = 100,
    ) -> list[ConnectorTaskRecord]:
        statement = (
            select(ConnectorTaskRecord)
            .where(ConnectorTaskRecord.task_type == "session_revoke")
            .where(
                ConnectorTaskRecord.task_status.in_(
                    [
                        "Pending",
                        "Retrying",
                    ]
                )
            )
            .order_by(ConnectorTaskRecord.scheduled_at.asc(), ConnectorTaskRecord.created_at.asc())
        )
        if limit is not None:
            statement = statement.limit(limit)
        return self.scalars(statement)


class NotificationTaskRepository(SqlAlchemyRepository[NotificationTaskRecord]):
    model = NotificationTaskRecord

    def list_for_grant(self, grant_id: str) -> list[NotificationTaskRecord]:
        statement = (
            select(NotificationTaskRecord)
            .where(NotificationTaskRecord.grant_id == grant_id)
            .order_by(NotificationTaskRecord.created_at.desc())
        )
        return self.scalars(statement)

    def get_latest_for_grant_and_type(
        self,
        grant_id: str,
        task_type: str,
    ) -> NotificationTaskRecord | None:
        statement = (
            select(NotificationTaskRecord)
            .where(NotificationTaskRecord.grant_id == grant_id)
            .where(NotificationTaskRecord.task_type == task_type)
            .order_by(NotificationTaskRecord.created_at.desc())
        )
        return self.session.scalar(statement)


class AuditRecordRepository(SqlAlchemyRepository[AuditRecordRecord]):
    model = AuditRecordRecord

    def list_for_request(self, request_id: str, *, limit: int | None = 100) -> list[AuditRecordRecord]:
        statement = (
            select(AuditRecordRecord)
            .where(AuditRecordRecord.request_id == request_id)
            .order_by(AuditRecordRecord.created_at.desc())
        )
        if limit is not None:
            statement = statement.limit(limit)
        return self.scalars(statement)

    def get_latest_by_event_and_idempotency_key(
        self,
        *,
        actor_type: str,
        actor_id: str | None,
        event_type: str,
        idempotency_key: str,
    ) -> AuditRecordRecord | None:
        statement = (
            select(AuditRecordRecord)
            .where(AuditRecordRecord.actor_type == actor_type)
            .where(AuditRecordRecord.actor_id == actor_id)
            .where(AuditRecordRecord.event_type == event_type)
            .where(AuditRecordRecord.metadata_json.contains({"idempotency_key": idempotency_key}))
            .order_by(AuditRecordRecord.created_at.desc())
        )
        return self.session.scalar(statement)

    def list_for_actor(
        self,
        *,
        actor_type: str,
        actor_id: str | None,
        limit: int | None = 100,
    ) -> list[AuditRecordRecord]:
        statement = (
            select(AuditRecordRecord)
            .where(AuditRecordRecord.actor_type == actor_type)
            .where(AuditRecordRecord.actor_id == actor_id)
            .order_by(AuditRecordRecord.created_at.desc())
        )
        if limit is not None:
            statement = statement.limit(limit)
        return self.scalars(statement)


class SessionContextRepository(SqlAlchemyRepository[SessionContextRecord]):
    model = SessionContextRecord

    def get_by_grant_id(self, grant_id: str) -> SessionContextRecord | None:
        statement = select(SessionContextRecord).where(SessionContextRecord.grant_id == grant_id)
        return self.session.scalar(statement)

    def list_for_agent(
        self,
        agent_id: str,
        *,
        statuses: list[str] | tuple[str, ...] | None = None,
        limit: int | None = 100,
    ) -> list[SessionContextRecord]:
        statement = (
            select(SessionContextRecord)
            .where(SessionContextRecord.agent_id == agent_id)
            .order_by(SessionContextRecord.updated_at.desc())
        )
        if statuses:
            statement = statement.where(SessionContextRecord.session_status.in_(statuses))
        if limit is not None:
            statement = statement.limit(limit)
        return self.scalars(statement)

    def list_for_statuses(
        self,
        statuses: list[str] | tuple[str, ...],
        *,
        limit: int | None = 100,
    ) -> list[SessionContextRecord]:
        statement = (
            select(SessionContextRecord)
            .where(SessionContextRecord.session_status.in_(statuses))
            .order_by(SessionContextRecord.updated_at.asc())
        )
        if limit is not None:
            statement = statement.limit(limit)
        return self.scalars(statement)
