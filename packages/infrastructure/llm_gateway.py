from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from json import JSONDecodeError
from typing import Any, Mapping, Protocol, Sequence
from urllib import error as urllib_error
from urllib import request as urllib_request

from config.loader import load_settings
from packages.prompts import PromptLoader, PromptNotFoundError

LOGGER = logging.getLogger(__name__)
DEFAULT_LLM_PROVIDER = "stub"
DEFAULT_LLM_MODEL = "gpt-4.1-mini"
DEFAULT_LLM_TIMEOUT_SECONDS = 30.0


class LLMGatewayError(RuntimeError):
    """Base LLM gateway error."""


class LLMConfigurationError(LLMGatewayError):
    """Raised when gateway configuration is invalid."""


class LLMTimeoutError(LLMGatewayError):
    """Raised when an LLM call exceeds the allowed timeout."""


class LLMTransportError(LLMGatewayError):
    """Raised when the underlying provider call fails."""


class LLMResponseError(LLMGatewayError):
    """Raised when the provider response cannot be interpreted."""


@dataclass(slots=True, frozen=True)
class LLMGatewaySettings:
    provider: str = DEFAULT_LLM_PROVIDER
    model: str = DEFAULT_LLM_MODEL
    timeout_seconds: float = DEFAULT_LLM_TIMEOUT_SECONDS
    base_url: str | None = None
    api_key: str | None = None
    prompt_dir: str | None = None

    @classmethod
    def from_settings(cls, settings: Mapping[str, Any]) -> "LLMGatewaySettings":
        llm_settings = settings.get("llm") if isinstance(settings, Mapping) else None
        llm_settings = llm_settings if isinstance(llm_settings, Mapping) else {}

        provider = _normalize_optional_text(llm_settings.get("provider")) or DEFAULT_LLM_PROVIDER
        model = _normalize_optional_text(llm_settings.get("model")) or DEFAULT_LLM_MODEL
        timeout_seconds = _coerce_timeout_seconds(
            llm_settings.get("timeout_seconds", DEFAULT_LLM_TIMEOUT_SECONDS)
        )
        return cls(
            provider=provider,
            model=model,
            timeout_seconds=timeout_seconds,
            base_url=_normalize_optional_text(llm_settings.get("base_url")),
            api_key=_normalize_optional_text(llm_settings.get("api_key")),
            prompt_dir=_normalize_optional_text(llm_settings.get("prompt_dir")),
        )


@dataclass(slots=True, frozen=True)
class LLMMessage:
    role: str
    content: str


@dataclass(slots=True, frozen=True)
class LLMRequest:
    prompt_name: str
    prompt_variables: Mapping[str, Any] | None = None
    user_input: str | None = None
    model: str | None = None
    timeout_seconds: float | None = None


@dataclass(slots=True, frozen=True)
class LLMTransportResult:
    content: str
    model: str
    raw_response: Any | None = None


@dataclass(slots=True, frozen=True)
class LLMResponse:
    prompt_name: str
    prompt_text: str
    content: str
    model: str
    raw_response: Any | None = None


class LLMTransport(Protocol):
    def generate(
        self,
        *,
        messages: Sequence[LLMMessage],
        model: str,
        timeout_seconds: float,
    ) -> LLMTransportResult:
        ...


class DisabledLLMTransport:
    def generate(
        self,
        *,
        messages: Sequence[LLMMessage],
        model: str,
        timeout_seconds: float,
    ) -> LLMTransportResult:
        raise LLMConfigurationError(
            "LLM transport is disabled. Configure 'llm.provider' or inject a stub transport."
        )


class OpenAICompatibleTransport:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None = None,
        endpoint_path: str = "/chat/completions",
    ) -> None:
        normalized_base_url = _normalize_optional_text(base_url)
        if not normalized_base_url:
            raise LLMConfigurationError("llm.base_url is required for OpenAI-compatible transport.")

        self.base_url = normalized_base_url.rstrip("/")
        self.api_key = _normalize_optional_text(api_key)
        self.endpoint_path = endpoint_path

    def generate(
        self,
        *,
        messages: Sequence[LLMMessage],
        model: str,
        timeout_seconds: float,
    ) -> LLMTransportResult:
        payload = {
            "model": model,
            "messages": [
                {
                    "role": message.role,
                    "content": message.content,
                }
                for message in messages
            ],
        }
        request_body = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        http_request = urllib_request.Request(
            url=f"{self.base_url}{self.endpoint_path}",
            data=request_body,
            headers=headers,
            method="POST",
        )

        try:
            with urllib_request.urlopen(http_request, timeout=timeout_seconds) as response:
                response_body = response.read().decode("utf-8")
        except urllib_error.HTTPError as exc:
            details = exc.read().decode("utf-8", errors="replace")
            message = details or exc.reason or "unknown provider error"
            raise LLMTransportError(
                f"LLM provider returned HTTP {exc.code}: {message}"
            ) from exc
        except urllib_error.URLError as exc:
            if _is_timeout_reason(exc.reason):
                raise TimeoutError(
                    f"LLM provider timed out after {timeout_seconds} seconds."
                ) from exc
            raise LLMTransportError(f"LLM provider request failed: {exc.reason}") from exc

        try:
            payload = json.loads(response_body)
        except JSONDecodeError as exc:
            raise LLMResponseError("LLM provider returned invalid JSON.") from exc

        content = _extract_message_content(payload)
        resolved_model = str(payload.get("model") or model)
        return LLMTransportResult(content=content, model=resolved_model, raw_response=payload)


class LLMGateway:
    def __init__(
        self,
        *,
        settings: LLMGatewaySettings,
        prompt_loader: PromptLoader,
        transport: LLMTransport,
    ) -> None:
        self.settings = settings
        self.prompt_loader = prompt_loader
        self.transport = transport

    def invoke(self, request: LLMRequest) -> LLMResponse:
        prompt = self.prompt_loader.render(request.prompt_name, request.prompt_variables)
        model = _normalize_optional_text(request.model) or self.settings.model
        timeout_seconds = _coerce_timeout_seconds(
            request.timeout_seconds or self.settings.timeout_seconds
        )
        messages = [LLMMessage(role="system", content=prompt.content)]

        user_input = _normalize_optional_text(request.user_input)
        if user_input:
            messages.append(LLMMessage(role="user", content=user_input))

        try:
            result = self.transport.generate(
                messages=tuple(messages),
                model=model,
                timeout_seconds=timeout_seconds,
            )
        except PromptNotFoundError:
            raise
        except TimeoutError as exc:
            LOGGER.warning(
                "LLM call timed out for prompt '%s' with model '%s'.",
                request.prompt_name,
                model,
            )
            raise LLMTimeoutError(
                f"LLM call timed out for prompt '{request.prompt_name}' after {timeout_seconds} seconds."
            ) from exc
        except LLMGatewayError:
            raise
        except Exception as exc:
            LOGGER.exception(
                "LLM call failed for prompt '%s' with model '%s'.",
                request.prompt_name,
                model,
            )
            raise LLMTransportError(
                f"LLM call failed for prompt '{request.prompt_name}'."
            ) from exc

        return LLMResponse(
            prompt_name=request.prompt_name,
            prompt_text=prompt.content,
            content=result.content,
            model=result.model,
            raw_response=result.raw_response,
        )


def load_llm_gateway_settings(env_name: str | None = None) -> LLMGatewaySettings:
    settings, _ = load_settings(env_name)
    return LLMGatewaySettings.from_settings(settings)


def create_default_transport(settings: LLMGatewaySettings) -> LLMTransport:
    provider = settings.provider.lower()
    if provider in {"stub", "disabled"}:
        return DisabledLLMTransport()
    if provider in {"openai", "openai_compatible"}:
        return OpenAICompatibleTransport(
            base_url=settings.base_url or "",
            api_key=settings.api_key,
        )
    raise LLMConfigurationError(f"Unsupported llm.provider '{settings.provider}'.")


def create_llm_gateway(
    *,
    env_name: str | None = None,
    settings: LLMGatewaySettings | None = None,
    prompt_loader: PromptLoader | None = None,
    transport: LLMTransport | None = None,
) -> LLMGateway:
    resolved_settings = settings or load_llm_gateway_settings(env_name)
    resolved_prompt_loader = prompt_loader or PromptLoader(resolved_settings.prompt_dir)
    resolved_transport = transport or create_default_transport(resolved_settings)
    return LLMGateway(
        settings=resolved_settings,
        prompt_loader=resolved_prompt_loader,
        transport=resolved_transport,
    )


def _normalize_optional_text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _coerce_timeout_seconds(value: Any) -> float:
    try:
        timeout_seconds = float(value)
    except (TypeError, ValueError) as exc:
        raise LLMConfigurationError("llm.timeout_seconds must be a positive number.") from exc

    if timeout_seconds <= 0:
        raise LLMConfigurationError("llm.timeout_seconds must be greater than zero.")
    return timeout_seconds


def _is_timeout_reason(reason: Any) -> bool:
    if isinstance(reason, TimeoutError):
        return True
    return "timed out" in str(reason).lower()


def _extract_message_content(payload: Mapping[str, Any]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        raise LLMResponseError("LLM provider response did not include choices.")

    first_choice = choices[0]
    if not isinstance(first_choice, Mapping):
        raise LLMResponseError("LLM provider response choice is invalid.")

    message = first_choice.get("message")
    if not isinstance(message, Mapping):
        raise LLMResponseError("LLM provider response did not include a message.")

    content = message.get("content")
    if isinstance(content, str):
        normalized = content.strip()
        if normalized:
            return normalized

    if isinstance(content, list):
        parts: list[str] = []
        for part in content:
            if isinstance(part, Mapping):
                text = part.get("text")
                if text:
                    parts.append(str(text))
        normalized = "".join(parts).strip()
        if normalized:
            return normalized

    raise LLMResponseError("LLM provider response did not include text content.")
