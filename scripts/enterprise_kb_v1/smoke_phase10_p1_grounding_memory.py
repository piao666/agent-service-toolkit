"""P1 semantic grounding, multi-turn focus, and governed-memory smoke checks."""

from __future__ import annotations

import json
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src"
REPORT = ROOT / "reports" / "enterprise_kb_v1" / "phase10_p1_grounding_memory_smoke.json"
sys.path.insert(0, str(SRC))


CHUNKS = [
    {
        "chunk_id": "fastapi_middleware_1",
        "source_id": "fastapi_official_middleware",
        "heading_path": "Middleware > Create middleware",
        "text_preview": (
            "FastAPI middleware runs before every request handler and before every response. "
            "Use the app.middleware decorator to register it."
        ),
        "score": 0.91,
        "corpus": "official_docs",
        "origin_url": "https://fastapi.tiangolo.com/tutorial/middleware/",
    },
    {
        "chunk_id": "bge_eval_1",
        "source_id": "phase6f_bge_eval",
        "heading_path": "Phase 6F > Embedding evaluation",
        "text_preview": "The bge-m3 retrieval evaluation reports hit@3, hit@10, and MRR.",
        "score": 0.89,
        "corpus": "internal_engineering_docs",
        "origin_url": "phase6f_bge_eval",
    },
]


def _check(name: str, passed: bool, detail: object = "") -> dict[str, object]:
    return {"name": name, "passed": bool(passed), "detail": detail}


def main() -> int:
    from custom_graph.grounding import build_mock_extractive_answer
    from custom_graph.memory_runtime import build_final_response_v2, rewrite_query_v2
    from custom_graph.nodes.evidence_verifier import verify_evidence
    from custom_graph.state import GraphState
    from llm.client import LLMClient
    from long_term_memory.service import LongTermMemoryService
    from long_term_memory.sqlite_store import LongTermMemoryStore
    from session_memory.scoped_manager import ScopedSessionMemoryManager
    from session_memory.store import MemoryStore, get_memory_store

    checks: list[dict[str, object]] = []
    query = "How does FastAPI middleware modify a response?"
    answer = build_mock_extractive_answer(query, CHUNKS)
    good_state = GraphState(
        query=query,
        rewritten_query=query,
        citations=answer["citations"],
        ranked_results=CHUNKS,
    )
    good = verify_evidence(good_state)
    checks.append(
        _check(
            "mock_answer_excludes_semantically_unrelated_chunks",
            len(answer["citations"]) == 1
            and answer["citations"][0]["chunk_id"] == "fastapi_middleware_1"
            and good["citation_validity"]
            and good["citation_trace"]["citation_semantic_support"],
            good["citation_trace"],
        )
    )

    unrelated_citation = {
        "citation_id": "cite_wrong_topic",
        "chunk_id": "bge_eval_1",
        "source_id": "phase6f_bge_eval",
        "quoted_evidence": CHUNKS[1]["text_preview"],
    }
    unrelated = verify_evidence(
        GraphState(query=query, citations=[unrelated_citation], ranked_results=CHUNKS)
    )
    checks.append(
        _check(
            "valid_chunk_id_does_not_imply_semantic_validity",
            unrelated["all_citations_from_retrieved"]
            and unrelated["citation_trace"]["citation_id_validity"]
            and not unrelated["citation_trace"]["citation_semantic_support"]
            and not unrelated["citation_validity"]
            and unrelated["hallucination_risk"] == "high",
            unrelated["citation_trace"],
        )
    )

    forged_quote = dict(answer["citations"][0])
    forged_quote["quoted_evidence"] = "This sentence was never present in the source chunk."
    quote_result = verify_evidence(
        GraphState(query=query, citations=[forged_quote], ranked_results=CHUNKS)
    )
    checks.append(
        _check(
            "quoted_evidence_must_match_source_text",
            quote_result["citation_trace"]["citation_id_validity"]
            and not quote_result["citation_trace"]["citation_quote_validity"]
            and not quote_result["citation_validity"],
            quote_result["citation_trace"],
        )
    )

    session_store = MemoryStore(max_sessions=10, max_turns_per_session=5)
    project_a = ScopedSessionMemoryManager("shared-session", "project_a", session_store)
    project_a.add_turn(
        query="What is FastAPI middleware?",
        rewritten_query="What is FastAPI middleware?",
    )
    rewritten, rewrite_trace = project_a.rewrite_coreference("How does it modify a response?")
    project_b = ScopedSessionMemoryManager("shared-session", "project_b", session_store)
    other_rewrite, other_trace = project_b.rewrite_coreference("How does it modify a response?")
    checks.append(
        _check(
            "multi_turn_focus_is_project_scoped",
            "FastAPI middleware" in rewritten
            and rewrite_trace["rewrite_used_memory"]
            and other_rewrite == "How does it modify a response?"
            and not other_trace["rewrite_used_memory"],
            {"project_a": rewritten, "project_b": other_rewrite},
        )
    )

    with tempfile.TemporaryDirectory() as temp_dir:
        store = LongTermMemoryStore(str(Path(temp_dir) / "ltm.sqlite"))
        service = LongTermMemoryService(store=store)

        relevant_candidate = store.create_candidate(
            content="FastAPI middleware answers must cite official evidence.",
            scope_id="project_a",
        )
        relevant_memory = store.approve_candidate(relevant_candidate["candidate_id"])
        unrelated_candidate = store.create_candidate(
            content="bge-m3 embedding evaluation must run on HPC.",
            scope_id="project_a",
        )
        unrelated_memory = store.approve_candidate(unrelated_candidate["candidate_id"])
        other_project_candidate = store.create_candidate(
            content="FastAPI middleware may use unverified sources.",
            scope_id="project_b",
        )
        other_project_memory = store.approve_candidate(other_project_candidate["candidate_id"])

        import custom_graph.memory_runtime as memory_runtime

        original_get_service = memory_runtime.get_ltm_service
        memory_runtime.get_ltm_service = lambda: service
        get_memory_store().clear()
        try:
            state = GraphState(
                query=query,
                session_id="ltm-session",
                project_id="project_a",
            )
            rewritten_output = rewrite_query_v2(
                state,
                LLMClient(provider="mock", allow_fallback=False),
            )
            state.rewritten_query = rewritten_output["rewritten_query"]
            state.memory_context = rewritten_output["memory_context"]
            state.memory_trace = rewritten_output["memory_trace"]
            state.long_term_memory_context = rewritten_output["long_term_memory_context"]
            state.long_term_memory_trace = rewritten_output["long_term_memory_trace"]
            state.rewrite_trace = rewritten_output["rewrite_trace"]
            state.answer_markdown = answer["answer_markdown"]
            state.citations = answer["citations"]
            state.used_sources = answer["used_sources"]
            final = build_final_response_v2(state)["final_response"]
        finally:
            memory_runtime.get_ltm_service = original_get_service

        trace = final["long_term_memory_trace"]
        checks.append(
            _check(
                "ltm_distinguishes_available_from_applied",
                trace["available_approved_memory_count"] == 2
                and relevant_memory["memory_id"] in trace["applied_memory_ids"]
                and unrelated_memory["memory_id"] not in trace["applied_memory_ids"]
                and other_project_memory["memory_id"] not in trace["approved_memory_ids"]
                and not trace["used_for_rewrite"]
                and trace["used_for_answer"]
                and trace["long_term_memory_used"],
                trace,
            )
        )

        disabled = service.disable(relevant_memory["memory_id"])
        remaining = service.list_approved_items(scope_id="project_a")
        checks.append(
            _check(
                "disabled_memory_is_excluded_from_active_context",
                disabled
                and relevant_memory["memory_id"] not in {item["memory_id"] for item in remaining},
            )
        )

    passed = all(bool(item["passed"]) for item in checks)
    payload = {
        "phase": "P1",
        "timestamp": datetime.now(UTC).isoformat(),
        "passed": passed,
        "checks": checks,
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
