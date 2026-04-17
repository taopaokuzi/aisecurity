from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, ValidationError
from sqlalchemy.orm import Session

from packages.application import (
    ApprovalCallbackInput,
    ApprovalCallbackPayload,
    ApprovalCallbackResult,
    ApprovalService,
    GrantProvisionInput,
    default_grant_id_for_request,
)
from packages.domain import ApprovalStatus, DomainError, ErrorCode, OperatorType
from packages.infrastructure import (
    ApprovalRecordRepository,
    AuditRecordRepository,
    PermissionRequestEventRepository,
    PermissionRequestRepository,
    create_approval_adapter,
    create_approval_callback_verifier,
)

from .dependencies import get_db_session
from .grants import build_provisioning_service

router = APIRouter(tags=["approvals"])


class ApprovalCallbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    external_approval_id: str
    request_id: str
    approval_status: str
    approval_node: str
    approver_id: str | None = None
    decision_at: str | None = None
    idempotency_key: str
    payload: dict[str, object] | None = None


class ApprovalCallbackData(BaseModel):
    accepted: bool
    approval_status: str
    duplicated: bool = False


class ApprovalCallbackResponse(BaseModel):
    request_id: str
    data: ApprovalCallbackData


def build_approval_service(session: Session) -> ApprovalService:
    return ApprovalService(
        permission_request_repository=PermissionRequestRepository(session),
        approval_repository=ApprovalRecordRepository(session),
        permission_request_event_repository=PermissionRequestEventRepository(session),
        audit_repository=AuditRecordRepository(session),
        approval_adapter=create_approval_adapter(),
        callback_verifier=create_approval_callback_verifier(),
    )


def build_callback_response(
    *,
    request_id: str,
    result: ApprovalCallbackResult,
) -> ApprovalCallbackResponse:
    return ApprovalCallbackResponse(
        request_id=request_id,
        data=ApprovalCallbackData(
            accepted=result.accepted,
            approval_status=result.approval_status.value,
            duplicated=result.duplicated,
        ),
    )


@router.post("/approvals/callback", response_model=ApprovalCallbackResponse)
async def handle_approval_callback(
    request: Request,
    session: Annotated[Session, Depends(get_db_session)],
) -> ApprovalCallbackResponse:
    raw_body = await request.body()
    try:
        payload = ApprovalCallbackRequest.model_validate_json(raw_body)
    except ValidationError as exc:
        raise DomainError(
            ErrorCode.REQUEST_STATUS_INVALID,
            message="Approval callback payload is invalid",
            details={
                "validation_errors": exc.errors(),
                "http_status": 400,
            },
        ) from exc

    api_request_id = (
        request.headers.get("X-Request-Id")
        or request.headers.get("X-Feishu-Request-Id")
        or payload.request_id
    )
    source = request.headers.get("X-Forwarded-For")
    if source:
        source = source.split(",")[0].strip()
    elif request.client is not None:
        source = request.client.host

    service = build_approval_service(session)
    try:
        result = service.handle_callback(
            ApprovalCallbackInput(
                callback=ApprovalCallbackPayload(
                    external_approval_id=payload.external_approval_id,
                    request_id=payload.request_id,
                    approval_status=payload.approval_status,
                    approval_node=payload.approval_node,
                    approver_id=payload.approver_id,
                    decision_at=payload.decision_at,
                    idempotency_key=payload.idempotency_key,
                    payload=payload.payload,
                ),
                request_id=api_request_id,
                provider_request_id=request.headers.get("X-Feishu-Request-Id"),
                signature=request.headers.get("X-Feishu-Signature", ""),
                timestamp=request.headers.get("X-Feishu-Timestamp", ""),
                source=source,
                raw_body=raw_body,
            )
        )
        if not result.duplicated and result.approval_status is ApprovalStatus.APPROVED:
            request_record = PermissionRequestRepository(session).get(payload.request_id)
            if request_record is not None:
                provisioning_service = build_provisioning_service(session)
                try:
                    provisioning_service.provision_grant(
                        GrantProvisionInput(
                            grant_id=default_grant_id_for_request(payload.request_id),
                            permission_request_id=payload.request_id,
                            policy_version=request_record.policy_version or "",
                            delegation_id=request_record.delegation_id,
                            api_request_id=api_request_id,
                            operator_user_id=payload.approver_id or "approval_callback",
                            operator_type=OperatorType.SYSTEM,
                            trace_id=request.headers.get("X-Trace-Id"),
                        )
                    )
                except DomainError:
                    # Approval callback has already been persisted; provisioning failure
                    # is recorded by ProvisioningService and can be retried later.
                    pass
        session.commit()
    except DomainError:
        session.commit()
        raise

    return build_callback_response(request_id=api_request_id, result=result)
