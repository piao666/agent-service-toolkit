from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from rag.evidence_verifier import verify_answer_grounding  # noqa: E402

CASES_PATH = REPO_ROOT / "data/knowledge_base/evaluation/phase6i_evidence_cases.jsonl"
RESULTS_PATH = REPO_ROOT / "data/knowledge_base/evaluation/phase6i_evidence_eval_results.jsonl"
SUMMARY_PATH = REPO_ROOT / "data/knowledge_base/evaluation/phase6i_evidence_eval_summary.json"
REQUIRED_DEBUG_FIELDS = {
    "verifier_mode",
    "grounding_status",
    "grounding_score",
    "answer_has_sources",
    "citation_coverage",
    "important_terms",
    "matched_terms",
    "unsupported_terms",
    "source_count",
    "safe_fallback_triggered",
    "calls_llm",
    "writes_chroma",
}


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def main() -> int:
    cases = _read_jsonl(CASES_PATH)
    results: list[dict[str, Any]] = []
    error_count = 0
    for case in cases:
        errors: list[str] = []
        try:
            result = verify_answer_grounding(
                query=str(case.get("query") or ""),
                answer=str(case.get("answer") or ""),
                sources=list(case.get("sources") or []),
                query_type=case.get("query_type"),
                mode="rule_based",
                safe_fallback_enabled=bool(case.get("safe_fallback_enabled", False)),
            )
            debug = result.as_debug()
            if result.grounding_status != case.get("expected_grounding_status"):
                errors.append("grounding_status_mismatch")
            if result.citation_coverage is not case.get("expected_citation_coverage"):
                errors.append("citation_coverage_mismatch")
            if result.safe_fallback_triggered is not case.get("expected_safe_fallback"):
                errors.append("safe_fallback_mismatch")
            if not REQUIRED_DEBUG_FIELDS.issubset(debug):
                errors.append("verifier_debug_incomplete")
        except Exception as exc:
            debug = {}
            errors.append(f"runtime_error:{type(exc).__name__}")
            error_count += 1

        results.append(
            {
                "case_id": case.get("case_id"),
                "case_type": case.get("case_type"),
                "query_type": case.get("query_type"),
                "expected_grounding_status": case.get("expected_grounding_status"),
                "expected_citation_coverage": case.get("expected_citation_coverage"),
                "passed": not errors,
                "errors": errors,
                "verifier_debug": debug,
            }
        )

    statuses = Counter(row["verifier_debug"].get("grounding_status") for row in results)
    citation_cases = [row for row in results if row["case_type"] == "citation_required_query"]
    unsupported_cases = [row for row in results if row["case_type"] == "unsupported_answer"]
    status_match_count = sum(
        row["verifier_debug"].get("grounding_status") == row["expected_grounding_status"]
        for row in results
    )
    summary = {
        "phase": "6I_evidence_grounding_eval",
        "case_count": len(results),
        "high_count": statuses["high"],
        "medium_count": statuses["medium"],
        "low_count": statuses["low"],
        "expected_status_match_count": status_match_count,
        "expected_status_match_rate": round(status_match_count / len(results), 4)
        if results
        else 0.0,
        "citation_required_case_count": len(citation_cases),
        "citation_required_checked_count": sum(
            row["verifier_debug"].get("verifier_mode") == "rule_based"
            for row in citation_cases
        ),
        "unsupported_answer_case_count": len(unsupported_cases),
        "unsupported_answer_detected_count": sum(
            row["verifier_debug"].get("grounding_status") == "low"
            for row in unsupported_cases
        ),
        "empty_sources_low_confidence_count": sum(
            row["verifier_debug"].get("source_count") == 0
            and row["verifier_debug"].get("grounding_status") == "low"
            for row in results
        ),
        "verifier_debug_present_count": sum(
            REQUIRED_DEBUG_FIELDS.issubset(row["verifier_debug"]) for row in results
        ),
        "safe_fallback_triggered_count": sum(
            bool(row["verifier_debug"].get("safe_fallback_triggered")) for row in results
        ),
        "failed_case_ids": [row["case_id"] for row in results if not row["passed"]],
        "error_count": error_count,
        "calls_llm": False,
        "writes_chroma": False,
        "starts_service": False,
    }
    summary["acceptance_passed"] = bool(
        summary["case_count"] >= 24
        and summary["error_count"] == 0
        and summary["expected_status_match_rate"] >= 0.85
        and summary["citation_required_checked_count"]
        == summary["citation_required_case_count"]
        and summary["unsupported_answer_detected_count"]
        == summary["unsupported_answer_case_count"]
        and summary["empty_sources_low_confidence_count"] > 0
        and summary["verifier_debug_present_count"] == summary["case_count"]
    )
    summary["recommended_checkpoint"] = summary["acceptance_passed"]
    _write_jsonl(RESULTS_PATH, results)
    _write_json(SUMMARY_PATH, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if summary["acceptance_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
