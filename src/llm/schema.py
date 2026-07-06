"""Phase 5: LLM schema — provider types, message structures, response contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal


class LLMProvider(str, Enum):
    MOCK = "mock"
    QWEN = "qwen"
    DEEPSEEK = "deepseek"


class LLMMode(str, Enum):
    MOCK_EXTRACTIVE = "mock_extractive"
    GROUNDED_LLM = "grounded_llm"


@dataclass
class LLMMessage:
    role: Literal["system", "user", "assistant"]
    content: str


@dataclass
class LLMResponse:
    content: str
    parsed_json: dict[str, Any] | None = None
    provider: str = "mock"
    model: str = "mock"
    latency_ms: float = 0.0
    token_usage: dict[str, int] = field(default_factory=dict)
    raw_response: Any = None


@dataclass
class GroundedAnswer:
    """Structured grounded answer from LLM."""
    answer_markdown: str
    citations: list[dict[str, Any]] = field(default_factory=list)
    used_sources: list[str] = field(default_factory=list)
    unsupported_claims: list[str] = field(default_factory=list)
    hallucination_risk: Literal["none", "low", "medium", "high"] = "none"


@dataclass
class IntentResult:
    intent: str  # "technical_reference", "project_inquiry", "mixed", "ambiguous", "unsupported"
    confidence: float
    reasoning: str
    recommended_corpus: str  # "official_docs", "internal_engineering_docs", "dual"


@dataclass
class PlanResult:
    steps: list[str] = field(default_factory=list)
    retrieval_queries: list[str] = field(default_factory=list)
    reasoning: str = ""
