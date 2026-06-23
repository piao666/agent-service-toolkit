from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from agents.enterprise_rag_graph import (  # noqa: E402
    build_enterprise_rag_graph,
    run_enterprise_rag_graph,
)
from rag.config import rag_settings  # noqa: E402
from rag.conversation_memory import get_memory_store  # noqa: E402

OUTPUT_PATH = (
    REPO_ROOT / "data/knowledge_base/evaluation/phase6j_graph_smoke_results.json"
)
REQUIRED_RESPONSE_FIELDS = {
    "answer",
    "sources",
    "citations",
    "query_type",
    "planner_debug",
    "memory_debug",
    "retrieval_debug",
    "verifier_debug",
    "judge_debug",
    "graph_debug",
}


def fake_retriever(query: str, top_k: int | None) -> dict[str, Any]:
    sources = [
        {
            "source_id": "rag_overview",
            "title": "RAG Overview",
            "doc_type": "markdown",
            "section_path": "Concepts / RAG",
            "source_url": "https://docs.example.invalid/rag-overview",
            "chunk_id": "rag-overview-001",
            "content_preview": (
                "RAG combines retrieval evidence with generation. "
                "It grounds answers in knowledge-base sources."
            ),
            "relevance_score": 0.95,
            "metadata": {"source_id": "rag_overview"},
        }
    ][: max(1, int(top_k or 1))]
    return {
        "context": sources[0]["content_preview"],
        "sources": sources,
        "retrieval_debug": {
            "hit_count": len(sources),
            "embedding_provider": "smoke_stub",
            "vector_store": "none",
        },
        "fallback": {"triggered": False, "reason": None},
    }


def fake_answer_generator(query: str, sources: list[dict[str, Any]]) -> str:
    if not sources:
        return "No evidence was available."
    return "RAG combines retrieval evidence with generation and grounds answers in sources."


def _nodes(response: dict[str, Any]) -> list[str]:
    return list((response.get("graph_debug") or {}).get("nodes_executed") or [])


def main() -> int:
    errors: list[str] = []
    original_memory_mode = rag_settings.ENTERPRISE_MEMORY_MODE
    store = get_memory_store()
    session_id = "phase6j-smoke-memory"
    store.clear_session(session_id)
    try:
        graph = build_enterprise_rag_graph(
            retriever=fake_retriever,
            answer_generator=fake_answer_generator,
            verifier_mode="rule_based",
        )
        graph_import_ok = True
        graph_build_ok = graph is not None
        mermaid = graph.get_graph().draw_mermaid()
        mermaid_available = all(
            node in mermaid
            for node in (
                "query_classifier",
                "planner",
                "memory_rewriter",
                "retriever",
                "ranker",
                "answer_generator",
                "evidence_verifier",
                "judge",
                "final_response",
            )
        )

        semantic = asyncio.run(run_enterprise_rag_graph("What is RAG?", graph=graph))
        ambiguous = asyncio.run(run_enterprise_rag_graph("继续", graph=graph))
        unsupported = asyncio.run(
            run_enterprise_rag_graph("今天的股票价格是多少？", graph=graph)
        )

        rag_settings.ENTERPRISE_MEMORY_MODE = "buffer"
        store.append_turn(
            session_id,
            "RAG 是什么？",
            "RAG 是检索增强生成。",
            [{"source_id": "rag_overview", "title": "RAG Overview"}],
        )
        memory_follow_up = asyncio.run(
            run_enterprise_rag_graph(
                "它有什么局限？",
                session_id=session_id,
                graph=graph,
            )
        )

        semantic_nodes = _nodes(semantic)
        semantic_route_ok = semantic.get("query_type") == "semantic_qa" and semantic_nodes == [
            "query_classifier",
            "memory_rewriter",
            "planner",
            "retriever",
            "ranker",
            "answer_generator",
            "evidence_verifier",
            "judge",
            "final_response",
        ]
        ambiguous_route_ok = ambiguous.get("query_type") == "ambiguous_query" and _nodes(
            ambiguous
        ) == ["query_classifier", "clarification_response", "final_response"]
        unsupported_route_ok = unsupported.get("query_type") == "unsupported_query" and _nodes(
            unsupported
        ) == ["query_classifier", "safe_response", "final_response"]
        memory_debug = memory_follow_up.get("memory_debug") or {}
        memory_rewriter_node_ok = bool(
            memory_follow_up.get("query_type") == "memory_follow_up"
            and memory_debug.get("memory_used_for_retrieval") is True
            and "RAG" in str(memory_debug.get("contextual_query") or "")
        )
        retriever_node_ok = semantic.get("retrieval_debug", {}).get("hit_count") == 1
        answer_generator_node_ok = bool(semantic.get("answer"))
        evidence_verifier_node_ok = bool(
            semantic.get("verifier_debug", {}).get("verifier_mode") == "rule_based"
        )
        judge_node_ok = bool(
            semantic.get("judge_debug", {}).get("judge_mode") == "rule_based_fallback"
        )
        final_response_schema_ok = REQUIRED_RESPONSE_FIELDS.issubset(semantic)
    except Exception as exc:
        errors.append(f"{type(exc).__name__}: {exc}")
        graph_import_ok = "graph_import_ok" in locals() and graph_import_ok
        graph_build_ok = False
        mermaid_available = False
        semantic_route_ok = False
        ambiguous_route_ok = False
        unsupported_route_ok = False
        memory_rewriter_node_ok = False
        retriever_node_ok = False
        answer_generator_node_ok = False
        evidence_verifier_node_ok = False
        judge_node_ok = False
        final_response_schema_ok = False
    finally:
        rag_settings.ENTERPRISE_MEMORY_MODE = original_memory_mode
        store.clear_session(session_id)

    summary = {
        "phase": "6J_langgraph_smoke",
        "graph_import_ok": graph_import_ok,
        "graph_build_ok": graph_build_ok,
        "mermaid_available": mermaid_available,
        "semantic_route_ok": semantic_route_ok,
        "ambiguous_route_ok": ambiguous_route_ok,
        "unsupported_route_ok": unsupported_route_ok,
        "memory_rewriter_node_ok": memory_rewriter_node_ok,
        "retriever_node_ok": retriever_node_ok,
        "answer_generator_node_ok": answer_generator_node_ok,
        "evidence_verifier_node_ok": evidence_verifier_node_ok,
        "judge_node_ok": judge_node_ok,
        "final_response_schema_ok": final_response_schema_ok,
        "calls_llm": False,
        "writes_chroma": False,
        "error_count": len(errors),
        "errors": errors,
    }
    required_checks = (
        "graph_import_ok",
        "graph_build_ok",
        "semantic_route_ok",
        "ambiguous_route_ok",
        "unsupported_route_ok",
        "final_response_schema_ok",
    )
    summary["recommended_checkpoint"] = bool(
        all(summary[key] is True for key in required_checks)
        and summary["error_count"] == 0
        and summary["calls_llm"] is False
        and summary["writes_chroma"] is False
    )

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["recommended_checkpoint"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
