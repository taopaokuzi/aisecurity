from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping

from packages.domain import ActorType, DomainError, ErrorCode
from packages.infrastructure.db.models import AuditRecordRecord
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


@dataclass(slots=True, frozen=True)
class AuditQueryInput:
    request_id: str | None = None
    event_type: str | None = None
    actor_type: str | None = None
    actor_id: str | None = None
    created_from: datetime | None = None
    created_to: datetime | None = None
    page: int = 1
    page_size: int = 20


@dataclass(slots=True, frozen=True)
class AuditRecordView:
    audit_id: str
    request_id: str | None
    event_type: str
    actor_type: str
    actor_id: str | None
    subject_chain: str | None
    result: str
    reason: str | None
    metadata: Mapping[str, Any] | None
    created_at: datetime
    request: PermissionRequestReference | None
    grant: AccessGrantReference | None
    connector_task: ConnectorTaskReference | None
    session_context: SessionContextReference | None
    approval_record: ApprovalRecordReference | None


@dataclass(slots=True, frozen=True)
class AuditQueryResult:
    items: list[AuditRecordView]
    page: int
    page_size: int
    total: int


class AuditQueryService:
    def __init__(
        self,
        *,
        audit_repository: AuditRecordRepository,
        permission_request_repository: PermissionRequestRepository,
        access_grant_repository: AccessGrantRepository,
        connector_task_repository: ConnectorTaskRepository,
        session_context_repository: SessionContextRepository,
        approval_record_repository: ApprovalRecordRepository,
    ) -> None:
        self.audit_repository = audit_repository
        self.permission_request_repository = permission_request_repository
        self.access_grant_repository = access_grant_repository
        self.connector_task_repository = connector_task_repository
        self.session_context_repository = session_context_repository
        self.approval_record_repository = approval_record_repository

    def search(self, command: AuditQueryInput) -> AuditQueryResult:
        self._validate_time_range(command.created_from, command.created_to)
        actor_type = self._normalize_actor_type(command.actor_type)

        records, total = self.audit_repository.search_paginated(
            request_id=command.request_id,
            event_type=command.event_type,
            actor_type=actor_type,
            actor_id=command.actor_id,
            created_from=command.created_from,
            created_to=command.created_to,
            page=command.page,
            page_size=command.page_size,
        )

        request_ids = {
            record.request_id
            for record in records
            if isinstance(record.request_id, str) and record.request_id.strip()
        }
        requests_by_id = {
            record.request_id: record
            for record in self.permission_request_repository.list_by_ids(request_ids)
        }

        grants_by_request = self._first_grant_by_request(
            self.access_grant_repository.list_for_requests(request_ids)
        )
        explicit_grant_ids = {
            value
            for value in (
                self._metadata_string(record.metadata_json, "grant_id")
                for record in records
            )
            if value is not None
        }
        grant_ids = explicit_grant_ids | {
            record.grant_id for record in grants_by_request.values()
        }
        grants_by_id = {
            record.grant_id: record
            for record in self.access_grant_repository.list_by_ids(grant_ids)
        }

        task_ids = {
            value
            for value in (self._extract_task_id(record) for record in records)
            if value is not None
        }
        tasks_by_id = {
            record.task_id: record
            for record in self.connector_task_repository.list_by_ids(task_ids)
        }

        session_ids = {
            value
            for value in (
                self._metadata_string(record.metadata_json, "global_session_id")
                for record in records
            )
            if value is not None
        }
        sessions_by_id = {
            record.global_session_id: record
            for record in self.session_context_repository.list_by_ids(session_ids)
        }
        sessions_by_grant = {
            record.grant_id: record
            for record in self.session_context_repository.list_by_grant_ids(grant_ids)
        }

        approval_ids = {
            value
            for value in (
                self._metadata_string(record.metadata_json, "approval_id")
                for record in records
            )
            if value is not None
        }
        approvals_by_id = {
            record.approval_id: record
            for record in self.approval_record_repository.list_by_ids(approval_ids)
        }

        items = [
            self._build_audit_view(
                record=record,
                requests_by_id=requests_by_id,
                grants_by_id=grants_by_id,
                grants_by_request=grants_by_request,
                tasks_by_id=tasks_by_id,
                sessions_by_id=sessions_by_id,
                sessions_by_grant=sessions_by_grant,
                approvals_by_id=approvals_by_id,
            )
            for record in records
        ]
        return AuditQueryResult(
            items=items,
            page=command.page,
            page_size=command.page_size,
            total=total,
        )

    def _build_audit_view(
        self,
        *,
        record: AuditRecordRecord,
        requests_by_id: dict[str, Any],
        grants_by_id: dict[str, Any],
        grants_by_request: dict[str, Any],
        tasks_by_id: dict[str, Any],
        sessions_by_id: dict[str, Any],
        sessions_by_grant: dict[str, Any],
        approvals_by_id: dict[str, Any],
    ) -> AuditRecordView:
        metadata = dict(record.metadata_json or {})
        request_record = requests_by_id.get(record.request_id) if record.request_id else None

        grant_id = self._metadata_string(metadata, "grant_id")
        grant_record = grants_by_id.get(grant_id) if grant_id is not None else None
        if grant_record is None and record.request_id is not None:
            grant_record = grants_by_request.get(record.request_id)

        task_record = tasks_by_id.get(self._extract_task_id(record))

        session_id = self._metadata_string(metadata, "global_session_id")
        session_record = sessions_by_id.get(session_id) if session_id is not None else None
        if session_record is None and grant_record is not None:
            session_record = sessions_by_grant.get(grant_record.grant_id)

        approval_record = approvals_by_id.get(self._metadata_string(metadata, "approval_id"))

        return AuditRecordView(
            audit_id=record.audit_id,
            request_id=record.request_id,
            event_type=record.event_type,
            actor_type=record.actor_type,
            actor_id=record.actor_id,
            subject_chain=record.subject_chain,
            result=record.result,
            reason=record.reason,
            metadata=metadata or None,
            created_at=record.created_at,
            request=build_permission_request_reference(request_record),
            grant=build_access_grant_reference(grant_record),
            connector_task=build_connector_task_reference(task_record),
            session_context=build_session_context_reference(session_record),
            approval_record=build_approval_record_reference(approval_record),
        )

    def _extract_task_id(self, record: AuditRecordRecord) -> str | None:
        metadata = dict(record.metadata_json or {})
        for key in ("task_id", "revoke_task_id", "connector_task_id"):
            value = self._metadata_string(metadata, key)
            if value is not None:
                return value
        return None

    def _first_grant_by_request(self, records: list[Any]) -> dict[str, Any]:
        items: dict[str, Any] = {}
        for record in records:
            items.setdefault(record.request_id, record)
        return items

    def _normalize_actor_type(self, actor_type: str | None) -> str | None:
        if actor_type is None:
            return None
        try:
            return ActorType(actor_type).value
        except ValueError as exc:
            raise DomainError(
                ErrorCode.FORBIDDEN,
                message="Actor type filter is invalid",
                details={"actor_type": actor_type, "http_status": 400},
            ) from exc

    def _metadata_string(
        self,
        metadata: Mapping[str, Any],
        key: str,
    ) -> str | None:
        value = metadata.get(key)
        if not isinstance(value, str):
            return None
        normalized = value.strip()
        return normalized or None

    def _validate_time_range(
        self,
        created_from: datetime | None,
        created_to: datetime | None,
    ) -> None:
        if created_from is None or created_to is None:
            return
        if created_from <= created_to:
            return
        raise DomainError(
            ErrorCode.REQUEST_STATUS_INVALID,
            message="created_from must be earlier than or equal to created_to",
            details={"http_status": 400},
        )
