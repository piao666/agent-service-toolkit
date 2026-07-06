"""Phase 5: LLM Client — unified interface with auto-fallback to mock."""

from __future__ import annotations

import os
from typing import Any

from llm.base import BaseLLMProvider, MockProvider, ProviderFactory
from llm.schema import LLMMessage, LLMResponse, LLMProvider, LLMMode


class LLMClient:
    """Unified LLM client with automatic provider selection and mock fallback."""

    def __init__(self, provider: str | None = None, model: str | None = None):
        self._provider_name = provider or self._detect_provider()
        self._model = model or "mock"
        self._provider: BaseLLMProvider = ProviderFactory.create(self._provider_name, model=self._model)
        self.mode: LLMMode = LLMMode.MOCK_EXTRACTIVE if isinstance(self._provider, MockProvider) else LLMMode.GROUNDED_LLM

    @staticmethod
    def _detect_provider() -> str:
        """Auto-detect available provider from environment."""
        if os.environ.get("QWEN_API_KEY"):
            return "qwen"
        if os.environ.get("DEEPSEEK_API_KEY"):
            return "deepseek"
        return "mock"

    @property
    def provider_name(self) -> str:
        return self._provider.provider_name

    @property
    def is_mock(self) -> bool:
        return isinstance(self._provider, MockProvider)

    def generate(self, messages: list[LLMMessage], **kwargs: Any) -> LLMResponse:
        """Generate a response. Always succeeds — falls back to mock on any error."""
        try:
            return self._provider.generate(messages, **kwargs)
        except Exception:
            return MockProvider().generate(messages, **kwargs)

    def chat(self, system: str, user: str, **kwargs: Any) -> LLMResponse:
        return self.generate([
            LLMMessage(role="system", content=system),
            LLMMessage(role="user", content=user),
        ], **kwargs)
