from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from packages.application import SessionAuthority, SessionRevokeInput, SessionRevokeRequestedResult
from packages.infrastructure import (
    AccessGrantRepository,
    AgentIdentityRepository,
    AuditRecordRepository,
    ConnectorTaskRepository,
    PermissionRequestEventRepository,
    PermissionRequestRepository,
    SessionContextRepository,
    create_feishu_session_connector,
)

from .dependencies import ApiRequestContext, get_db_session, get_request_context

router = APIRouter(tags=["sessions"])


class RevokeSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    global_session_id: str
    reason: str
    cascade_connector_sessions: bool = True


class SessionRevokeData(BaseModel):
    global_session_id: str
    session_status: str


class SessionRevokeResponse(BaseModel):
    request_id: str
    data: SessionRevokeData


def build_session_authority(session: Session) -> SessionAuthority:
    return SessionAuthority(
        permission_request_repository=PermissionRequestRepository(session),
        access_grant_repository=AccessGrantRepository(session),
        session_context_repository=SessionContextRepository(session),
        permission_request_event_repository=PermissionRequestEventRepository(session),
        audit_repository=AuditRecordRepository(session),
        connector_task_repository=ConnectorTaskRepository(session),
        agent_identity_repository=AgentIdentityRepository(session),
        connector=create_feishu_session_connector(),
    )


def build_revoke_response(
    *,
    request_id: str,
    result: SessionRevokeRequestedResult,
) -> SessionRevokeResponse:
    return SessionRevokeResponse(
        request_id=request_id,
        data=SessionRevokeData(
            global_session_id=result.global_session_id,
            session_status=result.session_status.value,
        ),
    )


@router.post("/sessions/revoke", response_model=SessionRevokeResponse)
def revoke_session(
    payload: RevokeSessionRequest,
    context: Annotated[ApiRequestContext, Depends(get_request_context)],
    session: Annotated[Session, Depends(get_db_session)],
) -> SessionRevokeResponse:
    service = build_session_authority(session)
    result = service.request_session_revoke(
        SessionRevokeInput(
            global_session_id=payload.global_session_id,
            reason=payload.reason,
            cascade_connector_sessions=payload.cascade_connector_sessions,
            api_request_id=context.request_id,
            operator_user_id=context.user_id,
            operator_type=context.operator_type,
            trace_id=context.trace_id,
        )
    )
    session.commit()
    return build_revoke_response(request_id=context.request_id, result=result)
