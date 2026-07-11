"""Phase 5: LLM Client - unified interface with auto-fallback to mock."""

from __future__ import annotations

import os
from typing import Any

from llm.base import BaseLLMProvider, MockProvider, ProviderFactory
from llm.errors import LLMConfigurationError, LLMProviderError
from llm.schema import LLMMessage, LLMMode, LLMResponse


class LLMClient:
    """Unified LLM client. Provider failures are fail-closed by default."""

    def __init__(
        self,
        provider: str | None = None,
        model: str | None = None,
        *,
        allow_fallback: bool | None = None,
    ):
        self.allow_fallback = (
            self._env_flag("ALLOW_LLM_FALLBACK", False)
            if allow_fallback is None
            else allow_fallback
        )
        self._provider_name = provider or self._detect_provider()
        self._model = model or self._default_model_for_provider(self._provider_name)
        self.last_fallback_used = False
        self.last_fallback_reason = ""
        try:
            self._provider: BaseLLMProvider = ProviderFactory.create(
                self._provider_name,
                model=self._model,
            )
        except LLMConfigurationError as exc:
            if not self.allow_fallback or self._provider_name == "mock":
                raise
            self._activate_fallback(f"configuration_error:{exc.__class__.__name__}")
        self.mode: LLMMode = (
            LLMMode.MOCK_EXTRACTIVE
            if isinstance(self._provider, MockProvider)
            else LLMMode.GROUNDED_LLM
        )

    @staticmethod
    def _env_flag(name: str, default: bool) -> bool:
        value = os.environ.get(name)
        if value is None:
            return default
        return value.strip().lower() in {"1", "true", "yes", "on"}

    @staticmethod
    def _detect_provider() -> str:
        """Auto-detect available provider from environment."""
        from dotenv import load_dotenv

        load_dotenv()
        if LLMClient._env_flag("USE_FAKE_MODEL", False):
            return "mock"
        if os.environ.get("QWEN_API_KEY"):
            return "qwen"
        if os.environ.get("DEEPSEEK_API_KEY"):
            return "deepseek"
        return "mock"

    @staticmethod
    def _default_model_for_provider(provider: str) -> str:
        if provider == "qwen":
            return os.environ.get("QWEN_MODEL") or "qwen-max"
        if provider == "deepseek":
            return os.environ.get("DEEPSEEK_MODEL") or "deepseek-chat"
        return "mock"

    def _activate_fallback(self, reason: str) -> None:
        self._provider = MockProvider()
        self.last_fallback_used = self._provider_name != "mock"
        self.last_fallback_reason = reason
        self.mode = LLMMode.MOCK_EXTRACTIVE

    @property
    def provider_name(self) -> str:
        return self._provider.provider_name

    @property
    def model_name(self) -> str:
        return self._provider.model

    @property
    def requested_provider_name(self) -> str:
        return self._provider_name

    @property
    def requested_model_name(self) -> str:
        return self._model

    @property
    def is_mock(self) -> bool:
        return isinstance(self._provider, MockProvider)

    def generate(self, messages: list[LLMMessage], **kwargs: Any) -> LLMResponse:
        """Generate a response, with fallback only when explicitly enabled."""
        try:
            response = self._provider.generate(messages, **kwargs)
            if not self.last_fallback_used:
                self.last_fallback_reason = ""
            return response
        except LLMProviderError as exc:
            if not self.allow_fallback or self._provider_name == "mock":
                raise
            reason = f"{exc.reason}:{exc.status_code or 'unknown'}"
            self._activate_fallback(reason)
            response = self._provider.generate(messages, **kwargs)
            response.raw_response = {"fallback_reason": reason}
            return response

    def chat(self, system: str, user: str, **kwargs: Any) -> LLMResponse:
        return self.generate(
            [
                LLMMessage(role="system", content=system),
                LLMMessage(role="user", content=user),
            ],
            **kwargs,
        )
