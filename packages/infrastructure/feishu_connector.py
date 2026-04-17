from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Mapping, Protocol
from uuid import uuid4

from packages.domain import ConnectorStatus


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(slots=True, frozen=True)
class FeishuConnectorSettings:
    provider: str = "stub"
    stub_mode: str = "accepted"


@dataclass(slots=True, frozen=True)
class ConnectorProvisionCommand:
    request_id: str
    grant_id: str
    delegation_id: str
    policy_version: str
    resource_key: str
    resource_type: str
    action: str
    expire_at: datetime
    api_request_id: str
    trace_id: str | None = None


@dataclass(slots=True, frozen=True)
class ConnectorProvisionResponse:
    connector_status: ConnectorStatus
    provider_request_id: str | None
    provider_task_id: str | None
    effective_at: datetime | None
    retryable: bool
    error_code: str | None
    error_message: str | None
    raw_payload: Mapping[str, object]


class ConnectorUnavailableError(RuntimeError):
    pass


class FeishuPermissionConnector(Protocol):
    def provision_access(
        self,
        command: ConnectorProvisionCommand,
    ) -> ConnectorProvisionResponse: ...


class StubFeishuPermissionConnector:
    def __init__(
        self,
        *,
        mode: str = "accepted",
        now_provider: Callable[[], datetime] = _utc_now,
    ) -> None:
        self.mode = mode.strip().lower() or "accepted"
        self.now_provider = now_provider

    def provision_access(
        self,
        command: ConnectorProvisionCommand,
    ) -> ConnectorProvisionResponse:
        current_time = self.now_provider().astimezone(timezone.utc)
        provider_request_id = f"feishu_req_{uuid4().hex[:16]}"
        provider_task_id = f"feishu_task_{uuid4().hex[:16]}"
        raw_payload = {
            "provider": "stub",
            "mode": self.mode,
            "request_id": command.request_id,
            "grant_id": command.grant_id,
            "delegation_id": command.delegation_id,
            "policy_version": command.policy_version,
            "resource_key": command.resource_key,
            "resource_type": command.resource_type,
            "action": command.action,
            "expire_at": command.expire_at.isoformat().replace("+00:00", "Z"),
            "api_request_id": command.api_request_id,
            "trace_id": command.trace_id,
        }

        if command.resource_type not in {"doc", "report"} or command.action != "read":
            return ConnectorProvisionResponse(
                connector_status=ConnectorStatus.FAILED,
                provider_request_id=provider_request_id,
                provider_task_id=provider_task_id,
                effective_at=None,
                retryable=False,
                error_code="UNSUPPORTED_PERMISSION",
                error_message="Feishu connector only supports doc/report read access in V1",
                raw_payload=raw_payload,
            )

        if self.mode == "accepted":
            return ConnectorProvisionResponse(
                connector_status=ConnectorStatus.ACCEPTED,
                provider_request_id=provider_request_id,
                provider_task_id=provider_task_id,
                effective_at=None,
                retryable=True,
                error_code=None,
                error_message=None,
                raw_payload=raw_payload,
            )
        if self.mode == "applied":
            return ConnectorProvisionResponse(
                connector_status=ConnectorStatus.APPLIED,
                provider_request_id=provider_request_id,
                provider_task_id=provider_task_id,
                effective_at=current_time,
                retryable=False,
                error_code=None,
                error_message=None,
                raw_payload=raw_payload,
            )
        if self.mode == "failed":
            return ConnectorProvisionResponse(
                connector_status=ConnectorStatus.FAILED,
                provider_request_id=provider_request_id,
                provider_task_id=provider_task_id,
                effective_at=None,
                retryable=True,
                error_code="FEISHU_PROVISION_FAILED",
                error_message="Feishu connector failed to apply the requested permission",
                raw_payload=raw_payload,
            )
        if self.mode == "partial":
            return ConnectorProvisionResponse(
                connector_status=ConnectorStatus.PARTIAL,
                provider_request_id=provider_request_id,
                provider_task_id=provider_task_id,
                effective_at=None,
                retryable=False,
                error_code="FEISHU_PROVISION_PARTIAL",
                error_message="Feishu connector reported a partial provisioning result",
                raw_payload=raw_payload,
            )
        raise ConnectorUnavailableError(f"Unsupported feishu connector stub mode: {self.mode}")


def load_feishu_connector_settings() -> FeishuConnectorSettings:
    return FeishuConnectorSettings(
        provider=os.getenv("FEISHU_CONNECTOR_PROVIDER", "stub").strip().lower() or "stub",
        stub_mode=os.getenv("FEISHU_CONNECTOR_STUB_MODE", "accepted").strip().lower() or "accepted",
    )


def create_feishu_permission_connector(
    *,
    now_provider: Callable[[], datetime] = _utc_now,
) -> FeishuPermissionConnector:
    settings = load_feishu_connector_settings()
    if settings.provider == "stub":
        return StubFeishuPermissionConnector(mode=settings.stub_mode, now_provider=now_provider)
    raise ConnectorUnavailableError(
        f"Unsupported feishu connector provider: {settings.provider}"
    )
