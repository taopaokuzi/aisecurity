from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from uuid import uuid4

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from packages.domain import ConnectorStatus
from packages.infrastructure import build_callback_signature
from packages.infrastructure.feishu_connector import (
    ConnectorProvisionCommand,
    ConnectorProvisionResponse,
    ConnectorSessionRevokeCommand,
    ConnectorSessionRevokeResponse,
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _json_request(
    *,
    method: str,
    url: str,
    payload: dict[str, object],
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, object]]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", **(headers or {})},
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            status_code = response.getcode()
            response_body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        status_code = exc.code
        response_body = exc.read().decode("utf-8")
    if not response_body:
        return status_code, {}
    return status_code, json.loads(response_body)


class MockApprovalSendRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    callback_url: str
    request_id: str
    external_approval_id: str
    scenario: str = "approved"
    approval_node: str = "manager"
    approver_id: str = "user_mgr_001"
    decision_at: str | None = None
    idempotency_key: str | None = None
    duplicate_count: int = Field(default=1, ge=1, le=5)
    api_request_id: str = "mock_feishu_callback"
    callback_secret: str | None = None
    source: str = "127.0.0.1"
    payload: dict[str, object] | None = None


class MockProvisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario: str = "applied"
    request_id: str
    grant_id: str
    delegation_id: str
    policy_version: str
    resource_key: str
    resource_type: str
    action: str
    expire_at: str
    api_request_id: str
    trace_id: str | None = None


class MockSessionRevokeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scenario: str = "success"
    global_session_id: str
    grant_id: str
    request_id: str
    agent_id: str
    user_id: str
    reason: str
    cascade_connector_sessions: bool
    api_request_id: str
    connector_session_ref: str | None = None
    task_session_id: str | None = None
    trace_id: str | None = None


def create_mock_feishu_app() -> FastAPI:
    app = FastAPI(title="mock-feishu")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/approval/callbacks/send")
    def send_approval_callback(command: MockApprovalSendRequest) -> dict[str, object]:
        scenario = command.scenario.strip().lower() or "approved"
        if scenario == "duplicate" and command.duplicate_count == 1:
            duplicate_count = 2
        else:
            duplicate_count = command.duplicate_count

        approval_status = {
            "approved": "Approved",
            "rejected": "Rejected",
            "duplicate": "Approved",
        }.get(scenario)
        if approval_status is None:
            raise HTTPException(status_code=400, detail=f"Unsupported approval scenario: {scenario}")

        idempotency_key = command.idempotency_key or f"feishu_cb_{uuid4().hex[:16]}"
        decision_at = command.decision_at or _utc_now().isoformat().replace("+00:00", "Z")
        callback_payload = {
            "external_approval_id": command.external_approval_id,
            "request_id": command.request_id,
            "approval_status": approval_status,
            "approval_node": command.approval_node,
            "approver_id": command.approver_id,
            "decision_at": decision_at,
            "idempotency_key": idempotency_key,
            "payload": command.payload or {"provider": "mock-feishu", "scenario": scenario},
        }
        raw_body = json.dumps(callback_payload).encode("utf-8")
        timestamp = str(int(_utc_now().timestamp()))
        signature = build_callback_signature(
            secret=command.callback_secret or os.getenv("MOCK_FEISHU_APPROVAL_SECRET", "test-approval-secret"),
            timestamp=timestamp,
            raw_body=raw_body,
        )

        deliveries: list[dict[str, object]] = []
        for _ in range(duplicate_count):
            status_code, response_payload = _json_request(
                method="POST",
                url=command.callback_url,
                payload=callback_payload,
                headers={
                    "X-Request-Id": command.api_request_id,
                    "X-Feishu-Request-Id": f"mock_feishu_req_{uuid4().hex[:12]}",
                    "X-Feishu-Timestamp": timestamp,
                    "X-Feishu-Signature": signature,
                    "X-Forwarded-For": command.source,
                },
            )
            deliveries.append(
                {
                    "status_code": status_code,
                    "payload": response_payload,
                }
            )

        return {
            "request_id": command.request_id,
            "data": {
                "scenario": scenario,
                "approval_status": approval_status,
                "idempotency_key": idempotency_key,
                "deliveries": deliveries,
            },
        }

    @app.post("/connector/provision")
    def provision(payload: MockProvisionRequest) -> dict[str, object]:
        scenario = payload.scenario.strip().lower() or "applied"
        provider_request_id = f"mock_feishu_req_{uuid4().hex[:16]}"
        provider_task_id = f"mock_feishu_task_{uuid4().hex[:16]}"
        raw_payload = payload.model_dump() | {
            "provider": "mock-feishu",
            "provider_request_id": provider_request_id,
            "provider_task_id": provider_task_id,
        }

        if scenario == "applied":
            return {
                "connector_status": ConnectorStatus.APPLIED.value,
                "provider_request_id": provider_request_id,
                "provider_task_id": provider_task_id,
                "effective_at": _utc_now().isoformat().replace("+00:00", "Z"),
                "retryable": False,
                "error_code": None,
                "error_message": None,
                "raw_payload": raw_payload,
            }
        if scenario in {"accepted", "accepted_delayed"}:
            return {
                "connector_status": ConnectorStatus.ACCEPTED.value,
                "provider_request_id": provider_request_id,
                "provider_task_id": provider_task_id,
                "effective_at": None,
                "retryable": True,
                "error_code": None,
                "error_message": None,
                "raw_payload": raw_payload | {"delayed_effective": True},
            }
        if scenario == "failed":
            return {
                "connector_status": ConnectorStatus.FAILED.value,
                "provider_request_id": provider_request_id,
                "provider_task_id": provider_task_id,
                "effective_at": None,
                "retryable": True,
                "error_code": "MOCK_FEISHU_PROVISION_FAILED",
                "error_message": "mock-feishu failed to provision the permission",
                "raw_payload": raw_payload,
            }
        raise HTTPException(status_code=400, detail=f"Unsupported provision scenario: {scenario}")

    @app.post("/connector/session-revoke")
    def revoke_session(payload: MockSessionRevokeRequest) -> dict[str, object]:
        scenario = payload.scenario.strip().lower() or "success"
        provider_request_id = f"mock_feishu_req_{uuid4().hex[:16]}"
        provider_task_id = f"mock_feishu_task_{uuid4().hex[:16]}"
        raw_payload = payload.model_dump() | {
            "provider": "mock-feishu",
            "provider_request_id": provider_request_id,
            "provider_task_id": provider_task_id,
        }

        if scenario == "success":
            return {
                "provider_request_id": provider_request_id,
                "provider_task_id": provider_task_id,
                "connector_session_ref": payload.connector_session_ref,
                "revoked_at": _utc_now().isoformat().replace("+00:00", "Z"),
                "retryable": False,
                "error_code": None,
                "error_message": None,
                "raw_payload": raw_payload,
            }
        if scenario == "failed":
            return {
                "provider_request_id": provider_request_id,
                "provider_task_id": provider_task_id,
                "connector_session_ref": payload.connector_session_ref,
                "revoked_at": None,
                "retryable": True,
                "error_code": "MOCK_FEISHU_REVOKE_FAILED",
                "error_message": "mock-feishu failed to revoke the connector session",
                "raw_payload": raw_payload,
            }
        raise HTTPException(status_code=400, detail=f"Unsupported revoke scenario: {scenario}")

    return app


app = create_mock_feishu_app()


class MockFeishuPermissionConnector:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    def provision_access(
        self,
        command: ConnectorProvisionCommand,
    ) -> ConnectorProvisionResponse:
        status_code, payload = _json_request(
            method="POST",
            url=f"{self.base_url}/connector/provision",
            payload={
                "scenario": os.getenv("MOCK_FEISHU_PROVISION_SCENARIO", "applied"),
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
            },
        )
        if status_code != 200:
            raise RuntimeError(f"mock-feishu provision failed: {payload}")
        return ConnectorProvisionResponse(
            connector_status=ConnectorStatus(payload["connector_status"]),
            provider_request_id=payload.get("provider_request_id"),
            provider_task_id=payload.get("provider_task_id"),
            effective_at=(
                datetime.fromisoformat(str(payload["effective_at"]).replace("Z", "+00:00"))
                if payload.get("effective_at")
                else None
            ),
            retryable=bool(payload["retryable"]),
            error_code=payload.get("error_code"),
            error_message=payload.get("error_message"),
            raw_payload=dict(payload.get("raw_payload") or {}),
        )


class MockFeishuSessionConnector:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    def revoke_session(
        self,
        command: ConnectorSessionRevokeCommand,
    ) -> ConnectorSessionRevokeResponse:
        status_code, payload = _json_request(
            method="POST",
            url=f"{self.base_url}/connector/session-revoke",
            payload={
                "scenario": os.getenv("MOCK_FEISHU_SESSION_REVOKE_SCENARIO", "success"),
                "global_session_id": command.global_session_id,
                "grant_id": command.grant_id,
                "request_id": command.request_id,
                "agent_id": command.agent_id,
                "user_id": command.user_id,
                "reason": command.reason,
                "cascade_connector_sessions": command.cascade_connector_sessions,
                "api_request_id": command.api_request_id,
                "connector_session_ref": command.connector_session_ref,
                "task_session_id": command.task_session_id,
                "trace_id": command.trace_id,
            },
        )
        if status_code != 200:
            raise RuntimeError(f"mock-feishu session revoke failed: {payload}")
        return ConnectorSessionRevokeResponse(
            provider_request_id=payload.get("provider_request_id"),
            provider_task_id=payload.get("provider_task_id"),
            connector_session_ref=payload.get("connector_session_ref"),
            revoked_at=(
                datetime.fromisoformat(str(payload["revoked_at"]).replace("Z", "+00:00"))
                if payload.get("revoked_at")
                else None
            ),
            retryable=bool(payload["retryable"]),
            error_code=payload.get("error_code"),
            error_message=payload.get("error_message"),
            raw_payload=dict(payload.get("raw_payload") or {}),
        )


def main() -> None:
    uvicorn.run(app, host="127.0.0.1", port=int(os.getenv("MOCK_FEISHU_PORT", "18080")))


if __name__ == "__main__":
    main()

