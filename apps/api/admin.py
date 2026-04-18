from __future__ import annotations

from dataclasses import asdict
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from packages.application import (
    FailedTaskQueryInput,
    FailedTaskService,
    RetryConnectorTaskInput,
    SessionAuthority,
    ProvisioningService,
)
from packages.domain import DomainError, ErrorCode, OperatorType
from packages.infrastructure import (
    AccessGrantRepository,
    AgentIdentityRepository,
    ApprovalRecordRepository,
    AuditRecordRepository,
    ConnectorTaskRepository,
    PermissionRequestEventRepository,
    PermissionRequestRepository,
    SessionContextRepository,
    create_feishu_permission_connector,
    create_feishu_session_connector,
)

from .dependencies import ApiRequestContext, get_db_session, get_request_context
from .management_models import FailedTaskItemModel

router = APIRouter(tags=["admin"])

_FAILED_TASK_QUERY_OPERATORS = frozenset(
    {
        OperatorType.IT_ADMIN,
        OperatorType.SECURITY_ADMIN,
        OperatorType.SYSTEM,
    }
)
_RETRY_OPERATORS = frozenset({OperatorType.IT_ADMIN, OperatorType.SYSTEM})


class FailedTaskPageModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[FailedTaskItemModel]
    page: int
    page_size: int
    total: int


class FailedTaskListResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str
    data: FailedTaskPageModel


class RetryConnectorTaskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str


class RetryConnectorTaskData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    original_task_id: str
    retry_task_id: str | None = None
    task_type: str
    task_status: str
    request_id: str
    grant_id: str
    global_session_id: str | None = None
    request_status: str
    grant_status: str
    session_status: str | None = None


class RetryConnectorTaskResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: str
    data: RetryConnectorTaskData


def build_failed_task_service(session: Session) -> FailedTaskService:
    session_authority = SessionAuthority(
        permission_request_repository=PermissionRequestRepository(session),
        access_grant_repository=AccessGrantRepository(session),
        session_context_repository=SessionContextRepository(session),
        permission_request_event_repository=PermissionRequestEventRepository(session),
        audit_repository=AuditRecordRepository(session),
        connector_task_repository=ConnectorTaskRepository(session),
        agent_identity_repository=AgentIdentityRepository(session),
        connector=create_feishu_session_connector(),
    )
    provisioning_service = ProvisioningService(
        permission_request_repository=PermissionRequestRepository(session),
        access_grant_repository=AccessGrantRepository(session),
        connector_task_repository=ConnectorTaskRepository(session),
        permission_request_event_repository=PermissionRequestEventRepository(session),
        audit_repository=AuditRecordRepository(session),
        connector=create_feishu_permission_connector(),
        session_authority=session_authority,
    )
    return FailedTaskService(
        permission_request_repository=PermissionRequestRepository(session),
        access_grant_repository=AccessGrantRepository(session),
        connector_task_repository=ConnectorTaskRepository(session),
        session_context_repository=SessionContextRepository(session),
        approval_record_repository=ApprovalRecordRepository(session),
        audit_repository=AuditRecordRepository(session),
        provisioning_service=provisioning_service,
        session_authority=session_authority,
    )


def _require_operator(
    *,
    context: ApiRequestContext,
    allowed: frozenset[OperatorType],
    message: str,
) -> None:
    if context.operator_type in allowed:
        return
    raise DomainError(
        ErrorCode.FORBIDDEN,
        message=message,
        details={"operator_type": context.operator_type.value, "http_status": 403},
    )


@router.get("/admin/failed-tasks", response_model=FailedTaskListResponse)
def list_failed_tasks(
    context: Annotated[ApiRequestContext, Depends(get_request_context)],
    session: Annotated[Session, Depends(get_db_session)],
    task_type: str | None = None,
    task_status: str | None = None,
    request_id: str | None = None,
    grant_id: str | None = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> FailedTaskListResponse:
    _require_operator(
        context=context,
        allowed=_FAILED_TASK_QUERY_OPERATORS,
        message="Operator is not allowed to query failed tasks",
    )
    result = build_failed_task_service(session).list_failed_tasks(
        FailedTaskQueryInput(
            task_type=task_type,
            task_status=task_status,
            request_id=request_id,
            grant_id=grant_id,
            page=page,
            page_size=page_size,
        )
    )
    return FailedTaskListResponse(
        request_id=context.request_id,
        data=FailedTaskPageModel(
            items=[FailedTaskItemModel(**asdict(item)) for item in result.items],
            page=result.page,
            page_size=result.page_size,
            total=result.total,
        ),
    )


@router.post("/admin/connector-tasks/{task_id}/retry", response_model=RetryConnectorTaskResponse)
def retry_connector_task(
    task_id: str,
    payload: RetryConnectorTaskRequest,
    context: Annotated[ApiRequestContext, Depends(get_request_context)],
    session: Annotated[Session, Depends(get_db_session)],
) -> RetryConnectorTaskResponse:
    _require_operator(
        context=context,
        allowed=_RETRY_OPERATORS,
        message="Operator is not allowed to retry connector tasks",
    )
    service = build_failed_task_service(session)
    try:
        result = service.retry_connector_task(
            RetryConnectorTaskInput(
                task_id=task_id,
                reason=payload.reason,
                api_request_id=context.request_id,
                operator_user_id=context.user_id,
                operator_type=context.operator_type,
                trace_id=context.trace_id,
            )
        )
    except DomainError:
        session.commit()
        raise
    session.commit()
    return RetryConnectorTaskResponse(
        request_id=context.request_id,
        data=RetryConnectorTaskData(**asdict(result)),
    )
