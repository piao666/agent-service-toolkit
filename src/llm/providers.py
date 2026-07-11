"""Phase 5: Concrete LLM providers — Qwen, DeepSeek."""

from __future__ import annotations

import json
import time
from typing import Any

from llm.base import BaseLLMProvider
from llm.errors import LLMProviderError
from llm.schema import LLMMessage, LLMResponse


class QwenProvider(BaseLLMProvider):
    """Qwen (Tongyi Qianwen) provider via OpenAI-compatible API."""

    def __init__(self, api_key: str, model: str = "qwen-max", base_url: str | None = None):
        super().__init__(model=model)
        self.api_key = api_key
        self.base_url = base_url or "https://dashscope.aliyuncs.com/compatible-mode/v1"

    @property
    def provider_name(self) -> str:
        return "qwen"

    def generate(self, messages: list[LLMMessage], **kwargs: Any) -> LLMResponse:
        t0 = time.perf_counter()
        try:
            import requests

            payload = {
                "model": self.model,
                "messages": [{"role": m.role, "content": m.content} for m in messages],
                "temperature": kwargs.get("temperature", 0.3),
                "max_tokens": kwargs.get("max_tokens", 2048),
            }
            resp = requests.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=60,
            )
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            parsed = _try_parse_json(content)
            return LLMResponse(
                content=content,
                parsed_json=parsed,
                provider="qwen",
                model=self.model,
                latency_ms=round((time.perf_counter() - t0) * 1000, 2),
                token_usage=data.get("usage", {}),
            )
        except Exception as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            reason = (
                "provider_http_error"
                if status is not None
                else f"provider_{exc.__class__.__name__.lower()}"
            )
            raise LLMProviderError(
                "qwen",
                self.model,
                reason,
                status_code=status,
                retryable=status in {408, 429, 500, 502, 503, 504} or status is None,
            ) from exc


class DeepSeekProvider(BaseLLMProvider):
    """DeepSeek provider via OpenAI-compatible API."""

    def __init__(self, api_key: str, model: str = "deepseek-chat", base_url: str | None = None):
        super().__init__(model=model)
        self.api_key = api_key
        self.base_url = base_url or "https://api.deepseek.com/v1"

    @property
    def provider_name(self) -> str:
        return "deepseek"

    def generate(self, messages: list[LLMMessage], **kwargs: Any) -> LLMResponse:
        t0 = time.perf_counter()
        try:
            import requests

            payload = {
                "model": self.model,
                "messages": [{"role": m.role, "content": m.content} for m in messages],
                "temperature": kwargs.get("temperature", 0.3),
                "max_tokens": kwargs.get("max_tokens", 2048),
            }
            resp = requests.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=60,
            )
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            parsed = _try_parse_json(content)
            return LLMResponse(
                content=content,
                parsed_json=parsed,
                provider="deepseek",
                model=self.model,
                latency_ms=round((time.perf_counter() - t0) * 1000, 2),
                token_usage=data.get("usage", {}),
            )
        except Exception as exc:
            status = getattr(getattr(exc, "response", None), "status_code", None)
            reason = (
                "provider_http_error"
                if status is not None
                else f"provider_{exc.__class__.__name__.lower()}"
            )
            raise LLMProviderError(
                "deepseek",
                self.model,
                reason,
                status_code=status,
                retryable=status in {408, 429, 500, 502, 503, 504} or status is None,
            ) from exc


def _try_parse_json(text: str) -> dict[str, Any] | None:
    """Try to extract and parse JSON from LLM output."""
    # Try direct parse
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        pass
    # Try to extract JSON from markdown code block
    import re

    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if m:
        try:
            return json.loads(m.group(1))
        except (json.JSONDecodeError, TypeError):
            pass
    return None
