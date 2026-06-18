from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from rag.conversation_memory import (  # noqa: E402
    ConversationMemoryStore,
    contextualize_query_with_memory,
)


def main() -> None:
    store = ConversationMemoryStore(max_turns=2, max_answer_chars=80)
    source = {
        "title": "RAG Overview",
        "chunk_id": "chunk-rag-001",
        "content": "This full chunk body must not be retained in memory.",
        "metadata": {
            "source_id": "rag_overview",
            "source_url": "https://example.invalid/rag",
        },
    }

    appended = store.append_turn(
        "session-a",
        "RAG 是什么？",
        "RAG 使用检索到的外部知识辅助生成回答。",
        [source],
    )
    memory_store_append_ok = appended is not None and store.get_turn_count("session-a") == 1
    source_summary_safe = bool(
        appended
        and appended.sources
        and "content" not in appended.sources[0]
        and appended.sources[0]["source_id"] == "rag_overview"
    )

    cross_session_isolation_ok = (
        store.get_turn_count("session-b") == 0
        and store.get_recent_turns("session-b") == []
    )

    contextual_query, follow_up_debug = contextualize_query_with_memory(
        query="它有什么局限？",
        session_id="session-a",
        memory_mode="buffer",
        store=store,
    )
    follow_up_rewrite_ok = (
        follow_up_debug["is_follow_up"] is True
        and follow_up_debug["memory_used_for_retrieval"] is True
        and "RAG" in contextual_query
    )

    off_query, off_debug = contextualize_query_with_memory(
        query="它有什么局限？",
        session_id="session-a",
        memory_mode="off",
        store=store,
    )
    memory_off_noop_ok = (
        off_query == "它有什么局限？"
        and off_debug["memory_enabled"] is False
        and off_debug["memory_used_for_retrieval"] is False
    )

    no_session_query, no_session_debug = contextualize_query_with_memory(
        query="它有什么局限？",
        session_id=None,
        memory_mode="buffer",
        store=store,
    )
    missing_session_noop_ok = (
        no_session_query == "它有什么局限？"
        and no_session_debug["memory_enabled"] is False
    )

    clear_ok = store.clear_session("session-a") and store.get_turn_count("session-a") == 0

    checks = {
        "memory_store_append_ok": memory_store_append_ok,
        "source_summary_safe": source_summary_safe,
        "cross_session_isolation_ok": cross_session_isolation_ok,
        "follow_up_rewrite_ok": follow_up_rewrite_ok,
        "memory_off_noop_ok": memory_off_noop_ok,
        "missing_session_noop_ok": missing_session_noop_ok,
        "clear_session_ok": clear_ok,
        "calls_llm": False,
        "writes_chroma": False,
    }
    for name, value in checks.items():
        print(f"{name}={value}")

    required = [value for name, value in checks.items() if name not in {"calls_llm", "writes_chroma"}]
    if not all(required):
        raise SystemExit("Phase 6G memory smoke checks failed")


if __name__ == "__main__":
    main()
