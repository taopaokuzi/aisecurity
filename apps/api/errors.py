from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from packages.domain import DomainError, ErrorCode

_DEFAULT_STATUS_BY_ERROR_CODE = {
    ErrorCode.UNAUTHORIZED: 401,
    ErrorCode.FORBIDDEN: 403,
    ErrorCode.CALLBACK_SIGNATURE_INVALID: 401,
    ErrorCode.CALLBACK_SOURCE_INVALID: 403,
    ErrorCode.DELEGATION_INVALID: 400,
    ErrorCode.AGENT_DISABLED: 409,
    ErrorCode.REQUEST_MESSAGE_EMPTY: 400,
    ErrorCode.REQUEST_STATUS_INVALID: 400,
    ErrorCode.DELEGATION_SCOPE_INVALID: 400,
    ErrorCode.DELEGATION_EXPIRE_AT_INVALID: 400,
    ErrorCode.APPROVAL_RECORD_NOT_FOUND: 404,
    ErrorCode.APPROVAL_NOT_APPROVED: 409,
    ErrorCode.PROVISION_POLICY_RECHECK_FAILED: 409,
    ErrorCode.CONNECTOR_UNAVAILABLE: 503,
    ErrorCode.SESSION_ALREADY_REVOKED: 409,
    ErrorCode.RETRY_NOT_ALLOWED: 409,
    ErrorCode.GRANT_ALREADY_ACTIVE: 409,
}


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def handle_domain_error(request: Request, exc: DomainError) -> JSONResponse:
        details = dict(exc.details)
        status_code = int(details.pop("http_status", _DEFAULT_STATUS_BY_ERROR_CODE.get(exc.code, 400)))
        return JSONResponse(
            status_code=status_code,
            content={
                "request_id": (
                    request.headers.get("X-Request-Id")
                    or request.headers.get("X-Feishu-Request-Id")
                    or ""
                ),
                "error": {
                    "code": exc.code.value,
                    "message": exc.message,
                    "details": details,
                },
            },
        )
