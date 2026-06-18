#!/usr/bin/env python3
"""Phase 6F-10: Failure Boundary Analysis / Case Delta Matrix.

Per-case delta: baseline-240 vs 6F-8 vs 6F-9.
No LLM, no service, no Chroma, no code changes.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
EVAL = ROOT / "data" / "knowledge_base" / "evaluation"

# ── Input paths ──
BL240 = EVAL / "phase6f8_deepseek_baseline_240_results.jsonl"
F8240 = EVAL / "phase6f8_deepseek_structured_materialization_240_results.jsonl"
F9240 = EVAL / "phase6f9_deepseek_refined_structured_240_results.jsonl"
CASES = EVAL / "phase6d7_expanded_cases.jsonl"

# ── Output paths ──
OUT_DELTA = EVAL / "phase6f10_case_delta_matrix.jsonl"
OUT_FAILURE = EVAL / "phase6f10_failure_boundary_summary.json"
OUT_ACTIONS = EVAL / "phase6f10_actionable_next_steps.json"


def load_jsonl(p: Path) -> list[dict]:
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text("utf-8").splitlines() if line.strip()]


def is_bad_ev(r: dict) -> bool:
    """Calibrated bad-case check: source_hit OR keyword_hit missing (Phase 6D-9 rules)."""
    return not (r.get("source_hit") and r.get("keyword_hit"))


def failure_layer(r: dict) -> list[str]:
    layers = []
    if not r.get("source_hit"):
        layers.append("retrieval_source_miss")
    if not r.get("doc_type_hit"):
        layers.append("retrieval_doc_type_miss")
    if not r.get("keyword_hit"):
        layers.append("retrieval_keyword_miss")
    if r.get("source_hit") and not r.get("keyword_hit"):
        layers.append("source_hit_but_keyword_failed")
    if r.get("source_hit") and not r.get("citation_present"):
        layers.append("source_hit_but_citation_failed")
    if not r.get("answer_non_empty"):
        layers.append("answer_generation_failed")
    qt = r.get("query_type", "")
    if qt == "ambiguous_query":
        layers.append("evaluator_too_strict_or_misaligned")
    if qt == "exact_metadata_lookup":
        layers.append("metadata_index_insufficient")
    if qt == "code_api_config":
        layers.append("code_symbol_index_insufficient")
    if qt == "citation_required_query":
        layers.append("citation_verifier_needed")
    if qt == "multi_hop_lookup":
        layers.append("multi_hop_query_decomposition_needed")
    return layers or ["unknown"]


def per_case_needs(r: dict, layers: list[str]) -> dict[str, bool]:
    return {
        "retrieval_still_fixable": "retrieval_source_miss" in layers and r.get("query_type", "") in ("exact_metadata_lookup", "code_api_config"),
        "generation_or_evaluator_likely": any(l in layers for l in ("source_hit_but_keyword_failed", "answer_generation_failed", "evaluator_too_strict_or_misaligned")),
        "citation_verifier_needed": "citation_required_query" == r.get("query_type", ""),
        "code_index_needed": "code_api_config" == r.get("query_type", ""),
        "metadata_index_needed": "exact_metadata_lookup" == r.get("query_type", ""),
        "chunk_cleanup_needed": False,
        "query_decomposition_needed": "multi_hop_lookup" == r.get("query_type", ""),
        "evaluator_calibration_needed": r.get("query_type", "") in ("ambiguous_query", "negative_banned_source"),
    }


def main():
    missing = []
    for name, p in [("baseline_240", BL240), ("6F-8_240", F8240), ("6F-9_240", F9240), ("cases", CASES)]:
        if not p.exists():
            missing.append(name)

    bl = {r["case_id"]: r for r in load_jsonl(BL240)}
    f8 = {r["case_id"]: r for r in load_jsonl(F8240)}
    f9 = {r["case_id"]: r for r in load_jsonl(F9240)}
    cases = load_jsonl(CASES)

    rows = []
    delta_cats = Counter()
    layer_dist = Counter()
    type_dist = Counter()
    needs_dist = Counter()
    fixed = regressed_f8 = fixed_f9 = regressed_f9 = 0
    f8_remaining = 0

    for c in cases:
        cid = c["case_id"]
        bl_r, f8_r, f9_r = bl.get(cid), f8.get(cid), f9.get(cid)

        bl_ok = not is_bad_ev(bl_r) if bl_r else None
        f8_ok = not is_bad_ev(f8_r) if f8_r else None
        f9_ok = not is_bad_ev(f9_r) if f9_r else None

        # Delta category
        dcats = []
        if bl_ok is False and f8_ok is True:
            dcats.append("baseline_fail_6f8_pass")
            fixed += 1
        elif bl_ok is True and f8_ok is False:
            dcats.append("baseline_pass_6f8_fail")
            regressed_f8 += 1
        elif bl_ok is False and f8_ok is False:
            dcats.append("baseline_fail_6f8_fail")
            f8_remaining += 1
        elif bl_ok is True and f8_ok is True:
            dcats.append("baseline_pass_6f8_pass")

        if f8_ok is False and f9_ok is True:
            dcats.append("sixf8_fail_6f9_pass")
            fixed_f9 += 1
        elif f8_ok is True and f9_ok is False:
            dcats.append("sixf8_pass_6f9_fail")
            regressed_f9 += 1
        elif f8_ok is False and f9_ok is False:
            dcats.append("sixf8_fail_6f9_fail")
        elif f8_ok is True and f9_ok is True:
            dcats.append("sixf8_pass_6f9_pass")

        for dc in dcats:
            delta_cats[dc] += 1

        # Failure layers for remaining bad (6F-8)
        f8_ref = f8_r or {}
        layers = failure_layer(f8_ref) if f8_ok is False else []
        needs = per_case_needs(f8_ref, layers) if layers else {}

        if f8_ok is False:
            type_dist[c.get("query_type", "?")] += 1
            for l in layers:
                layer_dist[l] += 1
            for k, v in needs.items():
                if v:
                    needs_dist[k] += 1

        rows.append({
            "case_id": cid,
            "query": c.get("query", "")[:200],
            "query_type": c.get("query_type", ""),
            "expected_source_id": c.get("expected_source_id", ""),
            "expected_doc_type": c.get("expected_doc_type", ""),
            "baseline_status": "pass" if bl_ok else ("fail" if bl_ok is False else "unknown"),
            "phase6f8_status": "pass" if f8_ok else ("fail" if f8_ok is False else "unknown"),
            "phase6f9_status": "pass" if f9_ok else ("fail" if f9_ok is False else "unknown"),
            "delta_category": dcats,
            "baseline_source_hit": bl_r.get("source_hit") if bl_r else None,
            "phase6f8_source_hit": f8_r.get("source_hit") if f8_r else None,
            "phase6f9_source_hit": f9_r.get("source_hit") if f9_r else None,
            "baseline_keyword_hit": bl_r.get("keyword_hit") if bl_r else None,
            "phase6f8_keyword_hit": f8_r.get("keyword_hit") if f8_r else None,
            "phase6f9_keyword_hit": f9_r.get("keyword_hit") if f9_r else None,
            "phase6f8_retrieved_source_ids": f8_r.get("returned_source_ids", [])[:5] if f8_r else [],
            "phase6f9_retrieved_source_ids": f9_r.get("returned_source_ids", [])[:5] if f9_r else [],
            "expected_source_in_phase6f8_sources": c.get("expected_source_id", "") in (f8_r.get("returned_source_ids", []) if f8_r else []),
            "expected_source_in_phase6f9_sources": c.get("expected_source_id", "") in (f9_r.get("returned_source_ids", []) if f9_r else []),
            "likely_failure_layer": layers,
            "recommended_fix_type": ["retrieval"] if needs.get("metadata_index_needed") or needs.get("code_index_needed") else (["generation_or_evaluator"] if needs.get("generation_or_evaluator_likely") else []),
            **needs,
            "notes": "",
        })

    # ── Write delta matrix ──
    with OUT_DELTA.open("w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")

    # ── Failure summary ──
    fsum = {
        "phase": "6F-10_failure_boundary_analysis",
        "missing_inputs": missing,
        "total_cases": len(rows),
        "baseline_bad_case_count": sum(1 for r in rows if r["baseline_status"] == "fail"),
        "phase6f8_bad_case_count": sum(1 for r in rows if r["phase6f8_status"] == "fail"),
        "phase6f9_bad_case_count": sum(1 for r in rows if r["phase6f9_status"] == "fail"),
        "phase6f8_fixed_count": fixed,
        "phase6f8_regressed_count": regressed_f8,
        "phase6f9_fixed_over_6f8_count": fixed_f9,
        "phase6f9_regressed_over_6f8_count": regressed_f9,
        "phase6f8_remaining_bad_count": f8_remaining,
        "by_delta_category": dict(delta_cats),
        "by_query_type_remaining_bad": dict(type_dist),
        "by_failure_layer": dict(layer_dist),
        "retrieval_still_fixable_count": needs_dist.get("retrieval_still_fixable", 0),
        "generation_or_evaluator_likely_count": needs_dist.get("generation_or_evaluator_likely", 0),
        "metadata_index_needed_count": needs_dist.get("metadata_index_needed", 0),
        "code_index_needed_count": needs_dist.get("code_index_needed", 0),
        "citation_verifier_needed_count": needs_dist.get("citation_verifier_needed", 0),
        "chunk_cleanup_needed_count": needs_dist.get("chunk_cleanup_needed", 0),
        "query_decomposition_needed_count": needs_dist.get("query_decomposition_needed", 0),
        "evaluator_calibration_needed_count": needs_dist.get("evaluator_calibration_needed", 0),
        "recommended_best_version": "phase6f8_structured_materialization",
        "should_continue_retrieval_refinement": False,
        "recommended_next_work": ["phase6f_final_closure"],
        "calls_llm": False,
        "writes_chroma": False,
        "starts_service": False,
    }
    with OUT_FAILURE.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(fsum, f, ensure_ascii=False, indent=2)

    # ── Actionable steps ──
    actions = {
        "recommended_best_version": "phase6f8_structured_materialization",
        "do_not_adopt_phase6f9": True,
        "next_priority": ["phase6f_final_closure"],
        "recommended_phase6f_final_closure": True,
        "recommended_next_phase": "phase6G_evidence_grounding_or_evaluator_calibration",
        "top_actions": [
            {"action": "keep_phase6f8_as_best_version", "reason": "6F-8 has best 240 bad=49, 6F-9 regressed to 50", "expected_impact": "high", "risk": "low", "depends_on": []},
        ],
    }
    if fixed_f9 > 0:
        actions["top_actions"].append({"action": "apply_6f9_fixes_to_6f8", "reason": f"6F-9 fixed {fixed_f9} cases over 6F-8", "expected_impact": "low", "risk": "medium"})
    if needs_dist.get("citation_verifier_needed", 0) >= 3:
        actions["top_actions"].append({"action": "build_citation_verifier", "reason": f"{needs_dist['citation_verifier_needed']} cases need citation verification", "expected_impact": "medium", "risk": "low"})
    if needs_dist.get("evaluator_calibration_needed", 0) >= 5:
        actions["top_actions"].append({"action": "evaluator_calibration", "reason": f"{needs_dist['evaluator_calibration_needed']} cases may have overly strict evaluation", "expected_impact": "medium", "risk": "low"})

    with OUT_ACTIONS.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(actions, f, ensure_ascii=False, indent=2)

    # ── Print ──
    print(f"cases={len(rows)}, bl_bad={fsum['baseline_bad_case_count']}, f8_bad={fsum['phase6f8_bad_case_count']}, f9_bad={fsum['phase6f9_bad_case_count']}")
    print(f"6F-8: fixed={fixed}, regressed={regressed_f8}, remaining={f8_remaining}")
    print(f"6F-9: fixed_over_6F-8={fixed_f9}, regressed_over_6F-8={regressed_f9}")
    print(f"Delta categories: {dict(delta_cats.most_common())}")
    print(f"Remaining by type: {dict(type_dist.most_common(8))}")
    print(f"Failure layers: {dict(layer_dist.most_common(8))}")
    print(f"Retrieval fixable: {needs_dist.get('retrieval_still_fixable', 0)}")
    print(f"Gen/eval likely: {needs_dist.get('generation_or_evaluator_likely', 0)}")
    print(f"recommended_best_version: {fsum['recommended_best_version']}")
    print(f"should_continue_retrieval_refinement: {fsum['should_continue_retrieval_refinement']}")


if __name__ == "__main__":
    main()
