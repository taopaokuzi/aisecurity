from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from packages.application import (
    PermissionRequestCreateInput,
    PermissionRequestListInput,
    PermissionRequestListResult,
    PermissionRequestService,
)
from packages.domain import ApprovalStatus, PermissionRequest, RequestStatus
from packages.infrastructure import (
    AgentIdentityRepository,
    AuditRecordRepository,
    DelegationCredentialRepository,
    PermissionRequestEventRepository,
    PermissionRequestRepository,
    UserRepository,
)

from .dependencies import ApiRequestContext, get_db_session, get_request_context

router = APIRouter(tags=["permission-requests"])


class CreatePermissionRequestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str
    agent_id: str
    delegation_id: str
    conversation_id: str | None = None


class PermissionRequestCreateData(BaseModel):
    permission_request_id: str
    request_status: str
    next_action: str


class PermissionRequestCreateResponse(BaseModel):
    request_id: str
    data: PermissionRequestCreateData


class PermissionRequestData(BaseModel):
    request_id: str
    user_id: str
    agent_id: str
    delegation_id: str
    raw_text: str
    resource_key: str | None = None
    resource_type: str | None = None
    action: str | None = None
    suggested_permission: str | None = None
    risk_level: str | None = None
    approval_status: str
    grant_status: str
    request_status: str
    policy_version: str | None = None
    created_at: datetime
    updated_at: datetime


class PermissionRequestDetailResponse(BaseModel):
    request_id: str
    data: PermissionRequestData


class PermissionRequestListData(BaseModel):
    items: list[PermissionRequestData]
    page: int
    page_size: int
    total: int


class PermissionRequestListResponse(BaseModel):
    request_id: str
    data: PermissionRequestListData


def build_permission_request_service(session: Session) -> PermissionRequestService:
    return PermissionRequestService(
        user_repository=UserRepository(session),
        agent_repository=AgentIdentityRepository(session),
        delegation_repository=DelegationCredentialRepository(session),
        permission_request_repository=PermissionRequestRepository(session),
        permission_request_event_repository=PermissionRequestEventRepository(session),
        audit_repository=AuditRecordRepository(session),
    )


def build_permission_request_data(
    permission_request: PermissionRequest,
) -> PermissionRequestData:
    risk_level = permission_request.risk_level.value if permission_request.risk_level else None
    return PermissionRequestData(
        request_id=permission_request.request_id,
        user_id=permission_request.user_id,
        agent_id=permission_request.agent_id,
        delegation_id=permission_request.delegation_id,
        raw_text=permission_request.raw_text,
        resource_key=permission_request.resource_key,
        resource_type=permission_request.resource_type,
        action=permission_request.action,
        suggested_permission=permission_request.suggested_permission,
        risk_level=risk_level,
        approval_status=permission_request.approval_status.value,
        grant_status=permission_request.grant_status.value,
        request_status=permission_request.request_status.value,
        policy_version=permission_request.policy_version,
        created_at=permission_request.created_at,
        updated_at=permission_request.updated_at,
    )


def build_create_response(
    *,
    request_id: str,
    permission_request: PermissionRequest,
) -> PermissionRequestCreateResponse:
    return PermissionRequestCreateResponse(
        request_id=request_id,
        data=PermissionRequestCreateData(
            permission_request_id=permission_request.request_id,
            request_status=permission_request.request_status.value,
            next_action=RequestStatus.EVALUATING.value,
        ),
    )


def build_detail_response(
    *,
    request_id: str,
    permission_request: PermissionRequest,
) -> PermissionRequestDetailResponse:
    return PermissionRequestDetailResponse(
        request_id=request_id,
        data=build_permission_request_data(permission_request),
    )


def build_list_response(
    *,
    request_id: str,
    result: PermissionRequestListResult,
) -> PermissionRequestListResponse:
    return PermissionRequestListResponse(
        request_id=request_id,
        data=PermissionRequestListData(
            items=[build_permission_request_data(item) for item in result.items],
            page=result.page,
            page_size=result.page_size,
            total=result.total,
        ),
    )


@router.post("/permission-requests", response_model=PermissionRequestCreateResponse)
def create_permission_request(
    payload: CreatePermissionRequestRequest,
    context: Annotated[ApiRequestContext, Depends(get_request_context)],
    session: Annotated[Session, Depends(get_db_session)],
) -> PermissionRequestCreateResponse:
    service = build_permission_request_service(session)
    permission_request = service.create_permission_request(
        PermissionRequestCreateInput(
            user_id=context.user_id,
            agent_id=payload.agent_id,
            delegation_id=payload.delegation_id,
            message=payload.message,
            conversation_id=payload.conversation_id,
            request_id=context.request_id,
            operator_type=context.operator_type,
            trace_id=context.trace_id,
            idempotency_key=context.idempotency_key,
        )
    )
    session.commit()
    return build_create_response(
        request_id=context.request_id,
        permission_request=permission_request,
    )


@router.get("/permission-requests/{permission_request_id}", response_model=PermissionRequestDetailResponse)
def get_permission_request(
    permission_request_id: str,
    context: Annotated[ApiRequestContext, Depends(get_request_context)],
    session: Annotated[Session, Depends(get_db_session)],
) -> PermissionRequestDetailResponse:
    service = build_permission_request_service(session)
    permission_request = service.get_permission_request(
        permission_request_id,
        requester_user_id=context.user_id,
        operator_type=context.operator_type,
    )
    return build_detail_response(
        request_id=context.request_id,
        permission_request=permission_request,
    )


@router.get("/permission-requests", response_model=PermissionRequestListResponse)
def list_permission_requests(
    context: Annotated[ApiRequestContext, Depends(get_request_context)],
    session: Annotated[Session, Depends(get_db_session)],
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    request_status: RequestStatus | None = Query(None),
    approval_status: ApprovalStatus | None = Query(None),
    mine_only: bool = Query(True),
) -> PermissionRequestListResponse:
    service = build_permission_request_service(session)
    result = service.list_permission_requests(
        PermissionRequestListInput(
            requester_user_id=context.user_id,
            operator_type=context.operator_type,
            page=page,
            page_size=page_size,
            request_status=request_status,
            approval_status=approval_status,
            mine_only=mine_only,
        )
    )
    return build_list_response(request_id=context.request_id, result=result)
