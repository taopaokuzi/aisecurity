from __future__ import annotations

from sqlalchemy.orm import Session

from packages.application import (
    ApprovalService,
    ApprovalSubmissionResult,
    ApprovalSubmitInput,
)
from packages.domain import OperatorType
from packages.infrastructure import (
    ApprovalRecordRepository,
    AuditRecordRepository,
    PermissionRequestEventRepository,
    PermissionRequestRepository,
    create_approval_adapter,
    create_approval_callback_verifier,
)


def build_approval_service(session: Session) -> ApprovalService:
    return ApprovalService(
        permission_request_repository=PermissionRequestRepository(session),
        approval_repository=ApprovalRecordRepository(session),
        permission_request_event_repository=PermissionRequestEventRepository(session),
        audit_repository=AuditRecordRepository(session),
        approval_adapter=create_approval_adapter(),
        callback_verifier=create_approval_callback_verifier(),
    )


def submit_request_to_approval_pipeline(
    *,
    session: Session,
    permission_request_id: str,
    request_id: str,
    operator_user_id: str,
    operator_type: OperatorType | str = OperatorType.SYSTEM,
    trace_id: str | None = None,
) -> ApprovalSubmissionResult:
    return build_approval_service(session).submit_approval_for_request(
        ApprovalSubmitInput(
            permission_request_id=permission_request_id,
            request_id=request_id,
            operator_user_id=operator_user_id,
            operator_type=operator_type,
            trace_id=trace_id,
        )
    )
