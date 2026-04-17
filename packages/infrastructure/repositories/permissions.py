from __future__ import annotations

from datetime import datetime

from sqlalchemy import select

from packages.infrastructure.db.models import (
    AccessGrantRecord,
    ApprovalRecordRecord,
    AuditRecordRecord,
    PermissionRequestEventRecord,
    PermissionRequestRecord,
)

from .base import SqlAlchemyRepository


class PermissionRequestRepository(SqlAlchemyRepository[PermissionRequestRecord]):
    model = PermissionRequestRecord

    def list_for_user(self, user_id: str, *, limit: int | None = 100) -> list[PermissionRequestRecord]:
        statement = (
            select(PermissionRequestRecord)
            .where(PermissionRequestRecord.user_id == user_id)
            .order_by(PermissionRequestRecord.created_at.desc())
        )
        if limit is not None:
            statement = statement.limit(limit)
        return self.scalars(statement)

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
