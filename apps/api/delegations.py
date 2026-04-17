from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from packages.application import DelegationCreateInput, DelegationService
from packages.domain import DelegationCredential
from packages.infrastructure import (
    AgentIdentityRepository,
    AuditRecordRepository,
    DelegationCredentialRepository,
    UserRepository,
)

from .dependencies import ApiRequestContext, get_db_session, get_request_context

router = APIRouter(tags=["delegations"])


class DelegationScopePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resource_types: list[str]
    allowed_actions: list[str]


class CreateDelegationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    agent_id: str
    task_scope: str
    scope: DelegationScopePayload
    expire_at: datetime


class DelegationCreateData(BaseModel):
    delegation_id: str
    delegation_status: str
    issued_at: datetime
    expire_at: datetime


class DelegationCreateResponse(BaseModel):
    request_id: str
    data: DelegationCreateData


class DelegationDetailData(BaseModel):
    delegation_id: str
    user_id: str
    agent_id: str
    task_scope: str
    scope: DelegationScopePayload
    delegation_status: str
    issued_at: datetime
    expire_at: datetime
    revoked_at: datetime | None = None


class DelegationDetailResponse(BaseModel):
    request_id: str
    data: DelegationDetailData


def build_delegation_service(session: Session) -> DelegationService:
    return DelegationService(
        user_repository=UserRepository(session),
        agent_repository=AgentIdentityRepository(session),
        delegation_repository=DelegationCredentialRepository(session),
        audit_repository=AuditRecordRepository(session),
    )


def build_create_response(
    *,
    request_id: str,
    delegation: DelegationCredential,
) -> DelegationCreateResponse:
    return DelegationCreateResponse(
        request_id=request_id,
        data=DelegationCreateData(
            delegation_id=delegation.delegation_id,
            delegation_status=delegation.delegation_status.value,
            issued_at=delegation.issued_at,
            expire_at=delegation.expire_at,
        ),
    )


def build_detail_response(
    *,
    request_id: str,
    delegation: DelegationCredential,
) -> DelegationDetailResponse:
    return DelegationDetailResponse(
        request_id=request_id,
        data=DelegationDetailData(
            delegation_id=delegation.delegation_id,
            user_id=delegation.user_id,
            agent_id=delegation.agent_id,
            task_scope=delegation.task_scope,
            scope=DelegationScopePayload.model_validate(dict(delegation.scope)),
            delegation_status=delegation.delegation_status.value,
            issued_at=delegation.issued_at,
            expire_at=delegation.expire_at,
            revoked_at=delegation.revoked_at,
        ),
    )


@router.post("/delegations", response_model=DelegationCreateResponse)
def create_delegation(
    payload: CreateDelegationRequest,
    context: Annotated[ApiRequestContext, Depends(get_request_context)],
    session: Annotated[Session, Depends(get_db_session)],
) -> DelegationCreateResponse:
    service = build_delegation_service(session)
    delegation = service.create_delegation(
        DelegationCreateInput(
            user_id=context.user_id,
            agent_id=payload.agent_id,
            task_scope=payload.task_scope,
            scope=payload.scope.model_dump(),
            expire_at=payload.expire_at,
            request_id=context.request_id,
            trace_id=context.trace_id,
            idempotency_key=context.idempotency_key,
        )
    )
    session.commit()
    return build_create_response(request_id=context.request_id, delegation=delegation)


@router.get("/delegations/{delegation_id}", response_model=DelegationDetailResponse)
def get_delegation(
    delegation_id: str,
    context: Annotated[ApiRequestContext, Depends(get_request_context)],
    session: Annotated[Session, Depends(get_db_session)],
) -> DelegationDetailResponse:
    service = build_delegation_service(session)
    delegation = service.get_delegation(
        delegation_id,
        requester_user_id=context.user_id,
        operator_type=context.operator_type,
    )
    session.commit()
    return build_detail_response(request_id=context.request_id, delegation=delegation)
