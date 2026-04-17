from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.orm import Session

from packages.application import (
    GrantProvisionInput,
    GrantProvisionResult,
    ProvisioningService,
)
from packages.domain import DomainError, ErrorCode
from packages.infrastructure import (
    AccessGrantRepository,
    AuditRecordRepository,
    ConnectorTaskRepository,
    PermissionRequestEventRepository,
    PermissionRequestRepository,
    create_feishu_permission_connector,
)

from .dependencies import ApiRequestContext, get_db_session, get_request_context

router = APIRouter(tags=["grants"])


class ProvisionGrantRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    permission_request_id: str = Field(alias="request_id")
    policy_version: str
    delegation_id: str
    force_retry: bool = False


class GrantProvisionData(BaseModel):
    grant_id: str
    request_id: str
    grant_status: str
    connector_status: str
    request_status: str
    connector_task_id: str | None = None
    connector_task_status: str | None = None
    effective_at: datetime | None = None
    retry_count: int


class GrantProvisionResponse(BaseModel):
    request_id: str
    data: GrantProvisionData


def build_provisioning_service(session: Session) -> ProvisioningService:
    return ProvisioningService(
        permission_request_repository=PermissionRequestRepository(session),
        access_grant_repository=AccessGrantRepository(session),
        connector_task_repository=ConnectorTaskRepository(session),
        permission_request_event_repository=PermissionRequestEventRepository(session),
        audit_repository=AuditRecordRepository(session),
        connector=create_feishu_permission_connector(),
    )


def build_provision_response(
    *,
    request_id: str,
    result: GrantProvisionResult,
) -> GrantProvisionResponse:
    return GrantProvisionResponse(
        request_id=request_id,
        data=GrantProvisionData(
            grant_id=result.grant_id,
            request_id=result.request_id,
            grant_status=result.grant_status.value,
            connector_status=result.connector_status.value,
            request_status=result.request_status.value,
            connector_task_id=result.connector_task_id,
            connector_task_status=(
                result.connector_task_status.value
                if result.connector_task_status is not None
                else None
            ),
            effective_at=result.effective_at,
            retry_count=result.retry_count,
        ),
    )


@router.post("/grants/{grant_id}/provision", response_model=GrantProvisionResponse)
def provision_grant(
    grant_id: str,
    payload: ProvisionGrantRequest,
    context: Annotated[ApiRequestContext, Depends(get_request_context)],
    session: Annotated[Session, Depends(get_db_session)],
) -> GrantProvisionResponse:
    service = build_provisioning_service(session)
    try:
        result = service.provision_grant(
            GrantProvisionInput(
                grant_id=grant_id,
                permission_request_id=payload.permission_request_id,
                policy_version=payload.policy_version,
                delegation_id=payload.delegation_id,
                api_request_id=context.request_id,
                operator_user_id=context.user_id,
                operator_type=context.operator_type,
                force_retry=payload.force_retry,
                trace_id=context.trace_id,
            )
        )
    except DomainError as exc:
        if exc.code is ErrorCode.CONNECTOR_UNAVAILABLE:
            session.commit()
        raise
    session.commit()
    return build_provision_response(request_id=context.request_id, result=result)
