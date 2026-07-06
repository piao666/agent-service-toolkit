"""Phase 5: Custom Graph — enterprise KB pipeline assembler.

Pipeline: query_classifier → memory_rewriter → planner → retriever →
           ranker → answer_generator → evidence_verifier → final_response
"""

import time
from typing import Any

from custom_graph.state import GraphState
from llm.client import LLMClient


def run_custom_graph(
    query: str,
    corpus: str = "auto",
    session_id: str = "",
    llm: LLMClient | None = None,
) -> dict[str, Any]:
    """Execute the full custom_graph pipeline and return the final response.

    Args:
        query: User query string.
        corpus: "official_docs" | "internal_engineering_docs" | "auto".
        session_id: Optional session identifier.
        llm: Optional LLMClient. If None, creates a mock client.

    Returns:
        Complete response dict with answer + citations + all traces.
    """
    llm = llm or LLMClient()
    state = GraphState(query=query, corpus=corpus, session_id=session_id)
    t_start = time.perf_counter()

    # Node 1: Query Classifier
    state_dict = _run_node("query_classifier", _classify, state, llm)
    _apply_state(state, state_dict)

    # Node 2: Memory Rewriter
    state_dict = _run_node("memory_rewriter", _rewrite, state, llm)
    _apply_state(state, state_dict)

    # Node 3: Planner
    state_dict = _run_node("planner", _plan, state, llm)
    _apply_state(state, state_dict)

    # Node 4: Retriever
    state_dict = _run_node("retriever", _retrieve, state, llm)
    _apply_state(state, state_dict)

    # Node 5: Ranker
    state_dict = _run_node("ranker", _rank, state, llm)
    _apply_state(state, state_dict)

    # Node 6: Answer Generator
    state_dict = _run_node("answer_generator", _answer, state, llm)
    _apply_state(state, state_dict)

    # Node 7: Evidence Verifier
    state_dict = _run_node("evidence_verifier", _verify, state, llm)
    _apply_state(state, state_dict)

    # Node 8: Final Response
    state_dict = _run_node("final_response", _finalize, state, llm)
    _apply_state(state, state_dict)

    total_latency = round((time.perf_counter() - t_start) * 1000, 2)
    response = state.final_response
    response["total_latency_ms"] = total_latency
    response["llm_mode"] = "mock_extractive" if llm.is_mock else "grounded_llm"
    return response


def _apply_state(state: GraphState, updates: dict[str, Any]) -> None:
    """Apply node output to state."""
    for key, value in updates.items():
        if hasattr(state, key):
            setattr(state, key, value)


def _run_node(name: str, func, state: GraphState, llm: LLMClient) -> dict[str, Any]:
    """Run a node with error handling."""
    try:
        return func(state, llm)
    except Exception as e:
        state.errors.append(f"{name}: {e}")
        return {}


# ── Node implementations (thin wrappers for lazy imports) ──────────────

def _classify(state: GraphState, llm: LLMClient) -> dict[str, Any]:
    from custom_graph.nodes.query_classifier import classify_query
    return classify_query(state, llm)


def _rewrite(state: GraphState, llm: LLMClient) -> dict[str, Any]:
    from custom_graph.nodes.memory_rewriter import rewrite_query
    return rewrite_query(state, llm)


def _plan(state: GraphState, llm: LLMClient) -> dict[str, Any]:
    from custom_graph.nodes.planner import plan_retrieval
    return plan_retrieval(state, llm)


def _retrieve(state: GraphState, llm: LLMClient) -> dict[str, Any]:
    from custom_graph.nodes.retriever import retrieve_chunks
    return retrieve_chunks(state)


def _rank(state: GraphState, llm: LLMClient) -> dict[str, Any]:
    from custom_graph.nodes.ranker import rank_results
    return rank_results(state)


def _answer(state: GraphState, llm: LLMClient) -> dict[str, Any]:
    from custom_graph.nodes.answer_generator import generate_answer
    return generate_answer(state, llm)


def _verify(state: GraphState, llm: LLMClient) -> dict[str, Any]:
    from custom_graph.nodes.evidence_verifier import verify_evidence
    return verify_evidence(state)


def _finalize(state: GraphState, llm: LLMClient) -> dict[str, Any]:
    from custom_graph.nodes.final_response import build_final_response
    return build_final_response(state)
