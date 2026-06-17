#!/usr/bin/env python3
"""Phase 6E-12: Bad Case Root Cause Audit + Evidence Coverage Diagnosis.

Best-effort analysis using available files (summaries, remaining_bad_cases,
chunk_manifest, calibrated taxonomy). No LLM, no service, no Chroma.

Output:
  phase6e12_bad_case_root_cause_results.jsonl
  phase6e12_bad_case_root_cause_summary.json
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
EVAL = ROOT / "data" / "knowledge_base" / "evaluation"
MANIFEST = ROOT / "data" / "knowledge_base" / "manifests"

REMAINING_CASES = EVAL / "phase6e_remaining_bad_cases.jsonl"
CHUNK_MANIFEST = MANIFEST / "chunk_manifest.jsonl"
CALIBRATED_TAXONOMY = EVAL / "phase6d9_deepseek_calibrated_bad_taxonomy.jsonl"
REGRESSION = EVAL / "phase6e11_policy_regression_analysis.json"

ROOT_CAUSES = [
    "corpus_missing_expected_source",
    "expected_source_exists_but_not_retrieved",
    "retrieved_expected_source_but_answer_failed",
    "retrieved_expected_source_but_keyword_failed",
    "metadata_field_missing_or_inconsistent",
    "chunk_too_noisy_or_too_broad",
    "chunk_too_small_or_context_missing",
    "query_type_misclassified",
    "evaluator_too_strict_or_misaligned",
    "needs_metadata_index",
    "needs_code_symbol_index",
    "needs_citation_verifier",
    "needs_query_decomposition",
    "needs_corpus_expansion",
    "unknown",
]

# ── Per-query-type default root cause mapping ──
QUERY_TYPE_ROOT_CAUSE_MAP: dict[str, list[str]] = {
    "exact_metadata_lookup": [
        "needs_metadata_index",
        "expected_source_exists_but_not_retrieved",
        "chunk_too_noisy_or_too_broad",
    ],
    "code_api_config": [
        "needs_code_symbol_index",
        "expected_source_exists_but_not_retrieved",
        "chunk_too_small_or_context_missing",
    ],
    "citation_required_query": [
        "needs_citation_verifier",
        "expected_source_exists_but_not_retrieved",
    ],
    "phase6c_bad_case_regression": [
        "expected_source_exists_but_not_retrieved",
        "needs_corpus_expansion",
        "query_type_misclassified",
    ],
    "ambiguous_query": [
        "evaluator_too_strict_or_misaligned",
        "needs_query_decomposition",
    ],
}


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def build_source_index(chunk_manifest: list[dict]) -> dict[str, dict[str, Any]]:
    """Build a map of source_id -> {exists, doc_types, chunk_count, languages, sample_chunk_id}."""
    index: dict[str, dict[str, Any]] = {}
    for c in chunk_manifest:
        sid = c.get("source_id", "")
        if not sid:
            continue
        if sid not in index:
            index[sid] = {
                "exists": True,
                "doc_types": set(),
                "chunk_count": 0,
                "languages": set(),
                "sample_chunk_id": c.get("chunk_id", ""),
                "sample_preview": c.get("content_preview") or c.get("text", "")[:200],
            }
        entry = index[sid]
        entry["doc_types"].add(c.get("doc_type", ""))
        entry["chunk_count"] += 1
        lang = c.get("language", "")
        if lang:
            entry["languages"].add(lang)
    # Convert sets to lists for JSON
    for v in index.values():
        v["doc_types"] = sorted(v["doc_types"])
        v["languages"] = sorted(v["languages"])
    return index


def load_summary_metrics() -> dict[str, dict[str, Any]]:
    """Load per-type metrics from all Phase 6E summaries."""
    metrics: dict[str, dict[str, Any]] = {}
    summaries = sorted(EVAL.glob("phase6e*_summary.json"))
    for sp in summaries:
        s = load_json(sp)
        if not s or "by_query_type" not in s:
            continue
        for qt, qm in s["by_query_type"].items():
            if not isinstance(qm, dict):
                continue
            if qt not in metrics:
                metrics[qt] = []
            metrics[qt].append({
                "source": sp.name,
                "source_hit_rate": qm.get("source_hit_rate"),
                "keyword_hit_rate": qm.get("keyword_hit_rate"),
                "bad_case_count_estimate": qm.get("case_count", 0) * (1 - qm.get("source_hit_rate", 0)),
            })
    return metrics


def main():
    missing: list[str] = []

    # ── Load inputs ──
    cases = load_jsonl(REMAINING_CASES)
    if not cases:
        missing.append("phase6e_remaining_bad_cases.jsonl")

    chunk_manifest = load_jsonl(CHUNK_MANIFEST)
    if not chunk_manifest:
        missing.append("chunk_manifest.jsonl")
    source_idx = build_source_index(chunk_manifest)

    taxonomy = load_jsonl(CALIBRATED_TAXONOMY)
    if not taxonomy:
        missing.append("phase6d9_deepseek_calibrated_bad_taxonomy.jsonl")
    tax_map: dict[str, dict] = {t["case_id"]: t for t in taxonomy}

    regression = load_json(REGRESSION)
    metrics = load_summary_metrics()

    # ── Analyze each case ──
    results: list[dict[str, Any]] = []
    type_dist = Counter()
    cause_dist = Counter()
    fixable_count = 0
    index_counts = Counter()

    for c in cases:
        cid = c.get("case_id", "?")
        qt = c.get("query_type", "unknown")
        esid = c.get("expected_source_id", "")
        etype = c.get("expected_doc_type", "")
        query = c.get("query", "")
        type_dist[qt] += 1

        # ── Check 1: Does expected_source_id exist in chunk_manifest? ──
        src_info = source_idx.get(esid)
        source_exists = src_info is not None if esid else None

        # ── Check 2: Reference calibrated taxonomy for failure type ──
        tax_entry = tax_map.get(cid, {})
        failure_type = tax_entry.get("failure_type", "")
        tax_source_hit = tax_entry.get("source_hit")
        tax_keyword_hit = tax_entry.get("keyword_hit")
        tax_retrieved_ids = tax_entry.get("returned_source_ids", [])[:5]

        # ── Check 3: Determine root causes ──
        root_causes: list[str] = []
        fix_dirs: list[str] = []
        policy_fixable = False
        needs_idx = {
            "requires_metadata_index": False,
            "requires_code_index": False,
            "requires_citation_verifier": False,
            "requires_corpus_expansion": False,
            "requires_evaluator_calibration": False,
            "requires_query_decomposition": False,
        }

        # 3a: Expected source doesn't exist
        if esid and source_exists is False:
            root_causes.append("corpus_missing_expected_source")
            fix_dirs.append("corpus_expansion")
            needs_idx["requires_corpus_expansion"] = True

        # 3b: Expected source exists but wasn't retrieved (per taxonomy)
        elif esid and source_exists and tax_source_hit is False:
            root_causes.append("expected_source_exists_but_not_retrieved")
            # Determine why based on query_type
            if qt == "exact_metadata_lookup":
                root_causes.append("needs_metadata_index")
                needs_idx["requires_metadata_index"] = True
            elif qt == "code_api_config":
                root_causes.append("needs_code_symbol_index")
                needs_idx["requires_code_index"] = True
            elif qt == "citation_required_query":
                root_causes.append("needs_citation_verifier")
                needs_idx["requires_citation_verifier"] = True
            elif qt in ("ambiguous_query", "multi_hop_lookup"):
                root_causes.append("needs_query_decomposition")
                needs_idx["requires_query_decomposition"] = True

        # 3c: Retrieved but keyword failed
        if tax_source_hit is True and tax_keyword_hit is False:
            root_causes.append("retrieved_expected_source_but_keyword_failed")
            root_causes.append("evaluator_too_strict_or_misaligned")
            needs_idx["requires_evaluator_calibration"] = True

        # 3d: Retrieved but answer failed (can't determine without results.jsonl)
        # Mark as unknown for missing data

        # 3e: Chunk issues for certain types
        if qt == "exact_metadata_lookup":
            root_causes.append("chunk_too_noisy_or_too_broad")
        if qt in ("code_api_config", "short_keyword"):
            root_causes.append("chunk_too_small_or_context_missing")

        # 3f: Evaluator issues
        if qt in ("ambiguous_query", "negative_banned_source"):
            root_causes.append("evaluator_too_strict_or_misaligned")
            needs_idx["requires_evaluator_calibration"] = True

        # 3g: Unknown if nothing matched
        if not root_causes:
            root_causes.append("unknown")

        # ── Determine fixability ──
        retrieval_fixable_causes = {
            "expected_source_exists_but_not_retrieved",
            "needs_metadata_index",
            "needs_code_symbol_index",
        }
        policy_fixable = any(rc in retrieval_fixable_causes for rc in root_causes)
        if policy_fixable:
            fixable_count += 1

        # ── Build result ──
        result = {
            "case_id": cid,
            "query": query[:200],
            "query_type": qt,
            "expected_source_id": esid or "",
            "expected_doc_type": etype,
            "baseline_status": "fail" if tax_source_hit is False else "unknown",
            "policy_status": "fail" if tax_source_hit is False else "unknown",
            "expected_source_exists": source_exists,
            "expected_source_retrieved": tax_source_hit,
            "source_hit": tax_source_hit,
            "keyword_hit": tax_keyword_hit,
            "answer_non_empty": True,
            "retrieved_source_ids": tax_retrieved_ids,
            "retrieved_doc_types": tax_entry.get("returned_doc_types", []) if tax_entry else [],
            "root_causes": root_causes,
            "fix_direction": fix_dirs,
            "retrieval_policy_fixable": policy_fixable,
            **needs_idx,
            "notes": f"failure_type={failure_type}" if failure_type else "no taxonomy data",
        }
        results.append(result)

        for rc in set(root_causes):
            cause_dist[rc] += 1
        for k, v in needs_idx.items():
            if v:
                index_counts[k] += 1

    # ── Build summary ──
    retrieval_gain = "low"
    if fixable_count >= 20:
        retrieval_gain = "medium"
    if fixable_count >= 40:
        retrieval_gain = "high"

    summary = {
        "phase": "6E-12_bad_case_root_cause_audit",
        "total_analyzed_cases": len(results),
        "missing_inputs": missing,
        "by_query_type": dict(type_dist),
        "by_root_cause": dict(cause_dist),
        "retrieval_fixable_count": fixable_count,
        "metadata_index_needed_count": index_counts.get("requires_metadata_index", 0),
        "code_index_needed_count": index_counts.get("requires_code_index", 0),
        "citation_verifier_needed_count": index_counts.get("requires_citation_verifier", 0),
        "corpus_expansion_needed_count": index_counts.get("requires_corpus_expansion", 0),
        "evaluator_calibration_needed_count": index_counts.get("requires_evaluator_calibration", 0),
        "query_decomposition_needed_count": index_counts.get("requires_query_decomposition", 0),
        "retrieval_policy_only_expected_gain": retrieval_gain,
        "recommended_next_phase": "6F_corpus_audit_or_structured_index",
        "analysis_limitations": [
            "No results.jsonl available — cannot determine per-case retrieval/answer details",
            "Best-effort using calibrated taxonomy + chunk manifest + summaries",
            "Source existence check via chunk_manifest (may miss sources without reviewed chunks)",
        ],
        "calls_llm": False,
        "writes_chroma": False,
        "starts_service": False,
        "source_coverage_summary": {
            sid: {
                "exists": info["exists"],
                "chunk_count": info["chunk_count"],
                "doc_types": info["doc_types"],
            }
            for sid, info in sorted(source_idx.items())
        } if source_idx else {},
    }

    # ── Write outputs ──
    out_results = EVAL / "phase6e12_bad_case_root_cause_results.jsonl"
    with out_results.open("w", encoding="utf-8", newline="\n") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")

    out_summary = EVAL / "phase6e12_bad_case_root_cause_summary.json"
    with out_summary.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    # ── Print report ──
    print(f"{'='*65}")
    print("Phase 6E-12: Bad Case Root Cause Audit")
    print(f"{'='*65}")
    print(f"  Total cases:          {len(results)}")
    print(f"  Missing inputs:       {missing or 'none'}")
    print(f"  Retrieval fixable:    {fixable_count} ({fixable_count/len(results)*100:.0f}%)")
    print(f"  Expected gain:        {retrieval_gain}")
    print(f"\n  By query_type:")
    for qt, c in type_dist.most_common():
        print(f"    {qt:35s}: {c:2d}")
    print(f"\n  By root_cause:")
    for rc, c in cause_dist.most_common():
        print(f"    {rc:45s}: {c:2d}")
    print(f"\n  Index needs:")
    for k, v in index_counts.most_common():
        print(f"    {k:45s}: {v:2d}")
    print(f"\n  Recommended: {summary['recommended_next_phase']}")
    print(f"  Output: {out_results}")
    print(f"  Output: {out_summary}")


if __name__ == "__main__":
    main()
