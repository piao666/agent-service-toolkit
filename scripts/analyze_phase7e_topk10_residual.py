"""Analyze Phase 7E top_k=10 residual delta cases offline."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

EVAL_DIR = Path("data/knowledge_base/evaluation")
INPUT_RESULTS = EVAL_DIR / "phase7e_delta_topk10_deepseek_results.jsonl"
INPUT_SUMMARY = EVAL_DIR / "phase7e_delta_topk10_deepseek_summary.json"
OUT_RESULTS = EVAL_DIR / "phase7e_topk10_residual_results.jsonl"
OUT_SUMMARY = EVAL_DIR / "phase7e_topk10_residual_summary.json"
OUT_DOC = Path("docs/enterprise_rag_backend/PHASE7E_TOPK10_RESIDUAL_DIAGNOSIS.md")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
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


def truncate_text(value: Any, limit: int = 240) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    return value[:limit] + ("..." if len(value) > limit else "")


def compact_sources(row: dict[str, Any]) -> list[dict[str, Any]] | str:
    sources = row.get("sources")
    if not isinstance(sources, list):
        return "not_persisted_in_result_jsonl"
    compacted = []
    for source in sources[:10]:
        if not isinstance(source, dict):
            continue
        metadata = source.get("metadata") if isinstance(source.get("metadata"), dict) else {}
        compacted.append(
            {
                "source": source.get("source"),
                "source_id": source.get("source_id") or metadata.get("source_id"),
                "title": source.get("title") or metadata.get("title"),
                "doc_type": source.get("doc_type") or metadata.get("doc_type"),
                "chunk_id": source.get("chunk_id") or metadata.get("chunk_id"),
                "relevance_score": source.get("relevance_score") or source.get("score"),
            }
        )
    return compacted


def is_bad(row: dict[str, Any]) -> bool:
    return bool(row.get("calibrated_bad_case", row.get("bad_case", False)))


def summarize_mode(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "answer_summary": truncate_text(row.get("answer")) or "not_persisted_in_result_jsonl",
        "sources": compact_sources(row),
        "bad_case_reasons": row.get("bad_case_reasons") or [],
        "calibrated_bad_case_reasons": row.get("calibrated_bad_case_reasons") or [],
        "answer_non_empty": bool(row.get("answer_non_empty")),
        "schema_valid": bool(row.get("schema_valid")),
        "source_count": row.get("source_count"),
        "source_hit": bool(row.get("source_hit")),
        "doc_type_hit": bool(row.get("doc_type_hit")),
        "keyword_hit": bool(row.get("keyword_hit")),
        "latency_ms": row.get("latency_ms"),
        "error": row.get("error"),
        "timeout": bool(row.get("timeout")),
        "retrieval_debug": row.get("retrieval_debug") or {},
    }


def classify_only_custom(legacy: dict[str, Any], custom: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    if not custom.get("source_hit"):
        reasons.append("source_still_missing")
    if not custom.get("doc_type_hit"):
        reasons.append("doc_type_still_missing")
    if not custom.get("keyword_hit"):
        reasons.append("keyword_still_missing")
    if (
        legacy.get("source_hit")
        and custom.get("source_hit")
        and legacy.get("doc_type_hit")
        and custom.get("doc_type_hit")
        and legacy.get("keyword_hit")
        and not custom.get("keyword_hit")
    ):
        reasons.append("answer_synthesis_diff")
    if "sources" not in legacy or "sources" not in custom:
        reasons.append("source_serialization_not_persisted")
    if not legacy.get("keyword_hit") and not custom.get("keyword_hit"):
        reasons.append("evaluator_threshold_or_shared_keyword_gap")
    if not custom.get("source_hit") and not custom.get("doc_type_hit"):
        reasons.append("data_or_chunk_gap")
    return reasons or ["unclassified_delta"]


def has_source_ordering_diff(legacy: dict[str, Any], custom: dict[str, Any]) -> bool | str:
    if not isinstance(legacy.get("sources"), list) or not isinstance(custom.get("sources"), list):
        return "not_persisted_in_result_jsonl"
    legacy_ids = [source_identifier(source) for source in legacy.get("sources", [])]
    custom_ids = [source_identifier(source) for source in custom.get("sources", [])]
    return legacy_ids != custom_ids


def source_identifier(source: Any) -> str | None:
    if not isinstance(source, dict):
        return None
    metadata = source.get("metadata") if isinstance(source.get("metadata"), dict) else {}
    return (
        source.get("source_id")
        or metadata.get("source_id")
        or source.get("chunk_id")
        or metadata.get("chunk_id")
        or source.get("title")
        or metadata.get("title")
    )


def build_rows(
    by_case: dict[str, dict[str, dict[str, Any]]],
    only_custom_ids: list[str],
    only_legacy_ids: list[str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for delta_type, ids in (
        ("only_custom_bad", only_custom_ids),
        ("only_legacy_bad", only_legacy_ids),
    ):
        for case_id in ids:
            modes = by_case.get(case_id, {})
            legacy = modes.get("legacy", {})
            custom = modes.get("custom_graph", {})
            reference = custom or legacy
            root_causes = classify_only_custom(legacy, custom) if delta_type == "only_custom_bad" else []
            rows.append(
                {
                    "case_id": case_id,
                    "delta_type": delta_type,
                    "query": reference.get("query"),
                    "query_type": reference.get("query_type"),
                    "expected_source_id": reference.get("expected_source_id"),
                    "expected_doc_type": reference.get("expected_doc_type"),
                    "expected_keywords": reference.get("expected_keywords") or [],
                    "legacy": summarize_mode(legacy),
                    "custom_graph": summarize_mode(custom),
                    "custom_graph_planner_debug": custom.get("planner_debug") or {},
                    "custom_graph_judge_debug": custom.get("judge_debug") or {},
                    "custom_graph_graph_debug": custom.get("graph_debug") or {},
                    "custom_graph_nodes_executed": custom.get("nodes_executed") or [],
                    "source_ordering_diff": has_source_ordering_diff(legacy, custom),
                    "root_causes": root_causes,
                }
            )
    return rows


def write_doc(summary: dict[str, Any]) -> None:
    only_custom = ", ".join(summary["only_custom_bad_case_ids"]) or "none"
    only_legacy = ", ".join(summary["only_legacy_bad_case_ids"]) or "none"
    root_lines = "\n".join(
        f"- {key}: {value}" for key, value in summary["only_custom_root_cause_distribution"].items()
    )
    text = f"""# Phase 7E TopK=10 Residual Diagnosis

## Scope

This is an offline diagnosis of the Phase 7E top_k=10 delta-case run. It reads existing JSONL results only. It does not call an endpoint, does not call an LLM, does not run a full 240-case evaluation, and does not write Chroma.

## Input

```text
{INPUT_RESULTS}
{INPUT_SUMMARY}
```

## Residual Delta

- only_custom_bad: {summary["only_custom_bad_count"]}
- only_custom_bad case ids: {only_custom}
- only_legacy_bad: {summary["only_legacy_bad_count"]}
- only_legacy_bad case ids: {only_legacy}

## Only-Custom Root Cause Distribution

{root_lines}

## Findings

- source_ordering_diff: {summary["source_ordering_diff_found"]}
- answer_synthesis_diff: {summary["answer_synthesis_diff_found"]}
- source_serialization_diff: {summary["source_serialization_diff_found"]}
- data_or_chunk_gap: {summary["data_or_chunk_gap_found"]}

The current result shows that top_k=10 is the best tested delta setting, but custom_graph still does not meet `custom_graph <= legacy` on the delta set.

## Recommendation

- Full 240 with top_k=10: {summary["recommend_full_240_with_topk10"]}
- Source ordering small fix: {summary["recommend_source_ordering_fix"]}
- Answer prompt alignment: {summary["recommend_answer_prompt_alignment"]}
- Data/chunk optimization: {summary["recommend_data_or_chunk_optimization"]}

## Boundary

This diagnosis does not claim custom_graph is better than legacy and does not represent a production benchmark.
"""
    OUT_DOC.parent.mkdir(parents=True, exist_ok=True)
    OUT_DOC.write_text(text, encoding="utf-8")


def main() -> None:
    summary = read_json(INPUT_SUMMARY)
    records = read_jsonl(INPUT_RESULTS)
    by_case: dict[str, dict[str, dict[str, Any]]] = {}
    for record in records:
        case_id = str(record.get("case_id") or "")
        mode = str(record.get("mode") or "")
        if case_id and mode in {"legacy", "custom_graph"}:
            by_case.setdefault(case_id, {})[mode] = record

    only_custom_ids = summary.get("only_custom_graph_calibrated_bad_case_ids") or summary.get(
        "only_custom_graph_bad_case_ids", []
    )
    only_legacy_ids = summary.get("only_legacy_calibrated_bad_case_ids") or summary.get(
        "only_legacy_bad_case_ids", []
    )
    result_rows = build_rows(by_case, only_custom_ids, only_legacy_ids)

    root_counter: Counter[str] = Counter()
    for row in result_rows:
        if row["delta_type"] == "only_custom_bad":
            root_counter.update(row["root_causes"])

    root_distribution = dict(sorted(root_counter.items()))
    source_ordering_diff_found = any(row.get("source_ordering_diff") is True for row in result_rows)
    answer_synthesis_diff_found = root_counter["answer_synthesis_diff"] > 0
    source_serialization_diff_found = root_counter["source_serialization_not_persisted"] > 0
    data_or_chunk_gap_found = root_counter["data_or_chunk_gap"] > 0

    out_summary = {
        "phase": "7E-3_topk10_residual_diagnosis",
        "input_results": str(INPUT_RESULTS),
        "input_summary": str(INPUT_SUMMARY),
        "only_custom_bad_case_ids": only_custom_ids,
        "only_custom_bad_count": len(only_custom_ids),
        "only_legacy_bad_case_ids": only_legacy_ids,
        "only_legacy_bad_count": len(only_legacy_ids),
        "only_custom_root_cause_distribution": root_distribution,
        "source_ordering_diff_found": source_ordering_diff_found,
        "answer_synthesis_diff_found": answer_synthesis_diff_found,
        "source_serialization_diff_found": source_serialization_diff_found,
        "data_or_chunk_gap_found": data_or_chunk_gap_found,
        "answer_and_source_detail_persistence": "answer/sources not persisted in current JSONL",
        "recommend_full_240_with_topk10": False,
        "recommend_source_ordering_fix": bool(source_ordering_diff_found),
        "recommend_answer_prompt_alignment": bool(answer_synthesis_diff_found),
        "recommend_data_or_chunk_optimization": bool(data_or_chunk_gap_found),
        "calls_llm": False,
        "runs_full_240_case": False,
        "writes_chroma": False,
    }
    write_jsonl(OUT_RESULTS, result_rows)
    write_json(OUT_SUMMARY, out_summary)
    write_doc(out_summary)
    print(json.dumps(out_summary, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
