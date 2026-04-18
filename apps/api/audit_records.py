from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from packages.application import AuditQueryInput, AuditQueryService
from packages.domain import DomainError, ErrorCode, OperatorType
from packages.infrastructure import (
    AccessGrantRepository,
    ApprovalRecordRepository,
    AuditRecordRepository,
    ConnectorTaskRepository,
    PermissionRequestRepository,
    SessionContextRepository,
)

from .dependencies import ApiRequestContext, get_db_session, get_request_context
from .management_models import AuditRecordItemModel

router = APIRouter(tags=["audit"])

_AUDIT_QUERY_OPERATORS = frozenset(
    {
        OperatorType.IT_ADMIN,
        OperatorType.SECURITY_ADMIN,
        OperatorType.SYSTEM,
    }
)


class AuditRecordPageModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[AuditRecordItemModel]
    page: int
    page_size: int
    total: int


class AuditRecordListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str
    data: AuditRecordPageModel


def build_audit_query_service(session: Session) -> AuditQueryService:
    return AuditQueryService(
        audit_repository=AuditRecordRepository(session),
        permission_request_repository=PermissionRequestRepository(session),
        access_grant_repository=AccessGrantRepository(session),
        connector_task_repository=ConnectorTaskRepository(session),
        session_context_repository=SessionContextRepository(session),
        approval_record_repository=ApprovalRecordRepository(session),
    )


def _require_operator(context: ApiRequestContext) -> None:
    if context.operator_type in _AUDIT_QUERY_OPERATORS:
        return
    raise DomainError(
        ErrorCode.FORBIDDEN,
        message="Operator is not allowed to query audit records",
        details={"operator_type": context.operator_type.value, "http_status": 403},
    )


@router.get("/audit-records", response_model=AuditRecordListResponse)
def list_audit_records(
    context: Annotated[ApiRequestContext, Depends(get_request_context)],
    session: Annotated[Session, Depends(get_db_session)],
    request_id: str | None = None,
    event_type: str | None = None,
    actor_type: str | None = None,
    actor_id: str | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> AuditRecordListResponse:
    _require_operator(context)
    result = build_audit_query_service(session).search(
        AuditQueryInput(
            request_id=request_id,
            event_type=event_type,
            actor_type=actor_type,
            actor_id=actor_id,
            created_from=created_from,
            created_to=created_to,
            page=page,
            page_size=page_size,
        )
    )
    return AuditRecordListResponse(
        request_id=context.request_id,
        data=AuditRecordPageModel(
            items=[AuditRecordItemModel(**asdict(item)) for item in result.items],
            page=result.page,
            page_size=result.page_size,
            total=result.total,
        ),
    )
