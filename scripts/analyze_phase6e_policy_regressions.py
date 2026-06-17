#!/usr/bin/env python3
"""Phase 6E-11: Policy Regression Analysis.

读取 Phase 6E-6/6E-8/6E-10 baseline vs policy summary，按 query_type 分解
improvement / degradation，输出结论性 JSON。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
EVAL = ROOT / "data" / "knowledge_base" / "evaluation"

PHASES = {
    "6E-6_global": {
        "baseline_59": "phase6e6_deepseek_baseline_59_summary.json",
        "policy_59": "phase6e6_deepseek_policy_59_summary.json",
        "baseline_240": "phase6e6_deepseek_baseline_240_summary.json",
        "policy_240": "phase6e6_deepseek_policy_240_summary.json",
        "label": "Phase 6E-6 global query_type_aware",
    },
    "6E-8_gated": {
        "baseline_59": "phase6e8_deepseek_baseline_59_summary.json",
        "policy_59": "phase6e8_deepseek_gated_59_summary.json",
        "baseline_240": "phase6e8_deepseek_baseline_240_summary.json",
        "policy_240": "phase6e8_deepseek_gated_240_summary.json",
        "label": "Phase 6E-8 gated query_type_aware",
    },
    "6E-10_conservative": {
        "baseline_59": "phase6e10_deepseek_baseline_59_summary.json",
        "policy_59": "phase6e10_deepseek_conservative_59_summary.json",
        "baseline_240": "phase6e10_deepseek_baseline_240_summary.json",
        "policy_240": "phase6e10_deepseek_conservative_240_summary.json",
        "label": "Phase 6E-10 conservative gate",
    },
}

TARGET_OVERLAY_TYPES = {"exact_metadata_lookup", "code_api_config", "short_keyword", "citation_required_query"}
NOOP_TYPES = {"zh_knowledge", "en_api_doc", "mixed_zh_en_api", "agent_rag_concept",
              "ambiguous_query", "multi_hop_lookup", "negative_banned_source"}


def load_summary(name: str) -> dict[str, Any] | None:
    path = EVAL / name
    if not path.exists():
        return None
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def per_type_delta(baseline: dict, policy: dict) -> dict[str, dict[str, Any]]:
    """计算 per-query-type 的 source_hit 和 bad_case delta。"""
    bq = baseline.get("by_query_type", {})
    pq = policy.get("by_query_type", {})
    result = {}
    for qt in sorted(set(list(bq) + list(pq))):
        bsrc = bq.get(qt, {}).get("source_hit_rate", 0)
        psrc = pq.get(qt, {}).get("source_hit_rate", 0)
        result[qt] = {
            "baseline_source_hit": bsrc,
            "policy_source_hit": psrc,
            "source_hit_delta": round(psrc - bsrc, 4),
            "direction": "improve" if psrc > bsrc else ("degrade" if psrc < bsrc else "stable"),
        }
    return result


def main():
    analysis: dict[str, Any] = {
        "phase": "6E-11",
        "target_overlay_types": sorted(TARGET_OVERLAY_TYPES),
        "noop_types": sorted(NOOP_TYPES),
        "phases": {},
        "overall": {
            "consistent_improvers": [],
            "consistent_degraders": [],
            "root_cause": (
                "sparse_first_bm25 policy 替换 baseline dense，导致 mixed_zh_en_api 类型崩溃 "
                "(source_hit 0.85→0.15)，同时 code_api_config 和 citation_required_query 也未受益。"
                "6E-10 conservative gate 过于保守，丢失了 59-case 改善，同时未能阻止 240-case 退化。"
            ),
        },
    }

    consistent_deltas: dict[str, list[float]] = {}

    for phase_key, phase_info in PHASES.items():
        b59 = load_summary(phase_info["baseline_59"])
        p59 = load_summary(phase_info["policy_59"])
        b240 = load_summary(phase_info["baseline_240"])
        p240 = load_summary(phase_info["policy_240"])

        if not all([b59, p59, b240, p240]):
            analysis["phases"][phase_key] = {"error": "missing files"}
            continue

        delta_240 = per_type_delta(b240, p240)

        for qt, d in delta_240.items():
            if qt not in consistent_deltas:
                consistent_deltas[qt] = []
            consistent_deltas[qt].append(d["source_hit_delta"])

        analysis["phases"][phase_key] = {
            "label": phase_info["label"],
            "59_baseline_bad": b59.get("bad_case_count"),
            "59_policy_bad": p59.get("bad_case_count"),
            "59_bad_delta": (p59.get("bad_case_count", 0) - b59.get("bad_case_count", 0)),
            "240_baseline_bad": b240.get("bad_case_count"),
            "240_policy_bad": p240.get("bad_case_count"),
            "240_bad_delta": (p240.get("bad_case_count", 0) - b240.get("bad_case_count", 0)),
            "240_source_hit_delta": round(p240.get("source_hit_rate", 0) - b240.get("source_hit_rate", 0), 4),
            "per_type_240": delta_240,
        }

    # ── consistent improvers / degraders ──
    for qt, deltas in consistent_deltas.items():
        if all(d > 0 for d in deltas):
            analysis["overall"]["consistent_improvers"].append(qt)
        elif all(d < 0 for d in deltas):
            analysis["overall"]["consistent_degraders"].append(qt)

    # ── write ──
    out_json = EVAL / "phase6e11_policy_regression_analysis.json"
    with out_json.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(analysis, f, ensure_ascii=False, indent=2)

    # ── print summary ──
    print(f"{'='*70}")
    print("Phase 6E-11 Policy Regression Analysis")
    print(f"{'='*70}")
    print(f"Consistent improvers: {analysis['overall']['consistent_improvers']}")
    print(f"Consistent degraders:  {analysis['overall']['consistent_degraders']}")
    print()
    for pk, pi in analysis["phases"].items():
        if "error" in pi:
            continue
        print(f"{pi['label']}:")
        print(f"  59:  {pi['59_baseline_bad']} → {pi['59_policy_bad']} ({pi['59_bad_delta']:+d})")
        print(f"  240: {pi['240_baseline_bad']} → {pi['240_policy_bad']} ({pi['240_bad_delta']:+d})")
        for qt, d in sorted(pi["per_type_240"].items()):
            if abs(d["source_hit_delta"]) >= 0.05:
                flag = "DEG" if d["direction"] == "degrade" else "IMP"
                print(f"    {flag} {qt}: {d['source_hit_delta']:+.4f}")
    print(f"\nRoot cause: {analysis['overall']['root_cause'][:120]}...")
    print(f"Output: {out_json}")


if __name__ == "__main__":
    main()
