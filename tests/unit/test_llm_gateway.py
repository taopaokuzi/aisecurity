from __future__ import annotations

import unittest

from packages.infrastructure.llm_gateway import (
    LLMGateway,
    LLMGatewaySettings,
    LLMMessage,
    LLMRequest,
    LLMTimeoutError,
    LLMTransportError,
    LLMTransportResult,
    create_llm_gateway,
    load_llm_gateway_settings,
)
from packages.prompts import PromptLoader


class _FakeTransport:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def generate(
        self,
        *,
        messages: tuple[LLMMessage, ...],
        model: str,
        timeout_seconds: float,
    ) -> LLMTransportResult:
        self.calls.append(
            {
                "messages": messages,
                "model": model,
                "timeout_seconds": timeout_seconds,
            }
        )
        return LLMTransportResult(
            content='{"resource_type":"report"}',
            model=model,
            raw_response={"provider": "fake"},
        )


class _TimeoutTransport:
    def generate(
        self,
        *,
        messages: tuple[LLMMessage, ...],
        model: str,
        timeout_seconds: float,
    ) -> LLMTransportResult:
        raise TimeoutError("timed out")


class _ExplodingTransport:
    def generate(
        self,
        *,
        messages: tuple[LLMMessage, ...],
        model: str,
        timeout_seconds: float,
    ) -> LLMTransportResult:
        raise RuntimeError("provider failure")


class LLMGatewayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = LLMGatewaySettings(
            provider="stub",
            model="gpt-test-mini",
            timeout_seconds=12,
            prompt_dir="packages/prompts/templates",
        )
        self.prompt_loader = PromptLoader(self.settings.prompt_dir)

    def test_create_llm_gateway_loads_settings_from_config(self) -> None:
        settings = load_llm_gateway_settings("test")
        gateway = create_llm_gateway(
            settings=settings,
            transport=_FakeTransport(),
        )

        self.assertEqual(gateway.settings.model, "gpt-4.1-mini")
        self.assertEqual(gateway.settings.timeout_seconds, 5.0)
        self.assertEqual(gateway.prompt_loader.base_dir.name, "templates")

    def test_invoke_uses_prompt_loader_model_and_timeout(self) -> None:
        transport = _FakeTransport()
        gateway = LLMGateway(
            settings=self.settings,
            prompt_loader=self.prompt_loader,
            transport=transport,
        )

        response = gateway.invoke(
            LLMRequest(
                prompt_name="parse_permission_request",
                prompt_variables={"request_text": "我需要查看销售部 Q3 报表"},
                user_input="请帮我结构化输出",
            )
        )

        self.assertEqual(response.model, "gpt-test-mini")
        self.assertIn("我需要查看销售部 Q3 报表", response.prompt_text)
        self.assertEqual(response.content, '{"resource_type":"report"}')
        self.assertEqual(len(transport.calls), 1)
        self.assertEqual(transport.calls[0]["model"], "gpt-test-mini")
        self.assertEqual(transport.calls[0]["timeout_seconds"], 12)
        messages = transport.calls[0]["messages"]
        self.assertEqual(len(messages), 2)
        self.assertEqual(messages[0].role, "system")
        self.assertEqual(messages[1].role, "user")

    def test_invoke_wraps_timeout_error(self) -> None:
        gateway = LLMGateway(
            settings=self.settings,
            prompt_loader=self.prompt_loader,
            transport=_TimeoutTransport(),
        )

        with self.assertRaises(LLMTimeoutError) as context:
            gateway.invoke(
                LLMRequest(
                    prompt_name="parse_permission_request",
                    prompt_variables={"request_text": "test"},
                )
            )

        self.assertIn("timed out", str(context.exception))

    def test_invoke_wraps_unexpected_transport_errors(self) -> None:
        gateway = LLMGateway(
            settings=self.settings,
            prompt_loader=self.prompt_loader,
            transport=_ExplodingTransport(),
        )

        with self.assertRaises(LLMTransportError) as context:
            gateway.invoke(
                LLMRequest(
                    prompt_name="parse_permission_request",
                    prompt_variables={"request_text": "test"},
                )
            )

        self.assertIn("parse_permission_request", str(context.exception))


if __name__ == "__main__":
    unittest.main()
