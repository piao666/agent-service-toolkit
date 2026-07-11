"""Phase 10 project-scoped session and governed long-term memory runtime."""

from __future__ import annotations

import time
from typing import Any

from custom_graph.grounding import semantic_overlap_score
from custom_graph.state import GraphState
from llm.client import LLMClient
from llm.errors import LLMError
from long_term_memory.schema import LongTermMemoryTrace
from long_term_memory.service import get_ltm_service
from session_memory.scoped_manager import ScopedSessionMemoryManager

_CONSTRAINT_MARKERS = (
    "must",
    "always",
    "never",
    "only",
    "do not",
    "禁止",
    "必须",
    "只能",
    "不允许",
)


def select_relevant_memories(
    approved_items: list[dict[str, Any]],
    query: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return relevant memories plus redacted relevance diagnostics."""
    selected: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    for item in approved_items:
        content = str(item.get("content", ""))
        score, shared = semantic_overlap_score(query, content)
        has_constraint = any(marker in content.lower() for marker in _CONSTRAINT_MARKERS)
        relevant = score >= 0.2 and (len(shared) >= 2 or score >= 0.5)
        if has_constraint and shared and score >= 0.1:
            relevant = True
        diagnostics.append(
            {
                "memory_id": item.get("memory_id", ""),
                "semantic_score": score,
                "shared_query_tokens": shared,
                "constraint_marker": has_constraint,
                "selected": relevant,
            }
        )
        if relevant:
            selected.append(item)
    return selected, diagnostics


def _memory_context(items: list[dict[str, Any]]) -> str:
    if not items:
        return ""
    parts = [
        f"[{item.get('memory_type', 'constraint')}] {item.get('content', '')}" for item in items
    ]
    return "Approved long-term memories:\n" + "\n".join(parts)


def rewrite_query_v2(state: GraphState, llm: LLMClient | None = None) -> dict[str, Any]:
    llm = llm or LLMClient()
    started = time.perf_counter()
    manager = ScopedSessionMemoryManager(
        session_id=state.session_id,
        project_id=state.project_id,
    )
    manager.get_or_create()

    service = get_ltm_service()
    approved = service.list_approved_items(scope_id=state.project_id)
    relevant, relevance_trace = select_relevant_memories(approved, state.query)
    relevant_context = _memory_context(relevant)
    approved_ids = [str(item["memory_id"]) for item in approved]
    applied_ids = [str(item["memory_id"]) for item in relevant]

    rewritten, rewrite_debug = manager.rewrite_coreference(state.query)
    llm_changes = "deterministic coreference rewrite"
    used_for_rewrite = False
    if not llm.is_mock:
        try:
            from llm.json_output_parser import parse_json_output
            from llm.prompt_registry import build_rewriter_prompt

            history = [manager.build_context()]
            if relevant_context:
                history.append(relevant_context)
                used_for_rewrite = True
            response = llm.generate(build_rewriter_prompt(rewritten, history=history))
            parsed = parse_json_output(response)
            rewritten = str(parsed.get("rewritten_query", rewritten))
            llm_changes = str(parsed.get("changes", "LLM rewritten"))
        except LLMError:
            raise
        except Exception:
            llm_changes = "LLM rewrite parse failed; deterministic rewrite retained"

    topic = manager.detect_topic(state.query)
    if topic != "general":
        manager.update_active_topic(topic)
    session_context = manager.build_context()
    memory_candidates = manager.maybe_write_candidates(
        query=state.query,
        rewritten_query=rewritten,
    )
    memory_trace = manager.build_trace(
        rewritten_query=rewritten,
        rewrite_used_memory=bool(rewrite_debug.get("rewrite_used_memory")),
        memory_candidates=memory_candidates,
    )
    ltm_trace = LongTermMemoryTrace(
        long_term_memory_used=used_for_rewrite,
        approved_memory_count=len(approved),
        available_approved_memory_count=len(approved),
        pending_candidate_count=len(service.list_pending_candidates(scope_id=state.project_id)),
        memory_write_status="none",
        long_term_memory_scope=f"project:{state.project_id}",
        approved_memory_ids=approved_ids,
        applied_memory_ids=applied_ids,
        used_for_rewrite=used_for_rewrite,
        used_for_answer=False,
    )

    latency = round((time.perf_counter() - started) * 1000, 2)
    return {
        "session_id": manager.session_id,
        "rewritten_query": rewritten,
        "memory_context": session_context,
        "memory_trace": memory_trace.to_dict(),
        "long_term_memory_context": relevant_context,
        "long_term_memory_trace": ltm_trace.to_dict(),
        "approved_memories": approved_ids,
        "memory_candidates": memory_candidates,
        "rewrite_trace": {
            "original_query": state.query,
            "rewritten_query": rewritten,
            "changes": llm_changes,
            "rewrite_used_memory": bool(rewrite_debug.get("rewrite_used_memory")),
            "memory_sources": rewrite_debug.get("memory_sources", []),
            "rewrite_reason": rewrite_debug.get("rewrite_reason", ""),
            "last_focus": rewrite_debug.get("last_focus", ""),
            "long_term_memory_used_for_rewrite": used_for_rewrite,
            "approved_memory_ids_used": applied_ids if used_for_rewrite else [],
            "relevant_memory_ids": applied_ids,
            "memory_relevance": relevance_trace,
            "latency_ms": latency,
            "llm_mode": "mock" if llm.is_mock else "grounded_llm",
        },
    }


def build_final_response_v2(state: GraphState) -> dict[str, Any]:
    started = time.perf_counter()
    if state.session_id:
        manager = ScopedSessionMemoryManager(
            session_id=state.session_id,
            project_id=state.project_id,
        )
        manager.add_turn(
            query=state.query,
            rewritten_query=state.rewritten_query,
            response=state.answer_markdown,
            intent=state.intent,
            sources=state.used_sources,
        )

    ltm_trace = dict(state.long_term_memory_trace)
    try:
        service = get_ltm_service()
        candidate = service.create_candidate(
            query=state.query,
            rewritten_query=state.rewritten_query,
            session_id=state.session_id,
            project_id=state.project_id,
        )
        if candidate:
            ltm_trace["memory_write_status"] = "pending_candidate_created"
            ltm_trace["last_candidate_id"] = candidate["candidate_id"]

        approved = service.list_approved_items(scope_id=state.project_id)
        approved_ids = [str(item["memory_id"]) for item in approved]
        applied_ids = list(ltm_trace.get("applied_memory_ids", []))
        used_for_rewrite = bool(ltm_trace.get("used_for_rewrite", False))
        used_for_answer = bool(state.long_term_memory_context and state.answer_markdown)
        ltm_trace.update(
            {
                "approved_memory_count": len(approved),
                "available_approved_memory_count": len(approved),
                "approved_memory_ids": approved_ids,
                "applied_memory_ids": applied_ids,
                "used_for_rewrite": used_for_rewrite,
                "used_for_answer": used_for_answer,
                "long_term_memory_used": used_for_rewrite or used_for_answer,
                "long_term_memory_scope": f"project:{state.project_id}",
                "pending_candidate_count": len(
                    service.list_pending_candidates(scope_id=state.project_id)
                ),
            }
        )
    except Exception as exc:
        state.errors.append(f"long_term_memory: {exc.__class__.__name__}")

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
        "long_term_memory_trace": ltm_trace,
        "graph_debug": {
            "nodes_executed": [
                "query_classifier",
                "memory_rewriter",
                "planner",
                "retriever",
                "ranker",
                "answer_generator",
                "evidence_verifier",
                "final_response",
            ],
            "project_id": state.project_id,
            "intent": state.intent,
            "recommended_corpus": state.recommended_corpus,
            "route_mode": state.retrieval_trace.get("route_mode", ""),
            "citation_validity": state.citation_validity,
            "citation_id_validity": state.citation_trace.get("citation_id_validity", False),
            "citation_semantic_support": state.citation_trace.get(
                "citation_semantic_support", False
            ),
            "hallucination_risk": state.hallucination_risk,
            "memory_read_used": state.memory_trace.get("memory_read_used", False),
            "long_term_memory_used": ltm_trace.get("long_term_memory_used", False),
        },
        "errors": state.errors,
    }
    response["finalize_latency_ms"] = round((time.perf_counter() - started) * 1000, 2)
    return {"final_response": response}
