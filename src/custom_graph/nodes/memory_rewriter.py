"""Phase 8 v1.2: Memory rewriter — LTM-aware query rewriting.

Approved long-term memory:
  - 在 rewrite 之前读取
  - 合并到 combined memory_context
  - 通过关键词匹配影响 rewrite
  - pending/disabled 不进入 context
"""

from __future__ import annotations

import time
from typing import Any

from custom_graph.state import GraphState
from llm.client import LLMClient
from llm.errors import LLMError


def _ltm_keywords_influence(approved_items: list[dict], query: str) -> tuple[str, list[str], bool]:
    """检查 approved memory 是否包含与 query 相关的约束关键词。

    Returns (influence_text, used_ids, ltm_used_for_rewrite).
    """
    if not approved_items:
        return "", [], False

    keywords = [
        "HPC",
        "本地",
        "禁止",
        "必须",
        "只能",
        "不允许",
        "bge-m3",
        "embedding",
        "Chroma",
        "retrieval eval",
        "检索",
        "评测",
        "策略",
        "配置",
    ]
    relevant: list[dict] = []
    for item in approved_items:
        content = item.get("content", "")
        if any(kw in content for kw in keywords):
            relevant.append(item)

    if not relevant:
        return "", [], False

    parts = [f"[approved memory] {m['content']}" for m in relevant]
    used_ids = [m["memory_id"] for m in relevant]
    return "LTM constraints: " + "; ".join(parts), used_ids, True


def _rewrite_query_legacy(state: GraphState, llm: LLMClient | None = None) -> dict[str, Any]:
    llm = llm or LLMClient()
    t0 = time.perf_counter()

    from session_memory.session_memory import SessionMemoryManager

    mgr = SessionMemoryManager(session_id=state.session_id)
    mgr.get_or_create()

    # ── Step 0: Long-term memory (APPROVED ONLY, before rewrite) ──────
    from long_term_memory.schema import LongTermMemoryTrace
    from long_term_memory.service import get_ltm_service

    ltm_svc = get_ltm_service()
    approved_items = ltm_svc.list_approved_items()
    ltm_context_str, approved_ids = ltm_svc.read_context()
    ltm_influence, ltm_used_ids, ltm_used_for_rewrite = _ltm_keywords_influence(
        approved_items, state.query
    )

    pending_count = len(ltm_svc.list_pending_candidates())
    ltm_trace = LongTermMemoryTrace(
        long_term_memory_used=len(approved_ids) > 0,
        approved_memory_count=len(approved_ids),
        pending_candidate_count=pending_count,
        memory_write_status="none",
        long_term_memory_scope="project:enterprise_kb_v1",
        approved_memory_ids=approved_ids,
    )

    # ── Step 1: Coreference rewrite ──────────────────────────────────
    rewritten, rewrite_debug = mgr.rewrite_coreference(state.query)

    # ── Step 2: LLM rewrite (mock fallback) ──────────────────────────
    if llm.is_mock and not rewrite_debug.get("rewrite_used_memory"):
        rewritten = state.query
        llm_changes = "mock: no rewriting"
    elif llm.is_mock:
        if ltm_influence:
            rewritten = f"[{ltm_influence}] {rewritten}"
        llm_changes = "mock: coreference rewrite only"
    else:
        try:
            from llm.json_output_parser import parse_json_output
            from llm.prompt_registry import build_rewriter_prompt

            messages = build_rewriter_prompt(state.query)
            response = llm.generate(messages)
            parsed = parse_json_output(response)
            rewritten = parsed.get("rewritten_query", rewritten)
            llm_changes = parsed.get("changes", "LLM rewritten")
        except LLMError:
            raise
        except Exception:
            llm_changes = "rewriter failed, using original"

    # ── Step 3: Detect active_topic ──────────────────────────────────
    topic = mgr.detect_topic(state.query)
    if topic != "general":
        mgr.store.update_active_topic(mgr.session_id, topic)

    # ── Step 4: Combined memory context (session + LTM) ──────────────
    session_context = mgr.build_context()
    combined_context = session_context
    if ltm_context_str:
        combined_context = session_context + "\n" + ltm_context_str

    # ── Step 5: Memory write candidates ──────────────────────────────
    memory_candidates = mgr.maybe_write_candidates(
        query=state.query, rewritten_query=rewritten, intent=state.intent
    )

    # ── Step 6: Build trace ──────────────────────────────────────────
    memory_trace = mgr.build_trace(
        query=state.query,
        rewritten_query=rewritten,
        rewrite_used_memory=rewrite_debug.get("rewrite_used_memory", False),
        memory_candidates=memory_candidates,
    )

    latency = round((time.perf_counter() - t0) * 1000, 2)
    bool(ltm_influence)

    return {
        "session_id": mgr.session_id,
        "rewritten_query": rewritten,
        "memory_context": combined_context,
        "memory_trace": memory_trace.to_dict(),
        "long_term_memory_context": ltm_context_str,
        "long_term_memory_trace": ltm_trace.to_dict(),
        "approved_memories": approved_ids,
        "memory_candidates": memory_candidates,
        "rewrite_trace": {
            "original_query": state.query,
            "rewritten_query": rewritten,
            "changes": llm_changes if "llm_changes" in dir() else "rewrite applied",
            "rewrite_used_memory": rewrite_debug.get("rewrite_used_memory", False),
            "memory_sources": rewrite_debug.get("memory_sources", []),
            "introduced_new_facts": rewrite_debug.get("introduced_new_facts", False),
            "rewrite_reason": rewrite_debug.get("rewrite_reason", ""),
            "long_term_memory_used_for_rewrite": ltm_used_for_rewrite,
            "approved_memory_ids_used": ltm_used_ids,
            "latency_ms": latency,
            "llm_mode": "mock" if llm.is_mock else "grounded_llm",
        },
    }


def rewrite_query(state: GraphState, llm: LLMClient | None = None) -> dict[str, Any]:
    """Run project-scoped session and governed-memory rewriting."""
    from custom_graph.memory_runtime import rewrite_query_v2

    return rewrite_query_v2(state, llm)
