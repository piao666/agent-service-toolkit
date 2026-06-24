"""Prepare Phase 7E top-k/source coverage delta cases.

This script is intentionally offline-only. It reads existing Phase 7D/7D-3
evaluation artifacts, selects delta cases for future HPC top-k experiments,
and writes a compact case file plus an execution plan.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

EVAL_DIR = Path("data/knowledge_base/evaluation")
RESIDUAL_RESULTS = EVAL_DIR / "phase7d3_residual_delta_results.jsonl"
RESIDUAL_SUMMARY = EVAL_DIR / "phase7d3_residual_delta_summary.json"
PHASE7D3_RESULTS = EVAL_DIR / "phase7d3_planner_debug_only_deepseek_240_results.jsonl"
PHASE7D3_SUMMARY = EVAL_DIR / "phase7d3_planner_debug_only_deepseek_240_summary.json"
PHASE7D1_RESIDUAL_RESULTS = EVAL_DIR / "phase7d1_residual_delta_results.jsonl"
PHASE7D1_RESIDUAL_SUMMARY = EVAL_DIR / "phase7d1_residual_delta_summary.json"
EXPANDED_CASES = EVAL_DIR / "phase6d7_expanded_cases.jsonl"

OUT_CASES = EVAL_DIR / "phase7e_topk_delta_cases.jsonl"
OUT_PLAN = EVAL_DIR / "phase7e_topk_source_coverage_plan.json"


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def load_expanded_cases() -> dict[str, dict[str, Any]]:
    cases: dict[str, dict[str, Any]] = {}
    for row in read_jsonl(EXPANDED_CASES):
        case_id = str(row.get("case_id") or "")
        if case_id:
            cases[case_id] = row
    return cases


def result_is_bad(row: dict[str, Any]) -> bool:
    return bool(row.get("calibrated_bad_case", row.get("bad_case", False)))


def result_has_source_gap(row: dict[str, Any]) -> bool:
    return (not bool(row.get("source_hit"))) or (not bool(row.get("doc_type_hit")))


def derive_delta_from_phase7d3() -> tuple[str, dict[str, Any], list[dict[str, Any]]]:
    summary = read_json(PHASE7D3_SUMMARY)
    rows = read_jsonl(PHASE7D3_RESULTS)
    by_case: dict[str, dict[str, dict[str, Any]]] = {}
    for row in rows:
        case_id = str(row.get("case_id") or "")
        mode = str(row.get("mode") or "")
        if case_id and mode in {"legacy", "custom_graph"}:
            by_case.setdefault(case_id, {})[mode] = row

    legacy_bad = {
        case_id for case_id, modes in by_case.items() if result_is_bad(modes.get("legacy", {}))
    }
    custom_bad = {
        case_id
        for case_id, modes in by_case.items()
        if result_is_bad(modes.get("custom_graph", {}))
    }
    only_custom = sorted(custom_bad - legacy_bad)
    only_legacy = sorted(legacy_bad - custom_bad)
    shared = sorted(custom_bad & legacy_bad)

    residual_rows: list[dict[str, Any]] = []
    for case_id in only_custom:
        modes = by_case.get(case_id, {})
        residual_rows.append(build_delta_row(case_id, "only_custom_bad", modes))
    for case_id in only_legacy:
        modes = by_case.get(case_id, {})
        residual_rows.append(build_delta_row(case_id, "only_legacy_bad", modes))
    for case_id in shared:
        modes = by_case.get(case_id, {})
        custom = modes.get("custom_graph", {})
        legacy = modes.get("legacy", {})
        if result_has_source_gap(custom) or result_has_source_gap(legacy):
            residual_rows.append(build_delta_row(case_id, "shared_source_miss", modes))

    derived_summary = {
        "diagnostics_source": "phase7d3_derived_from_240_results",
        "legacy_bad_case_count": len(legacy_bad),
        "custom_graph_bad_case_count": len(custom_bad),
        "only_custom_bad_case_ids": only_custom,
        "only_legacy_bad_case_ids": only_legacy,
        "shared_bad_case_ids": shared,
        "source_summary_path": str(PHASE7D3_SUMMARY),
        "summary_phase": summary.get("phase"),
    }
    return "phase7d3_derived_from_240_results", derived_summary, residual_rows


def build_delta_row(
    case_id: str, delta_type: str, modes: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    legacy = modes.get("legacy", {})
    custom = modes.get("custom_graph", {})
    reference = custom or legacy
    return {
        "case_id": case_id,
        "delta_type": delta_type,
        "query": reference.get("query"),
        "query_type": reference.get("query_type"),
        "expected_source_id": reference.get("expected_source_id"),
        "expected_doc_type": reference.get("expected_doc_type"),
        "expected_keywords": reference.get("expected_keywords") or [],
        "legacy": summarize_mode_result(legacy),
        "custom_graph": summarize_mode_result(custom),
        "custom_graph_planner_debug": custom.get("planner_debug") or {},
        "custom_graph_judge_debug": custom.get("judge_debug") or {},
        "custom_graph_graph_debug": custom.get("graph_debug") or {},
    }


def summarize_mode_result(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "present": bool(row),
        "bad_case": bool(row.get("bad_case")),
        "calibrated_bad_case": bool(row.get("calibrated_bad_case", row.get("bad_case"))),
        "bad_case_reasons": row.get("bad_case_reasons") or [],
        "calibrated_bad_case_reasons": row.get("calibrated_bad_case_reasons") or [],
        "source_hit": bool(row.get("source_hit")),
        "doc_type_hit": bool(row.get("doc_type_hit")),
        "keyword_hit": bool(row.get("keyword_hit")),
        "answer_non_empty": bool(row.get("answer_non_empty")),
        "schema_valid": bool(row.get("schema_valid")),
        "error": row.get("error"),
        "timeout": bool(row.get("timeout")),
    }


def load_delta_rows() -> tuple[str, dict[str, Any], list[dict[str, Any]]]:
    if RESIDUAL_RESULTS.exists() and RESIDUAL_SUMMARY.exists():
        return "phase7d3_residual_delta", read_json(RESIDUAL_SUMMARY), read_jsonl(RESIDUAL_RESULTS)
    if PHASE7D3_RESULTS.exists() and PHASE7D3_SUMMARY.exists():
        return derive_delta_from_phase7d3()
    if PHASE7D1_RESIDUAL_RESULTS.exists() and PHASE7D1_RESIDUAL_SUMMARY.exists():
        return (
            "phase7d1_residual_delta_fallback",
            read_json(PHASE7D1_RESIDUAL_SUMMARY),
            read_jsonl(PHASE7D1_RESIDUAL_RESULTS),
        )
    raise FileNotFoundError("No Phase 7D residual or Phase 7D-3 result artifacts found.")


def make_case(row: dict[str, Any], expanded: dict[str, dict[str, Any]]) -> dict[str, Any]:
    case_id = str(row.get("case_id") or "")
    base = expanded.get(case_id, {})
    custom = row.get("custom_graph") or {}
    legacy = row.get("legacy") or {}
    custom_source_gap = (not custom.get("source_hit")) or (not custom.get("doc_type_hit"))
    legacy_source_gap = (not legacy.get("source_hit")) or (not legacy.get("doc_type_hit"))
    return {
        "case_id": case_id,
        "selection_source": row.get("delta_type"),
        "query": row.get("query") or base.get("query"),
        "query_type": row.get("query_type") or base.get("query_type"),
        "expected_source_id": row.get("expected_source_id") or base.get("expected_source_id"),
        "expected_doc_type": row.get("expected_doc_type") or base.get("expected_doc_type"),
        "expected_keywords": row.get("expected_keywords") or base.get("expected_keywords") or [],
        "top_k_values": [5, 8, 10],
        "fixed_modes": {
            "multi_hop": "off",
            "planner": "debug_only",
            "judge": "rule_based_fallback",
            "verifier": "rule_based",
        },
        "diagnostic_focus": {
            "custom_source_gap": bool(custom_source_gap),
            "legacy_source_gap": bool(legacy_source_gap),
            "custom_bad_case_reasons": custom.get("bad_case_reasons") or [],
            "legacy_bad_case_reasons": legacy.get("bad_case_reasons") or [],
        },
        "notes": "Use this case for future HPC top_k/source coverage comparison only.",
    }


def select_cases(rows: list[dict[str, Any]], limit: int = 20) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()

    for wanted in ("only_custom_bad", "only_legacy_bad"):
        for row in rows:
            case_id = str(row.get("case_id") or "")
            if row.get("delta_type") == wanted and case_id and case_id not in seen:
                selected.append(row)
                seen.add(case_id)

    for row in rows:
        if len(selected) >= limit:
            break
        case_id = str(row.get("case_id") or "")
        if row.get("delta_type") == "shared_source_miss" and case_id and case_id not in seen:
            selected.append(row)
            seen.add(case_id)

    return selected[:limit]


def main() -> None:
    source_name, source_summary, delta_rows = load_delta_rows()
    expanded = load_expanded_cases()
    selected_rows = select_cases(delta_rows, limit=20)
    case_rows = [make_case(row, expanded) for row in selected_rows]

    distribution = Counter(row["selection_source"] for row in case_rows)
    plan = {
        "phase": "7E-1_topk_source_coverage_preparation",
        "diagnostics_source": source_name,
        "input_summary": source_summary,
        "case_count": len(case_rows),
        "case_source_distribution": dict(sorted(distribution.items())),
        "top_k_values": [5, 8, 10],
        "fixed_variables": {
            "multi_hop": "off",
            "planner": "debug_only",
            "judge": "rule_based_fallback",
            "verifier": "rule_based",
        },
        "control_variable": "top_k/source coverage",
        "outputs": {
            "cases": str(OUT_CASES),
            "plan": str(OUT_PLAN),
        },
        "calls_llm": False,
        "runs_240_case": False,
        "writes_chroma": False,
        "recommended_next_step": (
            "Run these delta cases on HPC with top_k=5/8/10 before considering a full 240-case rerun."
        ),
    }

    write_jsonl(OUT_CASES, case_rows)
    write_json(OUT_PLAN, plan)

    print(json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
