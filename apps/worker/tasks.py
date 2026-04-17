from __future__ import annotations

from datetime import datetime, timezone

from celery import Celery

from packages.application import GrantProvisionInput, ProvisioningService
from packages.domain import DomainError, ErrorCode, OperatorType
from packages.infrastructure import (
    AccessGrantRepository,
    AuditRecordRepository,
    ConnectorTaskRepository,
    PermissionRequestEventRepository,
    PermissionRequestRepository,
    create_feishu_permission_connector,
    session_scope,
)

REGISTERED_TASKS = (
    "worker.ping",
    "worker.runtime_summary",
    "worker.grants.provision",
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def register_tasks(celery_app: Celery) -> None:
    if "worker.ping" not in celery_app.tasks:

        @celery_app.task(name="worker.ping")
        def ping() -> dict[str, str]:
            return {
                "status": "ok",
                "service": celery_app.conf.worker_service_name,
                "timestamp": utc_now(),
            }

    if "worker.runtime_summary" not in celery_app.tasks:

        @celery_app.task(name="worker.runtime_summary")
        def runtime_summary() -> dict[str, str]:
            return {
                "service": celery_app.conf.worker_service_name,
                "broker_url": celery_app.conf.broker_url,
                "result_backend": celery_app.conf.result_backend,
                "queue_name": celery_app.conf.task_default_queue,
                "timestamp": utc_now(),
            }

    if "worker.grants.provision" not in celery_app.tasks:

        @celery_app.task(name="worker.grants.provision")
        def provision_grant(
            *,
            grant_id: str,
            permission_request_id: str,
            policy_version: str,
            delegation_id: str,
            api_request_id: str,
            operator_user_id: str = "worker",
            force_retry: bool = False,
            trace_id: str | None = None,
        ) -> dict[str, object]:
            with session_scope() as session:
                service = ProvisioningService(
                    permission_request_repository=PermissionRequestRepository(session),
                    access_grant_repository=AccessGrantRepository(session),
                    connector_task_repository=ConnectorTaskRepository(session),
                    permission_request_event_repository=PermissionRequestEventRepository(session),
                    audit_repository=AuditRecordRepository(session),
                    connector=create_feishu_permission_connector(),
                )
                try:
                    result = service.provision_grant(
                        GrantProvisionInput(
                            grant_id=grant_id,
                            permission_request_id=permission_request_id,
                            policy_version=policy_version,
                            delegation_id=delegation_id,
                            api_request_id=api_request_id,
                            operator_user_id=operator_user_id,
                            operator_type=OperatorType.SYSTEM,
                            force_retry=force_retry,
                            trace_id=trace_id,
                        )
                    )
                except DomainError as exc:
                    if exc.code is ErrorCode.CONNECTOR_UNAVAILABLE:
                        session.commit()
                    raise
                session.commit()
                return {
                    "grant_id": result.grant_id,
                    "request_id": result.request_id,
                    "grant_status": result.grant_status.value,
                    "connector_status": result.connector_status.value,
                    "request_status": result.request_status.value,
                    "connector_task_id": result.connector_task_id,
                    "connector_task_status": (
                        result.connector_task_status.value
                        if result.connector_task_status is not None
                        else None
                    ),
                    "effective_at": (
                        result.effective_at.isoformat().replace("+00:00", "Z")
                        if result.effective_at is not None
                        else None
                    ),
                    "retry_count": result.retry_count,
                }
