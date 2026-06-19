from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from rag.conversation_memory import (  # noqa: E402
    ConversationMemoryStore,
    contextualize_query_with_memory,
)

DEFAULT_CASES = REPO_ROOT / "data/knowledge_base/evaluation/phase6g_memory_cases.jsonl"
DEFAULT_RESULTS = (
    REPO_ROOT / "data/knowledge_base/evaluation/phase6g_memory_eval_results.jsonl"
)
DEFAULT_SUMMARY = REPO_ROOT / "data/knowledge_base/evaluation/phase6g_memory_eval_summary.json"
MEMORY_DEBUG_FIELDS = {
    "memory_mode",
    "memory_enabled",
    "session_id",
    "memory_turn_count_before",
    "memory_turn_count_after",
    "is_follow_up",
    "original_query",
    "contextual_query",
    "memory_rewrite_strategy",
    "memory_used_for_retrieval",
    "memory_written",
    "cross_session_isolated",
}
SAFE_SOURCE_FIELDS = {"source_id", "title", "chunk_id", "source_url"}


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Phase 6G local memory evaluation.")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    return parser.parse_args()


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def _source_payload(turn: dict[str, Any]) -> list[dict[str, Any]]:
    fixture = turn.get("source_fixture")
    if not fixture:
        return []
    return [
        {
            "title": fixture.get("title", ""),
            "chunk_id": fixture.get("chunk_id", ""),
            "source_url": fixture.get("source_url", ""),
            "content": fixture.get("content", ""),
            "metadata": {
                "source_id": fixture.get("source_id", ""),
                "title": fixture.get("title", ""),
                "chunk_id": fixture.get("chunk_id", ""),
                "source_url": fixture.get("source_url", ""),
            },
        }
    ]


def _evaluate_turn(
    case: dict[str, Any],
    turn: dict[str, Any],
    turn_index: int,
    session_id: str | None,
    store: ConversationMemoryStore,
) -> dict[str, Any]:
    original_query = turn["query"]
    contextual_query, memory_debug = contextualize_query_with_memory(
        query=original_query,
        session_id=session_id,
        memory_mode=case["memory_mode"],
        store=store,
    )
    expected_enabled = bool(case["expected_memory_enabled"])
    expected_detection = bool(turn.get("expected_detection", turn["expected_follow_up"]))
    expected_contextualized = bool(
        turn.get("expected_contextualized", turn.get("expected_contextual_query_contains"))
    )
    sources = _source_payload(turn)
    if memory_debug["memory_enabled"] and session_id:
        saved_turn = store.append_turn(
            session_id=session_id,
            user_query=original_query,
            assistant_answer=turn.get("answer", "Offline evaluation answer."),
            sources=sources,
        )
        memory_debug["memory_turn_count_after"] = store.get_turn_count(session_id)
        memory_debug["memory_written"] = saved_turn is not None
    else:
        saved_turn = None
        memory_debug["memory_turn_count_after"] = memory_debug.get(
            "memory_turn_count_before", 0
        )
        memory_debug["memory_written"] = False

    contains_terms = turn.get("expected_contextual_query_contains", [])
    context_terms_hit = all(term.lower() in contextual_query.lower() for term in contains_terms)
    contextualized = contextual_query != original_query
    forbidden_topics = turn.get("forbidden_context_topics", [])
    leaked_topics = [topic for topic in forbidden_topics if topic.lower() in contextual_query.lower()]
    debug_fields_complete = MEMORY_DEBUG_FIELDS.issubset(memory_debug)

    source_summary_safe: bool | None = None
    if case.get("validate_source_summary"):
        source_summary_safe = bool(
            saved_turn
            and saved_turn.sources
            and all(set(source) == SAFE_SOURCE_FIELDS for source in saved_turn.sources)
            and all("content" not in source for source in saved_turn.sources)
            and all(len(value) <= 500 for source in saved_turn.sources for value in source.values())
        )

    checks = {
        "memory_enabled_matches": memory_debug["memory_enabled"] is expected_enabled,
        "follow_up_detection_matches": memory_debug["is_follow_up"] is expected_detection,
        "contextualization_matches": contextualized is expected_contextualized,
        "expected_context_terms_present": context_terms_hit,
        "cross_session_isolated": not leaked_topics,
        "memory_debug_complete": debug_fields_complete,
        "write_behavior_matches": memory_debug["memory_written"] is expected_enabled,
    }
    if source_summary_safe is not None:
        checks["source_summary_safe"] = source_summary_safe

    errors = [name for name, passed in checks.items() if not passed]
    return {
        "case_id": case["case_id"],
        "case_type": case["case_type"],
        "session_id": session_id,
        "turn_index": turn_index,
        "query": original_query,
        "contextual_query": contextual_query,
        "expected_follow_up": bool(turn["expected_follow_up"]),
        "expected_contextualized": expected_contextualized,
        "context_hit": context_terms_hit if expected_contextualized else None,
        "leaked_topics": leaked_topics,
        "source_summary_safe": source_summary_safe,
        "memory_debug": memory_debug,
        "checks": checks,
        "errors": errors,
        "passed": not errors,
    }


def _run_case(case: dict[str, Any]) -> list[dict[str, Any]]:
    store = ConversationMemoryStore(max_turns=5, max_answer_chars=1000)
    results: list[dict[str, Any]] = []
    sequences = [(case.get("session_id"), case["turns"])]
    if case.get("comparison_turns") is not None:
        sequences.append((case.get("comparison_session_id"), case["comparison_turns"]))
    for session_id, turns in sequences:
        for turn_index, turn in enumerate(turns, start=1):
            results.append(_evaluate_turn(case, turn, turn_index, session_id, store))
    return results


def _build_summary(cases: list[dict[str, Any]], results: list[dict[str, Any]]) -> dict[str, Any]:
    follow_up_results = [row for row in results if row["expected_follow_up"]]
    eligible_context_results = [row for row in results if row["expected_contextualized"]]
    contextualized_results = [
        row
        for row in eligible_context_results
        if row["memory_debug"]["memory_used_for_retrieval"]
    ]
    context_hits = [row for row in eligible_context_results if row["context_hit"]]
    case_types = Counter(case["case_type"] for case in cases)
    error_rows = [row for row in results if not row["passed"]]
    cross_session_cases = [case for case in cases if case["case_type"] == "cross_session_isolation"]
    leak_count = sum(bool(row["leaked_topics"]) for row in results)

    summary: dict[str, Any] = {
        "phase": "6G-4_memory_eval",
        "case_count": len(cases),
        "turn_count": len(results),
        "case_type_distribution": dict(sorted(case_types.items())),
        "single_turn_count": case_types["single_turn_baseline"],
        "follow_up_turn_count": len(follow_up_results),
        "follow_up_detected_count": sum(
            row["memory_debug"]["is_follow_up"] for row in follow_up_results
        ),
        "follow_up_contextualization_eligible_count": len(eligible_context_results),
        "follow_up_contextualized_count": len(contextualized_results),
        "follow_up_context_hit_rate": round(
            len(context_hits) / len(eligible_context_results), 4
        )
        if eligible_context_results
        else 0.0,
        "cross_session_case_count": len(cross_session_cases),
        "cross_session_leak_count": leak_count,
        "memory_off_noop_count": sum(
            row["passed"] for row in results if row["case_type"] == "memory_off_noop"
        ),
        "missing_session_noop_count": sum(
            row["passed"] for row in results if row["case_type"] == "missing_session_noop"
        ),
        "no_context_noop_count": sum(
            row["passed"] for row in results if row["case_type"] == "no_context_follow_up"
        ),
        "source_summary_safe_count": sum(row["source_summary_safe"] is True for row in results),
        "memory_debug_present_count": sum(
            row["checks"]["memory_debug_complete"] for row in results
        ),
        "error_count": len(error_rows),
        "failed_case_ids": sorted({row["case_id"] for row in error_rows}),
        "calls_llm": False,
        "writes_chroma": False,
        "starts_service": False,
    }
    summary["acceptance_passed"] = bool(
        summary["error_count"] == 0
        and summary["cross_session_leak_count"] == 0
        and summary["follow_up_context_hit_rate"] >= 0.8
        and summary["memory_off_noop_count"] > 0
        and summary["missing_session_noop_count"] > 0
        and summary["no_context_noop_count"] > 0
        and summary["source_summary_safe_count"] > 0
        and summary["memory_debug_present_count"] > 0
        and not summary["calls_llm"]
        and not summary["writes_chroma"]
        and not summary["starts_service"]
    )
    summary["recommended_checkpoint"] = summary["acceptance_passed"]
    return summary


def main() -> None:
    args = _parse_args()
    cases = _read_jsonl(args.cases)
    results = [row for case in cases for row in _run_case(case)]
    summary = _build_summary(cases, results)
    _write_jsonl(args.results, results)
    _write_json(args.summary, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    if not summary["acceptance_passed"]:
        raise SystemExit("Phase 6G-4 memory evaluation did not meet the acceptance criteria")


if __name__ == "__main__":
    main()
