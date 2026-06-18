#!/usr/bin/env python3
"""Phase 6F-9A: Analyze remaining 49 bad cases from Phase 6F-8 structured materialization 240 eval."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
EVAL = ROOT / "data" / "knowledge_base" / "evaluation"

SRC = EVAL / "phase6f8_deepseek_structured_materialization_240_results.jsonl"
SUMMARY = EVAL / "phase6f8_deepseek_structured_materialization_240_summary.json"
OUT_JSON = EVAL / "phase6f9_remaining_bad_case_analysis.json"
OUT_JSONL = EVAL / "phase6f9_remaining_bad_cases.jsonl"


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def is_bad(r: dict) -> bool:
    return not (r.get("source_hit") and r.get("keyword_hit") and r.get("doc_type_hit"))


def classify(r: dict) -> dict[str, Any]:
    qt = r.get("query_type", "unknown")
    reasons = []
    if not r.get("source_hit"):
        reasons.append("source_miss")
    if not r.get("keyword_hit"):
        reasons.append("keyword_miss")
    if not r.get("doc_type_hit"):
        reasons.append("doc_type_miss")
    if not r.get("answer_non_empty"):
        reasons.append("answer_empty")

    # Root cause guesses
    needs = []
    if qt == "exact_metadata_lookup":
        needs.append("metadata_ranker")
    if qt == "code_api_config":
        needs.append("symbol_ranker")
    if qt == "citation_required_query":
        needs.append("citation_verifier")
    if qt == "phase6c_bad_case_regression":
        needs.append("evidence_cleaner")

    return {
        "case_id": r.get("case_id", ""),
        "query": r.get("query", "")[:200],
        "query_type": qt,
        "expected_source_id": r.get("expected_source_id", ""),
        "source_hit": r.get("source_hit"),
        "keyword_hit": r.get("keyword_hit"),
        "doc_type_hit": r.get("doc_type_hit"),
        "answer_non_empty": r.get("answer_non_empty"),
        "returned_source_ids": r.get("returned_source_ids", [])[:5],
        "reasons": reasons,
        "suggested_refinements": needs,
    }


def main():
    results = load_jsonl(SRC)
    summary = json.loads(SUMMARY.read_text(encoding="utf-8"))
    bad = [r for r in results if is_bad(r)]

    print(f"Total cases: {len(results)}, Bad: {len(bad)}")

    # Per-type distribution
    type_dist = Counter()
    reason_dist = Counter()
    refinement_counts = Counter()
    for r in bad:
        entry = classify(r)
        type_dist[entry["query_type"]] += 1
        for reason in entry["reasons"]:
            reason_dist[reason] += 1
        for ref in entry["suggested_refinements"]:
            refinement_counts[ref] += 1

    # Write outputs
    bad_entries = [classify(r) for r in bad]
    with OUT_JSONL.open("w", encoding="utf-8", newline="\n") as f:
        for e in bad_entries:
            f.write(json.dumps(e, ensure_ascii=False, sort_keys=True) + "\n")

    analysis = {
        "phase": "6F-9_remaining_bad_case_analysis",
        "total_bad_cases": len(bad),
        "by_query_type": dict(type_dist),
        "by_reason": dict(reason_dist),
        "by_refinement": dict(refinement_counts),
        "source_miss_count": reason_dist.get("source_miss", 0),
        "keyword_miss_count": reason_dist.get("keyword_miss", 0),
        "doc_type_miss_count": reason_dist.get("doc_type_miss", 0),
        "metadata_ranker_needed_count": refinement_counts.get("metadata_ranker", 0),
        "symbol_ranker_needed_count": refinement_counts.get("symbol_ranker", 0),
        "evidence_cleaner_needed_count": refinement_counts.get("evidence_cleaner", 0),
        "citation_verifier_needed_count": refinement_counts.get("citation_verifier", 0),
        "likely_retrieval_fixable_count": type_dist.get("exact_metadata_lookup", 0) + type_dist.get("code_api_config", 0),
        "likely_generation_or_evaluator_count": len(bad) - (type_dist.get("exact_metadata_lookup", 0) + type_dist.get("code_api_config", 0)),
        "recommended_refinements": ["metadata_exact_ranker", "symbol_exact_ranker", "evidence_cleaner", "citation_verifier"],
    }
    with OUT_JSON.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(analysis, f, ensure_ascii=False, indent=2)

    # Print
    print(f"\n=== Remaining {len(bad)} Bad Cases ===")
    print(f"By type:")
    for t, c in type_dist.most_common():
        print(f"  {t:35s}: {c:2d}")
    print(f"By reason:")
    for r, c in reason_dist.most_common():
        print(f"  {r:20s}: {c:2d}")
    print(f"\nRetrieval fixable: ~{analysis['likely_retrieval_fixable_count']}")
    print(f"Gen/eval issues: ~{analysis['likely_generation_or_evaluator_count']}")
    print(f"Refinements: {analysis['recommended_refinements']}")


if __name__ == "__main__":
    main()
