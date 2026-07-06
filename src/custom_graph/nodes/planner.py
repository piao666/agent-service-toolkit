"""Phase 5: Planner node — generates retrieval plan."""

import time
from typing import Any

from custom_graph.state import GraphState
from llm.client import LLMClient
from llm.prompt_registry import build_planner_prompt
from llm.json_output_parser import parse_plan


def plan_retrieval(state: GraphState, llm: LLMClient | None = None) -> dict[str, Any]:
    llm = llm or LLMClient()
    t0 = time.perf_counter()
    query = state.rewritten_query or state.query

    if llm.is_mock:
        steps = ["dense_retrieval"]
        queries = [query]
        reasoning = "mock: default dense retrieval plan"
    else:
        try:
            messages = build_planner_prompt(query, state.intent)
            response = llm.generate(messages)
            parsed = parse_plan(response)
            steps = parsed.get("steps", ["dense_retrieval"])
            queries = parsed.get("retrieval_queries", [query])
            reasoning = parsed.get("reasoning", "LLM planned")
        except Exception:
            steps = ["dense_retrieval"]
            queries = [query]
            reasoning = "planner failed, using default"

    latency = round((time.perf_counter() - t0) * 1000, 2)
    return {
        "plan_steps": steps,
        "plan_retrieval_queries": queries,
        "plan_trace": {"intent": state.intent, "steps": steps, "queries": queries, "reasoning": reasoning, "latency_ms": latency, "llm_mode": "mock" if llm.is_mock else "grounded_llm"},
    }
