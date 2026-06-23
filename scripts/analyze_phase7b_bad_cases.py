"""Offline Phase 7B bad-case diagnostics for Phase 7A regression outputs."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
EVAL_DIR = ROOT / "data" / "knowledge_base" / "evaluation"

LEGACY_RESULTS = EVAL_DIR / "phase7a_after_fix_deepseek_legacy_240_results.jsonl"
CUSTOM_RESULTS = EVAL_DIR / "phase7a_after_fix_deepseek_custom_240_results.jsonl"
LEGACY_SUMMARY = EVAL_DIR / "phase7a_after_fix_deepseek_legacy_240_summary.json"
CUSTOM_SUMMARY = EVAL_DIR / "phase7a_after_fix_deepseek_custom_240_summary.json"
REGRESSION_SUMMARY = EVAL_DIR / "phase7a_after_fix_deepseek_240_regression_summary.json"

OUT_RESULTS = EVAL_DIR / "phase7b_bad_case_diagnostics_results.jsonl"
OUT_SUMMARY = EVAL_DIR / "phase7b_bad_case_diagnostics_summary.json"


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "ok", "pass", "passed"}
    return bool(value)


def _is_error(row: dict[str, Any]) -> bool:
    if row.get("error_type") or row.get("error_summary"):
        return True
    status = row.get("http_status")
    if isinstance(status, int) and status >= 400:
        return True
    return row.get("request_success") is False


def _is_timeout(row: dict[str, Any]) -> bool:
    fields = [row.get("error_type"), row.get("error_summary"), row.get("retrieval_error_summary")]
    return any("timeout" in str(value).lower() for value in fields if value)


def _mode_flags(row: dict[str, Any]) -> dict[str, bool]:
    source_miss = row.get("source_hit") is False
    keyword_miss = row.get("keyword_hit") is False
    doc_type_miss = row.get("doc_type_hit") is False
    empty_answer = row.get("answer_non_empty") is False or not str(row.get("answer_preview") or "").strip()
    schema_invalid = row.get("response_schema_valid") is False
    error = _is_error(row)
    timeout = _is_timeout(row)
    proxy_bad = any(
        [
            source_miss,
            keyword_miss,
            doc_type_miss,
            empty_answer,
            schema_invalid,
            error,
            timeout,
        ]
    )
    return {
        "source_miss": source_miss,
        "keyword_miss": keyword_miss,
        "doc_type_miss": doc_type_miss,
        "empty_answer": empty_answer,
        "schema_invalid": schema_invalid,
        "error": error,
        "timeout": timeout,
        "diagnostic_bad_proxy": proxy_bad,
    }


def _infer_planner_type(row: dict[str, Any]) -> str:
    planner_debug = row.get("planner_debug")
    if isinstance(planner_debug, dict):
        for key in ("planner_type", "query_complexity", "query_type"):
            value = planner_debug.get(key)
            if value:
                return str(value)
    query_type = str(row.get("query_type") or "unknown")
    if query_type == "multi_hop_lookup":
        return "multi_hop"
    if query_type == "ambiguous_query":
        return "ambiguous"
    if query_type == "negative_banned_source":
        return "unsupported_or_guarded"
    if query_type in {"code_api_config", "citation_required_query", "exact_metadata_lookup"}:
        return "complex"
    return "simple_or_semantic"


def _judge_verdict(row: dict[str, Any]) -> str:
    judge_debug = row.get("judge_debug")
    if isinstance(judge_debug, dict):
        return str(judge_debug.get("verdict") or judge_debug.get("status") or "unknown")
    return "not_persisted_in_result_jsonl"


def _patterns(row: dict[str, Any], flags: dict[str, bool]) -> list[str]:
    patterns: list[str] = []
    query_type = str(row.get("query_type") or "unknown")
    if flags["source_miss"]:
        patterns.append("source_miss")
    if flags["doc_type_miss"]:
        patterns.append("doc_type_miss")
    if flags["source_miss"] and flags["doc_type_miss"]:
        patterns.append("source_and_doc_type_miss")
    if flags["keyword_miss"]:
        patterns.append("keyword_miss")
    if flags["empty_answer"]:
        patterns.append("empty_answer")
    if flags["schema_invalid"]:
        patterns.append("schema_invalid")
    if flags["error"]:
        patterns.append("runtime_error")
    if flags["timeout"]:
        patterns.append("timeout")
    if query_type == "multi_hop_lookup" and flags["diagnostic_bad_proxy"]:
        patterns.append("multi_hop_bad_proxy")
    if query_type == "citation_required_query" and flags["diagnostic_bad_proxy"]:
        patterns.append("citation_required_bad_proxy")
    if query_type == "exact_metadata_lookup" and flags["source_miss"]:
        patterns.append("metadata_lookup_source_miss")
    return patterns or ["no_visible_failure_signal"]


def _count_flags(rows: list[dict[str, Any]]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for row in rows:
        for key, enabled in _mode_flags(row).items():
            if enabled:
                counts[key] += 1
    return counts


def _summary_for_mode(rows: list[dict[str, Any]], summary: dict[str, Any]) -> dict[str, Any]:
    flags = _count_flags(rows)
    planner = Counter(_infer_planner_type(row) for row in rows)
    judge = Counter(_judge_verdict(row) for row in rows)
    query_type = Counter(str(row.get("query_type") or "unknown") for row in rows)
    multi_hop_rows = [row for row in rows if str(row.get("query_type")) == "multi_hop_lookup"]
    multi_hop_bad_proxy = sum(_mode_flags(row)["diagnostic_bad_proxy"] for row in multi_hop_rows)
    pattern_counts: Counter[str] = Counter()
    for row in rows:
        row_flags = _mode_flags(row)
        if row_flags["diagnostic_bad_proxy"]:
            pattern_counts.update(_patterns(row, row_flags))
    return {
        "case_count": len(rows),
        "calibrated_bad_case_count": summary.get("bad_case_count"),
        "available_bad_case_id_count": len(summary.get("bad_case_ids") or []),
        "source_miss_count": flags["source_miss"],
        "keyword_miss_count": flags["keyword_miss"],
        "doc_type_miss_count": flags["doc_type_miss"],
        "empty_answer_count": flags["empty_answer"],
        "schema_invalid_count": flags["schema_invalid"],
        "error_count": flags["error"],
        "timeout_count": flags["timeout"],
        "diagnostic_bad_proxy_count": flags["diagnostic_bad_proxy"],
        "multi_hop_case_count": len(multi_hop_rows),
        "multi_hop_bad_proxy_count": multi_hop_bad_proxy,
        "planner_type_distribution": dict(planner),
        "judge_verdict_distribution": dict(judge),
        "query_type_distribution": dict(query_type),
        "top_bad_case_patterns": pattern_counts.most_common(10),
    }


def main() -> None:
    legacy_rows = _load_jsonl(LEGACY_RESULTS)
    custom_rows = _load_jsonl(CUSTOM_RESULTS)
    legacy_summary = _load_json(LEGACY_SUMMARY)
    custom_summary = _load_json(CUSTOM_SUMMARY)
    regression_summary = _load_json(REGRESSION_SUMMARY)

    legacy_by_id = {str(row["case_id"]): row for row in legacy_rows}
    custom_by_id = {str(row["case_id"]): row for row in custom_rows}
    case_ids = sorted(set(legacy_by_id) | set(custom_by_id))

    legacy_bad_ids = set(str(x) for x in legacy_summary.get("bad_case_ids") or [])
    custom_bad_ids = set(str(x) for x in custom_summary.get("bad_case_ids") or [])
    shared_available_bad_ids = sorted(legacy_bad_ids & custom_bad_ids)
    only_legacy_available_bad_ids = sorted(legacy_bad_ids - custom_bad_ids)
    only_custom_available_bad_ids = sorted(custom_bad_ids - legacy_bad_ids)

    results: list[dict[str, Any]] = []
    shared_proxy = 0
    only_legacy_proxy = 0
    only_custom_proxy = 0
    pattern_counts: Counter[str] = Counter()

    for case_id in case_ids:
        legacy_row = legacy_by_id.get(case_id, {})
        custom_row = custom_by_id.get(case_id, {})
        legacy_flags = _mode_flags(legacy_row)
        custom_flags = _mode_flags(custom_row)
        if legacy_flags["diagnostic_bad_proxy"] and custom_flags["diagnostic_bad_proxy"]:
            shared_proxy += 1
        elif legacy_flags["diagnostic_bad_proxy"]:
            only_legacy_proxy += 1
        elif custom_flags["diagnostic_bad_proxy"]:
            only_custom_proxy += 1
        if custom_flags["diagnostic_bad_proxy"]:
            pattern_counts.update(_patterns(custom_row or legacy_row, custom_flags))
        results.append(
            {
                "case_id": case_id,
                "query": custom_row.get("query") or legacy_row.get("query"),
                "query_type": custom_row.get("query_type") or legacy_row.get("query_type"),
                "expected_source_id": custom_row.get("expected_source_id")
                or legacy_row.get("expected_source_id"),
                "legacy_available_calibrated_bad": case_id in legacy_bad_ids,
                "custom_available_calibrated_bad": case_id in custom_bad_ids,
                "available_shared_calibrated_bad": case_id in shared_available_bad_ids,
                "legacy_flags": legacy_flags,
                "custom_graph_flags": custom_flags,
                "diagnostic_shared_bad_proxy": legacy_flags["diagnostic_bad_proxy"]
                and custom_flags["diagnostic_bad_proxy"],
                "diagnostic_only_legacy_bad_proxy": legacy_flags["diagnostic_bad_proxy"]
                and not custom_flags["diagnostic_bad_proxy"],
                "diagnostic_only_custom_graph_bad_proxy": custom_flags["diagnostic_bad_proxy"]
                and not legacy_flags["diagnostic_bad_proxy"],
                "planner_type": _infer_planner_type(custom_row or legacy_row),
                "judge_verdict": _judge_verdict(custom_row),
                "multi_hop_enabled_proxy": str(
                    (custom_row or legacy_row).get("query_type") or ""
                )
                == "multi_hop_lookup",
                "patterns": _patterns(custom_row or legacy_row, custom_flags),
            }
        )

    OUT_RESULTS.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in results) + "\n",
        encoding="utf-8",
    )

    summary = {
        "phase": "7B_bad_case_diagnostics",
        "input_files": {
            "legacy_results": str(LEGACY_RESULTS.relative_to(ROOT)),
            "custom_graph_results": str(CUSTOM_RESULTS.relative_to(ROOT)),
            "legacy_summary": str(LEGACY_SUMMARY.relative_to(ROOT)),
            "custom_graph_summary": str(CUSTOM_SUMMARY.relative_to(ROOT)),
            "regression_summary": str(REGRESSION_SUMMARY.relative_to(ROOT)),
        },
        "case_count": len(case_ids),
        "regression_summary_bad_case_count": regression_summary.get("bad_case_count"),
        "legacy": _summary_for_mode(legacy_rows, legacy_summary),
        "custom_graph": _summary_for_mode(custom_rows, custom_summary),
        "available_calibrated_bad_id_note": (
            "The Phase 7A summary stores only the available bad_case_ids list, while the "
            "authoritative calibrated bad_case_count is recorded separately."
        ),
        "available_bad_id_overlap": {
            "shared_bad_case_count": len(shared_available_bad_ids),
            "only_legacy_bad_count": len(only_legacy_available_bad_ids),
            "only_custom_graph_bad_count": len(only_custom_available_bad_ids),
            "shared_bad_case_ids": shared_available_bad_ids,
            "only_legacy_bad_case_ids": only_legacy_available_bad_ids,
            "only_custom_graph_bad_case_ids": only_custom_available_bad_ids,
        },
        "diagnostic_bad_proxy_overlap": {
            "shared_bad_proxy_count": shared_proxy,
            "only_legacy_bad_proxy_count": only_legacy_proxy,
            "only_custom_graph_bad_proxy_count": only_custom_proxy,
        },
        "top_bad_case_patterns": pattern_counts.most_common(10),
        "diagnostic_boundaries": {
            "calls_llm": False,
            "writes_chroma": False,
            "runs_240_case": False,
            "uses_existing_results_only": True,
        },
        "recommended_next_actions": [
            "Prioritize source/doc-type miss analysis before changing planner policy.",
            "Persist planner_debug and judge_debug in future 240-case JSONL if deeper Phase 7 diagnostics are needed.",
            "Treat multi-hop improvements conservatively because the visible result rows do not retain subquery debug.",
        ],
    }
    OUT_SUMMARY.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
