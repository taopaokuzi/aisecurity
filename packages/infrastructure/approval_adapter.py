from __future__ import annotations

import hashlib
import hmac
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Mapping, Protocol
from uuid import uuid4


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_source_list(raw_value: str | None) -> tuple[str, ...]:
    if raw_value is None:
        return ("127.0.0.1", "::1", "localhost")
    return tuple(
        item.strip()
        for item in raw_value.split(",")
        if item.strip()
    )


@dataclass(slots=True, frozen=True)
class ApprovalAdapterSettings:
    provider: str = "stub"


@dataclass(slots=True, frozen=True)
class ApprovalCallbackSecuritySettings:
    secret: str
    max_age_seconds: int
    allowed_sources: tuple[str, ...]


@dataclass(slots=True, frozen=True)
class ApprovalSubmissionCommand:
    request_id: str
    user_id: str
    resource_key: str | None
    resource_type: str | None
    action: str | None
    requested_duration: str | None
    suggested_permission: str | None
    risk_level: str | None
    approval_route: tuple[str, ...]
    human_readable_explanation: str
    api_request_id: str
    trace_id: str | None = None


@dataclass(slots=True, frozen=True)
class ApprovalSubmissionResponse:
    external_approval_id: str
    approval_node: str
    approver_id: str | None
    submitted_at: datetime
    provider_request_id: str | None
    raw_payload: Mapping[str, object]


class ApprovalAdapter(Protocol):
    def submit_approval(
        self,
        command: ApprovalSubmissionCommand,
    ) -> ApprovalSubmissionResponse: ...


class StubApprovalAdapter:
    def __init__(
        self,
        *,
        now_provider: Callable[[], datetime] = _utc_now,
    ) -> None:
        self.now_provider = now_provider

    def submit_approval(
        self,
        command: ApprovalSubmissionCommand,
    ) -> ApprovalSubmissionResponse:
        submitted_at = self.now_provider().astimezone(timezone.utc)
        approval_node = command.approval_route[0] if command.approval_route else "manager"
        external_approval_id = f"feishu_apr_{uuid4().hex[:16]}"
        provider_request_id = f"feishu_req_{command.api_request_id}"
        raw_payload = {
            "provider": "stub",
            "request_id": command.request_id,
            "user_id": command.user_id,
            "resource_key": command.resource_key,
            "resource_type": command.resource_type,
            "action": command.action,
            "requested_duration": command.requested_duration,
            "suggested_permission": command.suggested_permission,
            "risk_level": command.risk_level,
            "approval_route": list(command.approval_route),
            "human_readable_explanation": command.human_readable_explanation,
            "api_request_id": command.api_request_id,
            "trace_id": command.trace_id,
        }
        return ApprovalSubmissionResponse(
            external_approval_id=external_approval_id,
            approval_node=approval_node,
            approver_id=None,
            submitted_at=submitted_at,
            provider_request_id=provider_request_id,
            raw_payload=raw_payload,
        )


def build_callback_signature(
    *,
    secret: str,
    timestamp: str,
    raw_body: bytes,
) -> str:
    message = timestamp.encode("utf-8") + b"." + raw_body
    return hmac.new(
        secret.encode("utf-8"),
        message,
        hashlib.sha256,
    ).hexdigest()


class ApprovalCallbackVerifier:
    def __init__(
        self,
        *,
        settings: ApprovalCallbackSecuritySettings,
        now_provider: Callable[[], datetime] = _utc_now,
    ) -> None:
        self.settings = settings
        self.now_provider = now_provider

    def verify(
        self,
        *,
        signature: str,
        timestamp: str,
        raw_body: bytes,
        source: str | None,
    ) -> None:
        normalized_timestamp = self._validate_timestamp(timestamp)
        expected_signature = build_callback_signature(
            secret=self.settings.secret,
            timestamp=normalized_timestamp,
            raw_body=raw_body,
        )
        if not hmac.compare_digest(
            self._normalize_signature(signature),
            expected_signature,
        ):
            raise ValueError("signature_invalid")
        if self.settings.allowed_sources:
            normalized_source = (source or "").strip()
            if normalized_source not in self.settings.allowed_sources:
                raise PermissionError("source_invalid")

    def _validate_timestamp(self, timestamp: str) -> str:
        normalized = timestamp.strip()
        if not normalized:
            raise PermissionError("timestamp_invalid")
        try:
            timestamp_value = int(normalized)
        except ValueError as exc:
            raise PermissionError("timestamp_invalid") from exc
        now_value = int(self.now_provider().timestamp())
        if abs(now_value - timestamp_value) > self.settings.max_age_seconds:
            raise PermissionError("timestamp_invalid")
        return normalized

    def _normalize_signature(self, signature: str) -> str:
        normalized = signature.strip()
        if normalized.startswith("sha256="):
            return normalized[len("sha256=") :]
        return normalized


def load_approval_adapter_settings() -> ApprovalAdapterSettings:
    return ApprovalAdapterSettings(
        provider=os.getenv("APPROVAL_ADAPTER_PROVIDER", "stub").strip().lower() or "stub",
    )


def load_approval_callback_security_settings() -> ApprovalCallbackSecuritySettings:
    return ApprovalCallbackSecuritySettings(
        secret=os.getenv("APPROVAL_CALLBACK_SECRET", "approval-dev-secret"),
        max_age_seconds=int(os.getenv("APPROVAL_CALLBACK_MAX_AGE_SECONDS", "300")),
        allowed_sources=_normalize_source_list(
            os.getenv("APPROVAL_CALLBACK_ALLOWED_SOURCES"),
        ),
    )


def create_approval_adapter(
    *,
    now_provider: Callable[[], datetime] = _utc_now,
) -> ApprovalAdapter:
    settings = load_approval_adapter_settings()
    if settings.provider == "stub":
        return StubApprovalAdapter(now_provider=now_provider)
    raise RuntimeError(f"Unsupported approval adapter provider: {settings.provider}")


def create_approval_callback_verifier(
    *,
    now_provider: Callable[[], datetime] = _utc_now,
) -> ApprovalCallbackVerifier:
    return ApprovalCallbackVerifier(
        settings=load_approval_callback_security_settings(),
        now_provider=now_provider,
    )
