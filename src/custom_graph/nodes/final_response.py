"""Phase 5: Final response assembler — combines all traces into the final output."""

import time
from typing import Any

from custom_graph.state import GraphState


def build_final_response(state: GraphState) -> dict[str, Any]:
    """Assemble the complete final response with all traces."""
    t0 = time.perf_counter()
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
        "graph_debug": {
            "nodes_executed": ["query_classifier", "memory_rewriter", "planner", "retriever", "ranker", "answer_generator", "evidence_verifier", "final_response"],
            "intent": state.intent,
            "recommended_corpus": state.recommended_corpus,
            "route_mode": state.retrieval_trace.get("route_mode", ""),
            "citation_validity": state.citation_validity,
            "hallucination_risk": state.hallucination_risk,
        },
        "errors": state.errors,
    }

    latency = round((time.perf_counter() - t0) * 1000, 2)
    return {"final_response": response}
