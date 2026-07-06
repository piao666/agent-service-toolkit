"""Phase 5: JSON output parser — extract structured data from LLM responses."""

from __future__ import annotations

import json
import re
from typing import Any

from llm.schema import LLMResponse


def parse_json_output(response: LLMResponse, default: dict[str, Any] | None = None) -> dict[str, Any]:
    """Extract structured JSON from an LLM response.

    Tries: direct parse → markdown code block extraction → default fallback.
    """
    default = default or {}
    if response.parsed_json:
        return response.parsed_json

    text = response.content.strip()

    # Try direct parse
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        pass

    # Try to find JSON in markdown code block
    m = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if m:
        try:
            return json.loads(m.group(1))
        except (json.JSONDecodeError, TypeError):
            pass

    # Try to find a JSON object anywhere in text
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        try:
            return json.loads(m.group(0))
        except (json.JSONDecodeError, TypeError):
            pass

    return default


def parse_intent(response: LLMResponse) -> dict[str, Any]:
    """Parse classifier output into structured intent."""
    default = {"intent": "ambiguous", "confidence": 0.3, "reasoning": "parse failed", "recommended_corpus": "official_docs"}
    return parse_json_output(response, default)


def parse_plan(response: LLMResponse) -> dict[str, Any]:
    """Parse planner output."""
    default = {"steps": ["dense_retrieval"], "retrieval_queries": [], "reasoning": "parse failed"}
    return parse_json_output(response, default)


def parse_grounded_answer(response: LLMResponse) -> dict[str, Any]:
    """Parse answer generator output."""
    default = {
        "answer_markdown": "证据不足，无法生成回答。",
        "citations": [],
        "used_sources": [],
        "unsupported_claims": ["LLM response could not be parsed"],
        "hallucination_risk": "high",
    }
    return parse_json_output(response, default)
