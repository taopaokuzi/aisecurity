from __future__ import annotations

from .llm_gateway import (
    DEFAULT_LLM_MODEL,
    DEFAULT_LLM_PROVIDER,
    DEFAULT_LLM_TIMEOUT_SECONDS,
    LLMConfigurationError,
    LLMGateway,
    LLMGatewayError,
    LLMGatewaySettings,
    LLMMessage,
    LLMRequest,
    LLMResponse,
    LLMResponseError,
    LLMTimeoutError,
    LLMTransport,
    LLMTransportError,
    OpenAICompatibleTransport,
    create_default_transport,
    create_llm_gateway,
    load_llm_gateway_settings,
)

__all__ = [
    "DEFAULT_LLM_MODEL",
    "DEFAULT_LLM_PROVIDER",
    "DEFAULT_LLM_TIMEOUT_SECONDS",
    "LLMConfigurationError",
    "LLMGateway",
    "LLMGatewayError",
    "LLMGatewaySettings",
    "LLMMessage",
    "LLMRequest",
    "LLMResponse",
    "LLMResponseError",
    "LLMTimeoutError",
    "LLMTransport",
    "LLMTransportError",
    "OpenAICompatibleTransport",
    "create_default_transport",
    "create_llm_gateway",
    "load_llm_gateway_settings",
]

try:
    from .db import (
        Base,
        AccessGrantRecord,
        AgentIdentityRecord,
        ApprovalRecordRecord,
        AuditRecordRecord,
        DelegationCredentialRecord,
        PermissionRequestEventRecord,
        PermissionRequestRecord,
        UserRecord,
        create_sync_engine,
        get_database_url,
        get_engine,
        get_session_factory,
        session_scope,
    )
    from .repositories import (
        AccessGrantRepository,
        AgentIdentityRepository,
        ApprovalRecordRepository,
        AuditRecordRepository,
        DelegationCredentialRepository,
        PermissionRequestEventRepository,
        PermissionRequestRepository,
        SqlAlchemyRepository,
        UserRepository,
    )
except ModuleNotFoundError as exc:
    if exc.name != "sqlalchemy":
        raise
else:
    __all__.extend(
        [
            "AccessGrantRecord",
            "AccessGrantRepository",
            "AgentIdentityRecord",
            "AgentIdentityRepository",
            "ApprovalRecordRecord",
            "ApprovalRecordRepository",
            "AuditRecordRecord",
            "AuditRecordRepository",
            "Base",
            "DelegationCredentialRecord",
            "DelegationCredentialRepository",
            "PermissionRequestEventRecord",
            "PermissionRequestEventRepository",
            "PermissionRequestRecord",
            "PermissionRequestRepository",
            "SqlAlchemyRepository",
            "UserRecord",
            "UserRepository",
            "create_sync_engine",
            "get_database_url",
            "get_engine",
            "get_session_factory",
            "session_scope",
        ]
    )
