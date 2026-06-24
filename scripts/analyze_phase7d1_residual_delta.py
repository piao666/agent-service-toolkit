"""Analyze Phase 7D-1 residual deltas without calling endpoints."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

EVAL_DIR = Path("data/knowledge_base/evaluation")
RESULTS_PATH = EVAL_DIR / "phase7d1_multihop_off_deepseek_240_results.jsonl"
SUMMARY_PATH = EVAL_DIR / "phase7d1_multihop_off_deepseek_240_summary.json"
OUT_RESULTS_PATH = EVAL_DIR / "phase7d1_residual_delta_results.jsonl"
OUT_SUMMARY_PATH = EVAL_DIR / "phase7d1_residual_delta_summary.json"
DOC_PATH = Path("docs/enterprise_rag_backend/PHASE7D1_RESIDUAL_DELTA_DIAGNOSIS.md")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        rows.append(json.loads(line))
    return rows


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def as_bool(value: Any) -> bool:
    return bool(value) if value is not None else False


def compact_row(row: dict[str, Any] | None) -> dict[str, Any]:
    if not row:
        return {
            "present": False,
            "bad_case": None,
            "bad_case_reasons": [],
            "source_hit": None,
            "doc_type_hit": None,
            "keyword_hit": None,
            "answer_non_empty": None,
            "schema_valid": None,
            "error": None,
            "timeout": None,
        }

    return {
        "present": True,
        "bad_case": row.get("bad_case"),
        "calibrated_bad_case": row.get("calibrated_bad_case"),
        "bad_case_reasons": row.get("bad_case_reasons") or [],
        "calibrated_bad_case_reasons": row.get("calibrated_bad_case_reasons") or [],
        "source_hit": row.get("source_hit"),
        "doc_type_hit": row.get("doc_type_hit"),
        "keyword_hit": row.get("keyword_hit"),
        "answer_non_empty": row.get("answer_non_empty"),
        "schema_valid": row.get("schema_valid"),
        "source_count": row.get("source_count"),
        "latency_ms": row.get("latency_ms"),
        "error": row.get("error"),
        "timeout": row.get("timeout"),
    }


def classify_custom_root_causes(
    legacy: dict[str, Any] | None,
    custom: dict[str, Any] | None,
) -> list[str]:
    if not custom:
        return ["custom_result_missing"]

    causes: list[str] = []
    if not as_bool(custom.get("source_hit")):
        causes.append("source_miss")
    if not as_bool(custom.get("doc_type_hit")):
        causes.append("doc_type_miss")
    if not as_bool(custom.get("keyword_hit")):
        causes.append("keyword_miss")
    if not as_bool(custom.get("answer_non_empty")):
        causes.append("answer_non_empty")
    if custom.get("error") or custom.get("timeout") or not as_bool(custom.get("schema_valid")):
        causes.append("schema_error")

    planner_debug = custom.get("planner_debug") or {}
    if planner_debug.get("multi_hop_disabled_by_config") or planner_debug.get("planner_type") in {
        "complex",
        "multi_hop",
        "ambiguous",
    }:
        causes.append("planner_side_effect")

    judge_debug = custom.get("judge_debug") or {}
    judge_verdict = custom.get("judge_verdict") or judge_debug.get("verdict")
    if judge_verdict and judge_verdict not in {"pass", "none"}:
        causes.append("judge_side_effect")

    if legacy:
        same_hits = (
            legacy.get("source_hit") == custom.get("source_hit")
            and legacy.get("doc_type_hit") == custom.get("doc_type_hit")
            and legacy.get("keyword_hit") == custom.get("keyword_hit")
        )
        if same_hits:
            causes.append("retrieval_order_diff")

    return sorted(set(causes)) or ["unclassified_delta"]


def build_case_index(rows: list[dict[str, Any]]) -> dict[str, dict[str, dict[str, Any]]]:
    indexed: dict[str, dict[str, dict[str, Any]]] = {}
    for row in rows:
        case_id = str(row.get("case_id") or "")
        mode = str(row.get("mode") or "")
        if not case_id or mode not in {"legacy", "custom_graph"}:
            continue
        indexed.setdefault(case_id, {})[mode] = row
    return indexed


def build_delta_result(
    case_id: str,
    delta_type: str,
    pair: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    legacy = pair.get("legacy")
    custom = pair.get("custom_graph")
    reference = custom or legacy or {}
    custom_root_causes = (
        classify_custom_root_causes(legacy, custom) if delta_type == "only_custom_bad" else []
    )

    return {
        "case_id": case_id,
        "delta_type": delta_type,
        "query": reference.get("query"),
        "query_type": reference.get("query_type"),
        "expected_source_id": reference.get("expected_source_id"),
        "expected_doc_type": reference.get("expected_doc_type"),
        "expected_keywords": reference.get("expected_keywords") or [],
        "legacy": compact_row(legacy),
        "custom_graph": compact_row(custom),
        "custom_graph_planner_debug": (custom or {}).get("planner_debug") or {},
        "custom_graph_judge_debug": (custom or {}).get("judge_debug") or {},
        "custom_graph_graph_debug": (custom or {}).get("graph_debug") or {},
        "custom_graph_nodes_executed": (custom or {}).get("nodes_executed") or [],
        "custom_graph_planner_type": (custom or {}).get("planner_type"),
        "custom_graph_judge_verdict": (custom or {}).get("judge_verdict"),
        "custom_graph_multi_hop_enabled": (custom or {}).get("multi_hop_enabled"),
        "custom_graph_root_causes": custom_root_causes,
    }


def summarize_results(
    summary: dict[str, Any],
    delta_results: list[dict[str, Any]],
) -> dict[str, Any]:
    only_custom = [
        result for result in delta_results if result["delta_type"] == "only_custom_bad"
    ]
    only_legacy = [
        result for result in delta_results if result["delta_type"] == "only_legacy_bad"
    ]

    root_causes = Counter(
        cause for result in only_custom for cause in result["custom_graph_root_causes"]
    )
    planner_types = Counter(
        str(result.get("custom_graph_planner_type") or "none") for result in only_custom
    )
    judge_verdicts = Counter(
        str(result.get("custom_graph_judge_verdict") or "none") for result in only_custom
    )

    recommendations = [
        "Run judge ablation before changing retrieval policy because only-custom deltas include judge_side_effect signals.",
        "Run planner debug-only ablation if planner_side_effect persists after judge ablation.",
        "Inspect answer generation and source ordering for only-custom deltas that have retrieval_order_diff.",
        "Defer conservative multi-hop gate changes until judge/planner residual deltas are isolated.",
    ]

    return {
        "phase": "7D-1b_residual_delta_diagnosis",
        "input_results": str(RESULTS_PATH),
        "input_summary": str(SUMMARY_PATH),
        "legacy_bad_case_count": summary.get("legacy", {}).get("bad_case_count"),
        "custom_graph_bad_case_count": summary.get("custom_graph", {}).get("bad_case_count"),
        "legacy_calibrated_bad_case_count": summary.get("legacy", {}).get(
            "calibrated_bad_case_count"
        ),
        "custom_graph_calibrated_bad_case_count": summary.get("custom_graph", {}).get(
            "calibrated_bad_case_count"
        ),
        "only_custom_bad_count": len(only_custom),
        "only_legacy_bad_count": len(only_legacy),
        "only_custom_bad_case_ids": [result["case_id"] for result in only_custom],
        "only_legacy_bad_case_ids": [result["case_id"] for result in only_legacy],
        "only_custom_root_cause_distribution": dict(root_causes),
        "only_custom_planner_type_distribution": dict(planner_types),
        "only_custom_judge_verdict_distribution": dict(judge_verdicts),
        "planner_side_effect_found": root_causes.get("planner_side_effect", 0) > 0,
        "judge_side_effect_found": root_causes.get("judge_side_effect", 0) > 0,
        "retrieval_order_diff_found": root_causes.get("retrieval_order_diff", 0) > 0,
        "recommend_judge_ablation": root_causes.get("judge_side_effect", 0) > 0,
        "recommend_planner_debug_only_ablation": root_causes.get(
            "planner_side_effect", 0
        )
        > 0,
        "recommend_defer_conservative_multi_hop_gate": True,
        "recommendations": recommendations,
        "calls_llm": False,
        "writes_chroma": False,
        "runs_240_case": False,
        "runs_benchmark": False,
    }


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows)
        + "\n",
        encoding="utf-8",
    )


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def write_doc(summary: dict[str, Any]) -> None:
    custom_ids = ", ".join(summary["only_custom_bad_case_ids"])
    legacy_ids = ", ".join(summary["only_legacy_bad_case_ids"])
    root_causes = "\n".join(
        f"- {name}: {count}"
        for name, count in summary["only_custom_root_cause_distribution"].items()
    )
    recommendations = "\n".join(
        f"- {item}" for item in summary["recommendations"]
    )

    DOC_PATH.write_text(
        f"""# Phase 7D-1b Residual Delta Diagnosis

## Scope

This diagnosis reads the existing Phase 7D-1 enriched JSONL and summary files only. It does not call endpoints, does not invoke an LLM, does not run 240-case evaluation again, and does not write Chroma.

## Input

- `{RESULTS_PATH.as_posix()}`
- `{SUMMARY_PATH.as_posix()}`

## Delta Counts

```text
legacy bad_case_count = {summary["legacy_bad_case_count"]}
custom_graph bad_case_count = {summary["custom_graph_bad_case_count"]}
only_custom_bad = {summary["only_custom_bad_count"]}
only_legacy_bad = {summary["only_legacy_bad_count"]}
```

## Only Custom Bad Cases

```text
{custom_ids}
```

## Only Legacy Bad Cases

```text
{legacy_ids}
```

## Only Custom Root-Cause Distribution

{root_causes}

## Side-Effect Signals

```text
planner_side_effect_found = {summary["planner_side_effect_found"]}
judge_side_effect_found = {summary["judge_side_effect_found"]}
retrieval_order_diff_found = {summary["retrieval_order_diff_found"]}
```

## Recommendations

{recommendations}

## Boundary

This is a residual delta diagnosis, not a production benchmark. It does not claim custom_graph is better than legacy and does not claim all bad cases are resolved.
""",
        encoding="utf-8",
    )


def main() -> None:
    rows = read_jsonl(RESULTS_PATH)
    summary = read_json(SUMMARY_PATH)
    indexed = build_case_index(rows)

    only_custom_ids = summary.get("only_custom_graph_bad_case_ids") or []
    only_legacy_ids = summary.get("only_legacy_bad_case_ids") or []

    delta_results = [
        build_delta_result(case_id, "only_custom_bad", indexed.get(case_id, {}))
        for case_id in only_custom_ids
    ]
    delta_results.extend(
        build_delta_result(case_id, "only_legacy_bad", indexed.get(case_id, {}))
        for case_id in only_legacy_ids
    )

    diagnosis_summary = summarize_results(summary, delta_results)
    write_jsonl(OUT_RESULTS_PATH, delta_results)
    write_json(OUT_SUMMARY_PATH, diagnosis_summary)
    write_doc(diagnosis_summary)

    print(json.dumps(diagnosis_summary, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
