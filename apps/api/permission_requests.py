from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from packages.application import (
    PermissionRequestCreateInput,
    PermissionRequestEvaluationInput,
    PermissionRequestEvaluationResult,
    PermissionRequestEvaluationService,
    PermissionRequestListInput,
    PermissionRequestListResult,
    PermissionRequestService,
)
from packages.domain import ApprovalStatus, DomainError, PermissionRequest, RequestStatus
from packages.infrastructure import (
    AgentIdentityRepository,
    AuditRecordRepository,
    DelegationCredentialRepository,
    PermissionRequestParser,
    PermissionRequestEventRepository,
    PermissionRequestRepository,
    UserRepository,
    create_llm_gateway,
)
from packages.policy import create_policy_engine

from .dependencies import ApiRequestContext, get_db_session, get_request_context
from .approval_submission import submit_request_to_approval_pipeline

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
    requested_duration: str | None = None
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


class EvaluatePermissionRequestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    force_re_evaluate: bool = False


class PermissionRequestEvaluationData(BaseModel):
    request_id: str
    resource_key: str | None = None
    resource_type: str | None = None
    action: str | None = None
    requested_duration: str | None = None
    structured_request: dict[str, object] | None = None
    suggested_permission: str | None = None
    risk_level: str | None = None
    approval_route: list[str]
    policy_version: str | None = None
    approval_status: str
    request_status: str
    evaluated_at: datetime | None = None
    failed_reason: str | None = None


class PermissionRequestEvaluationResponse(BaseModel):
    request_id: str
    data: PermissionRequestEvaluationData


def build_permission_request_service(session: Session) -> PermissionRequestService:
    return PermissionRequestService(
        user_repository=UserRepository(session),
        agent_repository=AgentIdentityRepository(session),
        delegation_repository=DelegationCredentialRepository(session),
        permission_request_repository=PermissionRequestRepository(session),
        permission_request_event_repository=PermissionRequestEventRepository(session),
        audit_repository=AuditRecordRepository(session),
    )


def build_permission_request_evaluation_service(
    session: Session,
) -> PermissionRequestEvaluationService:
    llm_gateway = create_llm_gateway()
    parser = PermissionRequestParser(llm_gateway=llm_gateway)
    return PermissionRequestEvaluationService(
        user_repository=UserRepository(session),
        permission_request_repository=PermissionRequestRepository(session),
        permission_request_event_repository=PermissionRequestEventRepository(session),
        audit_repository=AuditRecordRepository(session),
        parser=parser,
        policy_engine=create_policy_engine(),
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
        requested_duration=permission_request.requested_duration,
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


def build_evaluation_response(
    *,
    request_id: str,
    evaluation: PermissionRequestEvaluationResult,
) -> PermissionRequestEvaluationResponse:
    return PermissionRequestEvaluationResponse(
        request_id=request_id,
        data=PermissionRequestEvaluationData(
            request_id=evaluation.request_id,
            resource_key=evaluation.resource_key,
            resource_type=evaluation.resource_type,
            action=evaluation.action,
            requested_duration=evaluation.requested_duration,
            structured_request=(
                dict(evaluation.structured_request)
                if evaluation.structured_request is not None
                else None
            ),
            suggested_permission=evaluation.suggested_permission,
            risk_level=evaluation.risk_level.value if evaluation.risk_level else None,
            approval_route=list(evaluation.approval_route),
            policy_version=evaluation.policy_version,
            approval_status=evaluation.approval_status.value,
            request_status=evaluation.request_status.value,
            evaluated_at=evaluation.evaluated_at,
            failed_reason=evaluation.failed_reason,
        ),
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


@router.post(
    "/permission-requests/{permission_request_id}/evaluate",
    response_model=PermissionRequestEvaluationResponse,
)
def evaluate_permission_request(
    permission_request_id: str,
    payload: EvaluatePermissionRequestRequest,
    context: Annotated[ApiRequestContext, Depends(get_request_context)],
    session: Annotated[Session, Depends(get_db_session)],
) -> PermissionRequestEvaluationResponse:
    service = build_permission_request_evaluation_service(session)
    try:
        evaluation = service.evaluate_permission_request(
            PermissionRequestEvaluationInput(
                permission_request_id=permission_request_id,
                request_id=context.request_id,
                operator_user_id=context.user_id,
                operator_type=context.operator_type,
                trace_id=context.trace_id,
                force_re_evaluate=payload.force_re_evaluate,
            )
        )
        if evaluation.approval_status is ApprovalStatus.PENDING:
            submit_request_to_approval_pipeline(
                session=session,
                permission_request_id=permission_request_id,
                request_id=context.request_id,
                operator_user_id=context.user_id,
                operator_type=context.operator_type,
                trace_id=context.trace_id,
            )
        session.commit()
    except DomainError:
        session.commit()
        raise

    return build_evaluation_response(
        request_id=context.request_id,
        evaluation=evaluation,
    )


@router.get(
    "/permission-requests/{permission_request_id}/evaluation",
    response_model=PermissionRequestEvaluationResponse,
)
def get_permission_request_evaluation(
    permission_request_id: str,
    context: Annotated[ApiRequestContext, Depends(get_request_context)],
    session: Annotated[Session, Depends(get_db_session)],
) -> PermissionRequestEvaluationResponse:
    service = build_permission_request_evaluation_service(session)
    evaluation = service.get_permission_request_evaluation(
        permission_request_id,
        requester_user_id=context.user_id,
        operator_type=context.operator_type,
    )
    return build_evaluation_response(
        request_id=context.request_id,
        evaluation=evaluation,
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
