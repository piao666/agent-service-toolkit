"""Phase 7: Memory rewriter — context-aware query rewriting with session memory.

支持:
  - 指代消解 (它/这个/继续上面)
  - session memory 上下文注入
  - project constraint 感知
  - memory write candidate 生成
"""

from __future__ import annotations

import time
from typing import Any

from custom_graph.state import GraphState
from llm.client import LLMClient


def rewrite_query(state: GraphState, llm: LLMClient | None = None) -> dict[str, Any]:
    """使用 session memory 改写 query。"""
    llm = llm or LLMClient()
    t0 = time.perf_counter()

    from session_memory.session_memory import SessionMemoryManager

    mgr = SessionMemoryManager(session_id=state.session_id)
    mem = mgr.get_or_create()

    # ── Step 1: Coreference rewrite ──────────────────────────────────
    rewritten, rewrite_debug = mgr.rewrite_coreference(state.query)

    # ── Step 2: LLM rewrite (mock fallback) ──────────────────────────
    if llm.is_mock and not rewrite_debug.get("rewrite_used_memory"):
        rewritten = state.query
        llm_changes = "mock: no rewriting"
    elif llm.is_mock:
        llm_changes = "mock: coreference rewrite only"
    else:
        try:
            from llm.prompt_registry import build_rewriter_prompt
            from llm.json_output_parser import parse_json_output
            messages = build_rewriter_prompt(state.query)
            response = llm.generate(messages)
            parsed = parse_json_output(response)
            rewritten = parsed.get("rewritten_query", rewritten)
            llm_changes = parsed.get("changes", "LLM rewritten")
        except Exception:
            llm_changes = "rewriter failed, using original"

    # ── Step 3: Detect active_topic ──────────────────────────────────
    topic = mgr.detect_topic(state.query)
    if topic != "general":
        mgr.store.update_active_topic(mgr.session_id, topic)

    # ── Step 4: Memory context ───────────────────────────────────────
    memory_context = mgr.build_context()

    # ── Step 5: Memory write candidates ──────────────────────────────
    memory_candidates = mgr.maybe_write_candidates(
        query=state.query, rewritten_query=rewritten, intent=state.intent)

    # ── Step 6: Build trace ──────────────────────────────────────────
    memory_trace = mgr.build_trace(
        query=state.query,
        rewritten_query=rewritten,
        rewrite_used_memory=rewrite_debug.get("rewrite_used_memory", False),
        memory_candidates=memory_candidates,
    )

    latency = round((time.perf_counter() - t0) * 1000, 2)

    return {
        "session_id": mgr.session_id,  # v1.3: auto id 回写 GraphState
        "rewritten_query": rewritten,
        "memory_context": memory_context,
        "memory_trace": memory_trace.to_dict(),
        "memory_candidates": memory_candidates,
        "rewrite_trace": {
            "original_query": state.query,
            "rewritten_query": rewritten,
            "changes": llm_changes if 'llm_changes' in dir() else "rewrite applied",
            "rewrite_used_memory": rewrite_debug.get("rewrite_used_memory", False),
            "memory_sources": rewrite_debug.get("memory_sources", []),
            "introduced_new_facts": rewrite_debug.get("introduced_new_facts", False),
            "rewrite_reason": rewrite_debug.get("rewrite_reason", ""),
            "latency_ms": latency,
            "llm_mode": "mock" if llm.is_mock else "grounded_llm",
        },
    }
