"""Phase 5: Memory rewriter node — expands query with conversation context."""

import time
from typing import Any

from custom_graph.state import GraphState
from llm.client import LLMClient
from llm.prompt_registry import build_rewriter_prompt
from llm.json_output_parser import parse_json_output


def rewrite_query(state: GraphState, llm: LLMClient | None = None) -> dict[str, Any]:
    llm = llm or LLMClient()
    t0 = time.perf_counter()

    if llm.is_mock:
        # Mock: use original query as-is
        rewritten = state.query
        changes = "mock: no rewriting"
    else:
        try:
            messages = build_rewriter_prompt(state.query)
            response = llm.generate(messages)
            parsed = parse_json_output(response)
            rewritten = parsed.get("rewritten_query", state.query)
            changes = parsed.get("changes", "LLM rewritten")
        except Exception:
            rewritten = state.query
            changes = "rewriter failed, using original"

    latency = round((time.perf_counter() - t0) * 1000, 2)
    return {
        "rewritten_query": rewritten,
        "rewrite_trace": {"original_query": state.query, "rewritten_query": rewritten, "changes": changes, "latency_ms": latency, "llm_mode": "mock" if llm.is_mock else "grounded_llm"},
    }
