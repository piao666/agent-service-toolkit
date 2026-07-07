"""Phase 7: Final response — includes memory_trace in output."""

from __future__ import annotations

import time
from typing import Any

from custom_graph.state import GraphState


def build_final_response(state: GraphState) -> dict[str, Any]:
    """Assemble complete final response with memory_trace."""
    t0 = time.perf_counter()

    # 添加当前 turn 到 session memory
    if state.session_id:
        from session_memory.session_memory import SessionMemoryManager
        mgr = SessionMemoryManager(session_id=state.session_id)
        mgr.add_turn(
            query=state.query,
            rewritten_query=state.rewritten_query,
            intent=state.intent,
        )

    response = {
        "answer_markdown": state.answer_markdown,
        "citations": state.citations,
        "used_sources": state.used_sources,
        "unsupported_claims": state.unsupported_claims,
        "hallucination_risk": state.hallucination_risk,
        "intent_trace": state.intent_trace,
        "rewrite_trace": state.rewrite_trace,
        "plan_trace": state.plan_trace,
        "retrieval_trace": state.retrieval_trace,
        "rank_trace": state.rank_trace,
        "llm_trace": state.llm_trace,
        "citation_trace": state.citation_trace,
        "memory_trace": state.memory_trace,
        "graph_debug": {
            "nodes_executed": ["query_classifier", "memory_rewriter", "planner", "retriever", "ranker", "answer_generator", "evidence_verifier", "final_response"],
            "intent": state.intent,
            "recommended_corpus": state.recommended_corpus,
            "route_mode": state.retrieval_trace.get("route_mode", ""),
            "citation_validity": state.citation_validity,
            "hallucination_risk": state.hallucination_risk,
            "memory_read_used": state.memory_trace.get("memory_read_used", False),
            "memory_write_status": state.memory_trace.get("memory_write_status", "none"),
        },
        "errors": state.errors,
    }

    latency = round((time.perf_counter() - t0) * 1000, 2)
    return {"final_response": response}
