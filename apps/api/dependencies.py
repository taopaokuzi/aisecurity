from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Annotated

from fastapi import Header
from sqlalchemy.orm import Session

from packages.domain import DomainError, ErrorCode, OperatorType
from packages.infrastructure import session_scope


@dataclass(slots=True, frozen=True)
class ApiRequestContext:
    request_id: str
    user_id: str
    operator_type: OperatorType
    trace_id: str | None = None
    idempotency_key: str | None = None


def get_db_session() -> Iterator[Session]:
    with session_scope() as session:
        yield session


def get_request_context(
    x_request_id: Annotated[str, Header(alias="X-Request-Id")],
    x_user_id: Annotated[str, Header(alias="X-User-Id")],
    x_trace_id: Annotated[str | None, Header(alias="X-Trace-Id")] = None,
    x_operator_type: Annotated[str, Header(alias="X-Operator-Type")] = OperatorType.USER.value,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> ApiRequestContext:
    try:
        operator_type = OperatorType(x_operator_type)
    except ValueError as exc:
        raise DomainError(
            ErrorCode.FORBIDDEN,
            message="Operator type is invalid",
            details={"operator_type": x_operator_type, "http_status": 400},
        ) from exc
    return ApiRequestContext(
        request_id=x_request_id,
        user_id=x_user_id,
        operator_type=operator_type,
        trace_id=x_trace_id,
        idempotency_key=idempotency_key,
    )
