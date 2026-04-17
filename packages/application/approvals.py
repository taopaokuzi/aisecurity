from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Mapping
from uuid import uuid4

from packages.domain import (
    ActorType,
    ApprovalStatus,
    DomainError,
    ErrorCode,
    OperatorType,
    RequestStatus,
    TaskStatus,
)
from packages.infrastructure.approval_adapter import (
    ApprovalAdapter,
    ApprovalCallbackVerifier,
    ApprovalSubmissionCommand,
)
from packages.infrastructure.db.models import (
    ApprovalRecordRecord,
    AuditRecordRecord,
    PermissionRequestEventRecord,
    PermissionRequestRecord,
)
from packages.infrastructure.repositories import (
    ApprovalRecordRepository,
    AuditRecordRepository,
    PermissionRequestEventRepository,
    PermissionRequestRepository,
)

_APPROVAL_SUBMIT_OPERATORS = frozenset(
    {
        OperatorType.SYSTEM,
        OperatorType.IT_ADMIN,
        OperatorType.SECURITY_ADMIN,
    }
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _generate_prefixed_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:24]}"


@dataclass(slots=True, frozen=True)
class ApprovalSubmitInput:
    permission_request_id: str
    request_id: str
    operator_user_id: str
    operator_type: OperatorType | str = OperatorType.SYSTEM
    trace_id: str | None = None


@dataclass(slots=True, frozen=True)
class ApprovalSubmissionResult:
    request_id: str
    approval_id: str
    external_approval_id: str | None
    approval_status: ApprovalStatus
    approval_node: str
    approver_id: str | None
    submitted_at: datetime | None


@dataclass(slots=True, frozen=True)
class ApprovalCallbackPayload:
    external_approval_id: str
    request_id: str
    approval_status: str
    approval_node: str
    idempotency_key: str
    approver_id: str | None = None
    decision_at: str | None = None
    payload: Mapping[str, object] | None = None


@dataclass(slots=True, frozen=True)
class ApprovalCallbackInput:
    callback: ApprovalCallbackPayload
    request_id: str
    provider_request_id: str | None
    signature: str
    timestamp: str
    source: str | None
    raw_body: bytes


@dataclass(slots=True, frozen=True)
class ApprovalCallbackResult:
    request_id: str
    accepted: bool
    approval_status: ApprovalStatus
    duplicated: bool = False


class ApprovalService:
    def __init__(
        self,
        *,
        permission_request_repository: PermissionRequestRepository,
        approval_repository: ApprovalRecordRepository,
        permission_request_event_repository: PermissionRequestEventRepository,
        audit_repository: AuditRecordRepository,
        approval_adapter: ApprovalAdapter,
        callback_verifier: ApprovalCallbackVerifier,
        now_provider: Callable[[], datetime] = _utc_now,
    ) -> None:
        self.permission_request_repository = permission_request_repository
        self.approval_repository = approval_repository
        self.permission_request_event_repository = permission_request_event_repository
        self.audit_repository = audit_repository
        self.approval_adapter = approval_adapter
        self.callback_verifier = callback_verifier
        self.now_provider = now_provider

    def submit_approval_for_request(
        self,
        command: ApprovalSubmitInput,
    ) -> ApprovalSubmissionResult:
        operator_type = self._coerce_operator_type(command.operator_type)
        self._require_submit_operator(operator_type)

        request_record = self._get_request_record(command.permission_request_id)
        if RequestStatus(request_record.request_status) is not RequestStatus.PENDING_APPROVAL:
            raise DomainError(
                ErrorCode.REQUEST_STATUS_INVALID,
                message="Current request status does not allow approval submission",
                details={
                    "request_id": command.permission_request_id,
                    "request_status": request_record.request_status,
                    "http_status": 409,
                },
            )
        if ApprovalStatus(request_record.approval_status) is not ApprovalStatus.PENDING:
            raise DomainError(
                ErrorCode.REQUEST_STATUS_INVALID,
                message="Approval submission requires a pending approval state",
                details={
                    "request_id": command.permission_request_id,
                    "approval_status": request_record.approval_status,
                    "http_status": 409,
                },
            )

        existing_records = self.approval_repository.list_for_request(request_record.request_id)
        if existing_records:
            return self._build_submission_result(existing_records[0])

        approval_route = self._extract_approval_route(request_record)
        if not approval_route:
            raise DomainError(
                ErrorCode.REQUEST_STATUS_INVALID,
                message="Approval route is missing for the request",
                details={
                    "request_id": command.permission_request_id,
                    "http_status": 409,
                },
            )

        submission = self.approval_adapter.submit_approval(
            ApprovalSubmissionCommand(
                request_id=request_record.request_id,
                user_id=request_record.user_id,
                resource_key=request_record.resource_key,
                resource_type=request_record.resource_type,
                action=request_record.action,
                requested_duration=request_record.requested_duration,
                suggested_permission=request_record.suggested_permission,
                risk_level=request_record.risk_level,
                approval_route=approval_route,
                human_readable_explanation=request_record.raw_text,
                api_request_id=command.request_id,
                trace_id=command.trace_id,
            )
        )

        occurred_at = submission.submitted_at.astimezone(timezone.utc)
        approval_record = ApprovalRecordRecord(
            approval_id=_generate_prefixed_id("apr"),
            request_id=request_record.request_id,
            external_approval_id=submission.external_approval_id,
            approval_node=submission.approval_node,
            approver_id=submission.approver_id,
            approval_status=ApprovalStatus.PENDING.value,
            callback_payload_json=None,
            idempotency_key=None,
            submitted_at=occurred_at,
            approved_at=None,
            rejected_at=None,
            created_at=occurred_at,
            updated_at=occurred_at,
        )
        self.approval_repository.add(approval_record)
        self._flush_repository(self.approval_repository)

        self.permission_request_event_repository.add(
            PermissionRequestEventRecord(
                event_id=_generate_prefixed_id("evt"),
                request_id=request_record.request_id,
                event_type="approval.required",
                operator_type=operator_type.value,
                operator_id=command.operator_user_id,
                from_request_status=RequestStatus.PENDING_APPROVAL.value,
                to_request_status=RequestStatus.PENDING_APPROVAL.value,
                metadata_json=self._compact_metadata(
                    {
                        "api_request_id": command.request_id,
                        "trace_id": command.trace_id,
                        "approval_id": approval_record.approval_id,
                        "external_approval_id": submission.external_approval_id,
                        "provider_request_id": submission.provider_request_id,
                        "approval_route": list(approval_route),
                    }
                ),
                occurred_at=occurred_at,
                created_at=occurred_at,
            )
        )
        self.audit_repository.add(
            AuditRecordRecord(
                audit_id=_generate_prefixed_id("aud"),
                request_id=request_record.request_id,
                event_type="approval.required",
                actor_type=ActorType.SYSTEM.value,
                actor_id=command.operator_user_id,
                subject_chain=self._subject_chain(request_record),
                result="Success",
                reason=None,
                metadata_json=self._compact_metadata(
                    {
                        "api_request_id": command.request_id,
                        "trace_id": command.trace_id,
                        "approval_id": approval_record.approval_id,
                        "external_approval_id": submission.external_approval_id,
                        "provider_request_id": submission.provider_request_id,
                        "approval_route": list(approval_route),
                        "adapter_payload": dict(submission.raw_payload),
                    }
                ),
                created_at=occurred_at,
            )
        )

        return self._build_submission_result(approval_record)

    def handle_callback(
        self,
        command: ApprovalCallbackInput,
    ) -> ApprovalCallbackResult:
        self._verify_callback(command)

        duplicate_record = self.approval_repository.get_by_idempotency_key(
            command.callback.idempotency_key
        )
        if duplicate_record is not None:
            return ApprovalCallbackResult(
                request_id=command.request_id,
                accepted=True,
                approval_status=ApprovalStatus(duplicate_record.approval_status),
                duplicated=True,
            )

        approval_record = self._get_approval_record_for_callback(command.callback)
        request_record = self._get_request_record(approval_record.request_id)
        received_at = self._current_time()
        actor_type = ActorType.APPROVER.value if command.callback.approver_id else ActorType.SYSTEM.value
        actor_id = command.callback.approver_id
        current_approval_status = ApprovalStatus(approval_record.approval_status)
        incoming_status = self._try_parse_approval_status(command.callback.approval_status)

        if current_approval_status not in {
            ApprovalStatus.PENDING,
            ApprovalStatus.CALLBACK_FAILED,
        }:
            if incoming_status is current_approval_status:
                return ApprovalCallbackResult(
                    request_id=command.request_id,
                    accepted=True,
                    approval_status=current_approval_status,
                    duplicated=True,
                )
            raise DomainError(
                ErrorCode.REQUEST_STATUS_INVALID,
                message="Approval callback cannot change a completed approval",
                details={
                    "request_id": request_record.request_id,
                    "approval_status": approval_record.approval_status,
                    "http_status": 409,
                },
            )

        approval_record.callback_payload_json = self._build_callback_snapshot(
            command=command,
            received_at=received_at,
        )
        approval_record.idempotency_key = command.callback.idempotency_key
        approval_record.external_approval_id = command.callback.external_approval_id
        approval_record.approval_node = command.callback.approval_node.strip()
        approval_record.approver_id = command.callback.approver_id
        approval_record.updated_at = received_at
        self._flush_repository(self.approval_repository)

        self.audit_repository.add(
            AuditRecordRecord(
                audit_id=_generate_prefixed_id("aud"),
                request_id=request_record.request_id,
                event_type="approval.callback_received",
                actor_type=actor_type,
                actor_id=actor_id,
                subject_chain=self._subject_chain(request_record),
                result="Success",
                reason=None,
                metadata_json=self._compact_metadata(
                    {
                        "api_request_id": command.request_id,
                        "provider_request_id": command.provider_request_id,
                        "external_approval_id": approval_record.external_approval_id,
                        "approval_id": approval_record.approval_id,
                        "approval_status": command.callback.approval_status,
                        "idempotency_key": command.callback.idempotency_key,
                        "source": command.source,
                    }
                ),
                created_at=received_at,
            )
        )

        try:
            mapped_status = ApprovalStatus(command.callback.approval_status)
        except ValueError as exc:
            self._apply_callback_failed(
                approval_record=approval_record,
                request_record=request_record,
                received_at=received_at,
                actor_id=actor_id,
                api_request_id=command.request_id,
                provider_request_id=command.provider_request_id,
                idempotency_key=command.callback.idempotency_key,
                reason=f"Unsupported approval status: {command.callback.approval_status}",
            )
            raise DomainError(
                ErrorCode.REQUEST_STATUS_INVALID,
                message="Approval callback status is invalid",
                details={
                    "approval_status": command.callback.approval_status,
                    "http_status": 400,
                },
            ) from exc

        try:
            return self._apply_callback_status(
                approval_record=approval_record,
                request_record=request_record,
                mapped_status=mapped_status,
                received_at=received_at,
                actor_id=actor_id,
                api_request_id=command.request_id,
                provider_request_id=command.provider_request_id,
                idempotency_key=command.callback.idempotency_key,
                decision_at=self._parse_optional_datetime(
                    command.callback.decision_at,
                    fallback=received_at,
                ),
            )
        except DomainError:
            raise
        except Exception as exc:
            self._apply_callback_failed(
                approval_record=approval_record,
                request_record=request_record,
                received_at=received_at,
                actor_id=actor_id,
                api_request_id=command.request_id,
                provider_request_id=command.provider_request_id,
                idempotency_key=command.callback.idempotency_key,
                reason="Approval callback processing failed",
            )
            raise DomainError(
                ErrorCode.REQUEST_STATUS_INVALID,
                message="Approval callback processing failed",
                details={
                    "request_id": request_record.request_id,
                    "http_status": 500,
                },
            ) from exc

    def _apply_callback_status(
        self,
        *,
        approval_record: ApprovalRecordRecord,
        request_record: PermissionRequestRecord,
        mapped_status: ApprovalStatus,
        received_at: datetime,
        actor_id: str | None,
        api_request_id: str,
        provider_request_id: str | None,
        idempotency_key: str,
        decision_at: datetime,
    ) -> ApprovalCallbackResult:
        if RequestStatus(request_record.request_status) is not RequestStatus.PENDING_APPROVAL:
            raise DomainError(
                ErrorCode.REQUEST_STATUS_INVALID,
                message="Current request status does not allow approval callback",
                details={
                    "request_id": request_record.request_id,
                    "request_status": request_record.request_status,
                    "http_status": 409,
                },
            )

        if mapped_status is ApprovalStatus.APPROVED:
            event_type = "approval.approved"
            next_request_status = RequestStatus.APPROVED
            audit_result = "Success"
            failure_reason = None
            approval_record.approved_at = decision_at
            approval_record.rejected_at = None
        elif mapped_status in {
            ApprovalStatus.REJECTED,
            ApprovalStatus.WITHDRAWN,
            ApprovalStatus.EXPIRED,
        }:
            event_type = f"approval.{mapped_status.value.lower()}"
            next_request_status = RequestStatus.FAILED
            audit_result = "Denied"
            failure_reason = f"Approval {mapped_status.value.lower()}"
            approval_record.approved_at = None
            approval_record.rejected_at = decision_at
        elif mapped_status is ApprovalStatus.CALLBACK_FAILED:
            self._apply_callback_failed(
                approval_record=approval_record,
                request_record=request_record,
                received_at=received_at,
                actor_id=actor_id,
                api_request_id=api_request_id,
                provider_request_id=provider_request_id,
                idempotency_key=idempotency_key,
                reason="Provider reported callback failure",
            )
            return ApprovalCallbackResult(
                request_id=request_record.request_id,
                accepted=True,
                approval_status=ApprovalStatus.CALLBACK_FAILED,
            )
        else:
            raise DomainError(
                ErrorCode.REQUEST_STATUS_INVALID,
                message="Approval callback status is invalid",
                details={
                    "approval_status": mapped_status.value,
                    "http_status": 400,
                },
            )

        approval_record.approval_status = mapped_status.value
        approval_record.updated_at = received_at

        request_record.approval_status = mapped_status.value
        request_record.request_status = next_request_status.value
        request_record.current_task_state = TaskStatus.SUCCEEDED.value
        request_record.failed_reason = failure_reason
        request_record.updated_at = received_at

        self.permission_request_event_repository.add(
            PermissionRequestEventRecord(
                event_id=_generate_prefixed_id("evt"),
                request_id=request_record.request_id,
                event_type=event_type,
                operator_type=OperatorType.APPROVER.value,
                operator_id=actor_id,
                from_request_status=RequestStatus.PENDING_APPROVAL.value,
                to_request_status=next_request_status.value,
                metadata_json=self._compact_metadata(
                    {
                        "api_request_id": api_request_id,
                        "provider_request_id": provider_request_id,
                        "approval_id": approval_record.approval_id,
                        "external_approval_id": approval_record.external_approval_id,
                        "approval_status": mapped_status.value,
                        "approval_node": approval_record.approval_node,
                        "idempotency_key": idempotency_key,
                    }
                ),
                occurred_at=received_at,
                created_at=received_at,
            )
        )
        self.audit_repository.add(
            AuditRecordRecord(
                audit_id=_generate_prefixed_id("aud"),
                request_id=request_record.request_id,
                event_type=event_type,
                actor_type=ActorType.APPROVER.value if actor_id else ActorType.SYSTEM.value,
                actor_id=actor_id,
                subject_chain=self._subject_chain(request_record),
                result=audit_result,
                reason=failure_reason,
                metadata_json=self._compact_metadata(
                    {
                        "api_request_id": api_request_id,
                        "provider_request_id": provider_request_id,
                        "approval_id": approval_record.approval_id,
                        "external_approval_id": approval_record.external_approval_id,
                        "approval_status": mapped_status.value,
                        "approval_node": approval_record.approval_node,
                        "idempotency_key": idempotency_key,
                    }
                ),
                created_at=received_at,
            )
        )
        return ApprovalCallbackResult(
            request_id=request_record.request_id,
            accepted=True,
            approval_status=mapped_status,
        )

    def _apply_callback_failed(
        self,
        *,
        approval_record: ApprovalRecordRecord,
        request_record: PermissionRequestRecord,
        received_at: datetime,
        actor_id: str | None,
        api_request_id: str,
        provider_request_id: str | None,
        idempotency_key: str,
        reason: str,
    ) -> None:
        normalized_reason = reason[:256]
        approval_record.approval_status = ApprovalStatus.CALLBACK_FAILED.value
        approval_record.updated_at = received_at
        approval_record.approved_at = None
        approval_record.rejected_at = None

        request_record.approval_status = ApprovalStatus.CALLBACK_FAILED.value
        request_record.current_task_state = TaskStatus.FAILED.value
        request_record.failed_reason = normalized_reason
        request_record.updated_at = received_at

        self.permission_request_event_repository.add(
            PermissionRequestEventRecord(
                event_id=_generate_prefixed_id("evt"),
                request_id=request_record.request_id,
                event_type="approval.callback_failed",
                operator_type=OperatorType.SYSTEM.value,
                operator_id=actor_id,
                from_request_status=request_record.request_status,
                to_request_status=request_record.request_status,
                metadata_json=self._compact_metadata(
                    {
                        "api_request_id": api_request_id,
                        "provider_request_id": provider_request_id,
                        "approval_id": approval_record.approval_id,
                        "external_approval_id": approval_record.external_approval_id,
                        "idempotency_key": idempotency_key,
                        "failed_reason": normalized_reason,
                    }
                ),
                occurred_at=received_at,
                created_at=received_at,
            )
        )
        self.audit_repository.add(
            AuditRecordRecord(
                audit_id=_generate_prefixed_id("aud"),
                request_id=request_record.request_id,
                event_type="approval.callback_failed",
                actor_type=ActorType.SYSTEM.value,
                actor_id=actor_id,
                subject_chain=self._subject_chain(request_record),
                result="Fail",
                reason=normalized_reason,
                metadata_json=self._compact_metadata(
                    {
                        "api_request_id": api_request_id,
                        "provider_request_id": provider_request_id,
                        "approval_id": approval_record.approval_id,
                        "external_approval_id": approval_record.external_approval_id,
                        "idempotency_key": idempotency_key,
                    }
                ),
                created_at=received_at,
            )
        )

    def _verify_callback(self, command: ApprovalCallbackInput) -> None:
        try:
            self.callback_verifier.verify(
                signature=command.signature,
                timestamp=command.timestamp,
                raw_body=command.raw_body,
                source=command.source,
            )
        except ValueError as exc:
            raise DomainError(
                ErrorCode.CALLBACK_SIGNATURE_INVALID,
                details={"http_status": 401},
            ) from exc
        except PermissionError as exc:
            raise DomainError(
                ErrorCode.CALLBACK_SOURCE_INVALID,
                message="Callback source or timestamp is invalid",
                details={"http_status": 403},
            ) from exc

    def _get_request_record(self, request_id: str) -> PermissionRequestRecord:
        record = self.permission_request_repository.get(request_id)
        if record is None:
            raise DomainError(
                ErrorCode.REQUEST_STATUS_INVALID,
                message="Permission request was not found",
                details={"request_id": request_id, "http_status": 404},
            )
        return record

    def _get_approval_record_for_callback(
        self,
        callback: ApprovalCallbackPayload,
    ) -> ApprovalRecordRecord:
        record = self.approval_repository.get_by_external_approval_id(
            callback.external_approval_id
        )
        if record is not None:
            return record

        for candidate in self.approval_repository.list_for_request(callback.request_id):
            if candidate.external_approval_id is None:
                return candidate

        raise DomainError(
            ErrorCode.APPROVAL_RECORD_NOT_FOUND,
            details={
                "request_id": callback.request_id,
                "external_approval_id": callback.external_approval_id,
                "http_status": 404,
            },
        )

    def _coerce_operator_type(self, operator_type: OperatorType | str) -> OperatorType:
        if isinstance(operator_type, OperatorType):
            return operator_type
        try:
            return OperatorType(operator_type)
        except ValueError as exc:
            raise DomainError(
                ErrorCode.FORBIDDEN,
                message="Operator type is invalid",
                details={"operator_type": operator_type, "http_status": 400},
            ) from exc

    def _require_submit_operator(self, operator_type: OperatorType) -> None:
        if operator_type not in _APPROVAL_SUBMIT_OPERATORS:
            raise DomainError(
                ErrorCode.FORBIDDEN,
                details={"operator_type": operator_type.value, "http_status": 403},
            )

    def _extract_approval_route(
        self,
        request_record: PermissionRequestRecord,
    ) -> tuple[str, ...]:
        structured_request = request_record.structured_request_json or {}
        raw_route = structured_request.get("approval_route")
        if not isinstance(raw_route, list):
            policy_payload = structured_request.get("policy_evaluation")
            if isinstance(policy_payload, Mapping):
                raw_route = policy_payload.get("approval_route")
        if not isinstance(raw_route, list):
            return ()
        return tuple(str(item) for item in raw_route if str(item).strip())

    def _build_submission_result(
        self,
        approval_record: ApprovalRecordRecord,
    ) -> ApprovalSubmissionResult:
        return ApprovalSubmissionResult(
            request_id=approval_record.request_id,
            approval_id=approval_record.approval_id,
            external_approval_id=approval_record.external_approval_id,
            approval_status=ApprovalStatus(approval_record.approval_status),
            approval_node=approval_record.approval_node,
            approver_id=approval_record.approver_id,
            submitted_at=approval_record.submitted_at,
        )

    def _build_callback_snapshot(
        self,
        *,
        command: ApprovalCallbackInput,
        received_at: datetime,
    ) -> dict[str, object]:
        raw_payload = (
            dict(command.callback.payload)
            if command.callback.payload is not None
            else {}
        )
        return {
            "provider_request_id": command.provider_request_id,
            "signature": command.signature,
            "timestamp": command.timestamp,
            "source": command.source,
            "received_at": received_at.isoformat().replace("+00:00", "Z"),
            "body": {
                "external_approval_id": command.callback.external_approval_id,
                "request_id": command.callback.request_id,
                "approval_status": command.callback.approval_status,
                "approval_node": command.callback.approval_node,
                "approver_id": command.callback.approver_id,
                "decision_at": command.callback.decision_at,
                "idempotency_key": command.callback.idempotency_key,
                "payload": raw_payload,
            },
            "raw_body": command.raw_body.decode("utf-8", errors="replace"),
        }

    def _parse_optional_datetime(
        self,
        raw_value: str | None,
        *,
        fallback: datetime,
    ) -> datetime:
        if raw_value is None or not raw_value.strip():
            return fallback
        normalized = raw_value.strip().replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(normalized).astimezone(timezone.utc)
        except ValueError:
            return fallback

    def _try_parse_approval_status(
        self,
        raw_value: str,
    ) -> ApprovalStatus | None:
        try:
            return ApprovalStatus(raw_value)
        except ValueError:
            return None

    def _current_time(self) -> datetime:
        return self.now_provider().astimezone(timezone.utc)

    def _flush_repository(self, repository: object) -> None:
        session = getattr(repository, "session", None)
        if session is not None:
            session.flush()

    def _subject_chain(self, request_record: PermissionRequestRecord) -> str:
        return (
            f"user:{request_record.user_id}->"
            f"agent:{request_record.agent_id}->"
            f"request:{request_record.request_id}"
        )

    def _compact_metadata(self, metadata: dict[str, object | None]) -> dict[str, object]:
        return {key: value for key, value in metadata.items() if value is not None}
