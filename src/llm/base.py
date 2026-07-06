"""Phase 5: LLM Provider base class."""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Any

from llm.schema import LLMMessage, LLMResponse


class BaseLLMProvider(ABC):
    """Abstract base for LLM providers."""

    def __init__(self, model: str = "mock"):
        self.model = model

    @abstractmethod
    def generate(self, messages: list[LLMMessage], **kwargs: Any) -> LLMResponse:
        """Generate a response from the LLM."""
        ...

    def chat(self, system_prompt: str, user_prompt: str, **kwargs: Any) -> LLMResponse:
        """Convenience: single-turn chat."""
        return self.generate([
            LLMMessage(role="system", content=system_prompt),
            LLMMessage(role="user", content=user_prompt),
        ], **kwargs)

    @property
    @abstractmethod
    def provider_name(self) -> str:
        ...


class MockProvider(BaseLLMProvider):
    """Mock provider — always returns structured empty/default responses.

    Used when no real LLM key is configured. Never throws, never makes network calls.
    """

    def __init__(self):
        super().__init__(model="mock")

    @property
    def provider_name(self) -> str:
        return "mock"

    def generate(self, messages: list[LLMMessage], **kwargs: Any) -> LLMResponse:
        t0 = time.perf_counter()
        # Return a safe default response
        content = '{"intent": "technical_reference", "confidence": 0.5, "reasoning": "mock provider — no LLM available"}'
        return LLMResponse(
            content=content,
            provider="mock",
            model="mock",
            latency_ms=round((time.perf_counter() - t0) * 1000, 2),
            token_usage={"prompt": 0, "completion": 0},
        )


class ProviderFactory:
    """Factory to create LLM providers based on available configuration."""

    @staticmethod
    def create(provider: str = "mock", **kwargs: Any) -> BaseLLMProvider:
        if provider == "mock":
            return MockProvider()
        if provider == "qwen":
            return ProviderFactory._create_qwen(**kwargs)
        if provider == "deepseek":
            return ProviderFactory._create_deepseek(**kwargs)
        # Unknown provider → fall back to mock
        return MockProvider()

    @staticmethod
    def _create_qwen(**kwargs: Any) -> BaseLLMProvider:
        import os
        api_key = os.environ.get("QWEN_API_KEY", "")
        if not api_key:
            return MockProvider()  # no key → mock
        from llm.providers import QwenProvider
        return QwenProvider(api_key=api_key, model=kwargs.get("model", "qwen-turbo"))

    @staticmethod
    def _create_deepseek(**kwargs: Any) -> BaseLLMProvider:
        import os
        api_key = os.environ.get("DEEPSEEK_API_KEY", "")
        if not api_key:
            return MockProvider()  # no key → mock
        from llm.providers import DeepSeekProvider
        return DeepSeekProvider(api_key=api_key, model=kwargs.get("model", "deepseek-chat"))
