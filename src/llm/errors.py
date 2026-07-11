"""Typed LLM failures that can cross graph and API boundaries safely."""

from __future__ import annotations


class LLMError(RuntimeError):
    """Base class for LLM runtime failures."""


class LLMConfigurationError(LLMError):
    """Raised when a requested provider cannot be configured safely."""


class LLMProviderError(LLMError):
    """Raised when a configured provider fails to serve a request."""

    def __init__(
        self,
        provider: str,
        model: str,
        reason: str,
        *,
        status_code: int | None = None,
        retryable: bool = False,
    ) -> None:
        self.provider = provider
        self.model = model
        self.reason = reason
        self.status_code = status_code
        self.retryable = retryable
        super().__init__(f"{provider}/{model}: {reason}")

    def public_detail(self) -> dict[str, object]:
        """Return a redacted payload suitable for an API response."""
        return {
            "code": "llm_provider_failed",
            "provider": self.provider,
            "model": self.model,
            "reason": self.reason,
            "provider_status": self.status_code,
            "retryable": self.retryable,
            "fallback_used": False,
        }
