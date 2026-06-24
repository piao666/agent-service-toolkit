"""Analyze Phase 7E answer/source alignment from persisted result previews.

This script is offline-only. It expects a future Phase 7E-4B result file with
answer previews, source previews, source sequences, and prompt profiles.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

EVAL_DIR = Path("data/knowledge_base/evaluation")
INPUT_RESULTS = EVAL_DIR / "phase7e_answer_source_topk10_results.jsonl"
INPUT_SUMMARY = EVAL_DIR / "phase7e_answer_source_topk10_summary.json"
OUT_RESULTS = EVAL_DIR / "phase7e_answer_source_alignment_results.jsonl"
OUT_SUMMARY = EVAL_DIR / "phase7e_answer_source_alignment_summary.json"
OUT_DOC = Path("docs/enterprise_rag_backend/PHASE7E_ANSWER_SOURCE_ALIGNMENT_DIAGNOSIS.md")


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


def is_bad(row: dict[str, Any]) -> bool:
    return bool(row.get("calibrated_bad_case", row.get("bad_case", False)))


def row_by_case_and_mode(rows: list[dict[str, Any]]) -> dict[str, dict[str, dict[str, Any]]]:
    grouped: dict[str, dict[str, dict[str, Any]]] = {}
    for row in rows:
        case_id = str(row.get("case_id") or "")
        mode = str(row.get("mode") or "")
        if case_id and mode in {"legacy", "custom_graph"}:
            grouped.setdefault(case_id, {})[mode] = row
    return grouped


def sequence(row: dict[str, Any], key: str) -> list[Any]:
    value = row.get(key)
    return value if isinstance(value, list) else []


def source_sequence_equal(legacy: dict[str, Any], custom: dict[str, Any]) -> bool:
    return (
        sequence(legacy, "source_id_sequence") == sequence(custom, "source_id_sequence")
        and sequence(legacy, "doc_type_sequence") == sequence(custom, "doc_type_sequence")
        and sequence(legacy, "chunk_id_sequence") == sequence(custom, "chunk_id_sequence")
    )


def expected_keywords(row: dict[str, Any]) -> list[str]:
    value = row.get("expected_keywords")
    return [str(item) for item in value] if isinstance(value, list) else []


def answer_contains_keywords(row: dict[str, Any]) -> bool:
    preview = str(row.get("answer_preview") or "").lower()
    keywords = [keyword.lower() for keyword in expected_keywords(row) if keyword.strip()]
    return bool(keywords) and all(keyword in preview for keyword in keywords)


def classify_root_causes(legacy: dict[str, Any], custom: dict[str, Any]) -> list[str]:
    causes: list[str] = []
    same_sources = source_sequence_equal(legacy, custom)
    if same_sources and legacy.get("answer_sha256") != custom.get("answer_sha256"):
        causes.append("same_sources_answer_diff")
    if not same_sources:
        causes.append("source_order_diff")
    if not custom.get("sources_persisted"):
        causes.append("source_serialization_diff")
    if not custom.get("keyword_hit"):
        causes.append("custom_missing_keyword_in_answer")
    if answer_contains_keywords(legacy) and not answer_contains_keywords(custom):
        causes.append("legacy_keyword_present_custom_missing")
    if not custom.get("source_hit"):
        causes.append("source_missing")
    if not custom.get("doc_type_hit"):
        causes.append("doc_type_missing")
    required_fields = [
        "answer_preview",
        "answer_sha256",
        "source_id_sequence",
        "doc_type_sequence",
        "chunk_id_sequence",
        "source_previews",
    ]
    if any(field not in custom for field in required_fields):
        causes.append("insufficient_persisted_data")
    return causes or ["unclassified_answer_source_delta"]


def build_result_rows(
    grouped: dict[str, dict[str, dict[str, Any]]],
    only_custom_ids: list[str],
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for case_id in only_custom_ids:
        legacy = grouped.get(case_id, {}).get("legacy", {})
        custom = grouped.get(case_id, {}).get("custom_graph", {})
        reference = custom or legacy
        results.append(
            {
                "case_id": case_id,
                "query": reference.get("query"),
                "query_type": reference.get("query_type"),
                "expected_source_id": reference.get("expected_source_id"),
                "expected_doc_type": reference.get("expected_doc_type"),
                "expected_keywords": reference.get("expected_keywords") or [],
                "legacy_answer_preview": legacy.get("answer_preview"),
                "custom_answer_preview": custom.get("answer_preview"),
                "legacy_source_id_sequence": sequence(legacy, "source_id_sequence"),
                "custom_source_id_sequence": sequence(custom, "source_id_sequence"),
                "legacy_doc_type_sequence": sequence(legacy, "doc_type_sequence"),
                "custom_doc_type_sequence": sequence(custom, "doc_type_sequence"),
                "legacy_chunk_id_sequence": sequence(legacy, "chunk_id_sequence"),
                "custom_chunk_id_sequence": sequence(custom, "chunk_id_sequence"),
                "legacy_bad_case_reasons": legacy.get("bad_case_reasons") or [],
                "custom_bad_case_reasons": custom.get("bad_case_reasons") or [],
                "legacy_prompt_profile": legacy.get("prompt_profile") or {},
                "custom_prompt_profile": custom.get("prompt_profile") or {},
                "root_causes": classify_root_causes(legacy, custom),
            }
        )
    return results


def write_doc(summary: dict[str, Any]) -> None:
    root_lines = "\n".join(
        f"- {key}: {value}"
        for key, value in summary["only_custom_root_cause_distribution"].items()
    )
    text = f"""# Phase 7E Answer / Source Alignment Diagnosis

## Scope

This diagnosis reads persisted answer/source preview artifacts only. It does not call an endpoint, does not call an LLM, does not run 240 cases, and does not write Chroma.

## Inputs

```text
{INPUT_RESULTS}
{INPUT_SUMMARY}
```

## Result

- only_custom_bad_count: {summary["only_custom_bad_count"]}
- only_custom_bad_case_ids: {", ".join(summary["only_custom_bad_case_ids"]) or "none"}

## Root Cause Distribution

{root_lines}

## Recommendation

- recommend_prompt_alignment: {summary["recommend_prompt_alignment"]}
- recommend_source_ordering_fix: {summary["recommend_source_ordering_fix"]}
- recommend_data_or_chunk_optimization: {summary["recommend_data_or_chunk_optimization"]}

## Boundary

This is diagnostic support for later small-scope HPC evaluation. It does not claim production readiness or complete bad-case resolution.
"""
    OUT_DOC.parent.mkdir(parents=True, exist_ok=True)
    OUT_DOC.write_text(text, encoding="utf-8")


def main() -> int:
    if not INPUT_RESULTS.exists() or not INPUT_SUMMARY.exists():
        print("Phase 7E-4B results not found. Run HPC answer/source persistence eval first.")
        return 0

    source_summary = read_json(INPUT_SUMMARY)
    rows = read_jsonl(INPUT_RESULTS)
    grouped = row_by_case_and_mode(rows)

    if "only_custom_graph_calibrated_bad_case_ids" in source_summary:
        only_custom_ids = list(source_summary.get("only_custom_graph_calibrated_bad_case_ids") or [])
    else:
        legacy_bad = {
            case_id for case_id, modes in grouped.items() if is_bad(modes.get("legacy", {}))
        }
        custom_bad = {
            case_id for case_id, modes in grouped.items() if is_bad(modes.get("custom_graph", {}))
        }
        only_custom_ids = sorted(custom_bad - legacy_bad)

    result_rows = build_result_rows(grouped, only_custom_ids)
    root_counter: Counter[str] = Counter()
    for row in result_rows:
        root_counter.update(row["root_causes"])

    root_distribution = dict(sorted(root_counter.items()))
    summary = {
        "phase": "7E_answer_source_alignment_diagnosis",
        "input_results": str(INPUT_RESULTS),
        "input_summary": str(INPUT_SUMMARY),
        "only_custom_bad_case_ids": only_custom_ids,
        "only_custom_bad_count": len(only_custom_ids),
        "only_custom_root_cause_distribution": root_distribution,
        "recommend_prompt_alignment": any(
            key in root_counter
            for key in (
                "same_sources_answer_diff",
                "custom_missing_keyword_in_answer",
                "legacy_keyword_present_custom_missing",
            )
        ),
        "recommend_source_ordering_fix": root_counter["source_order_diff"] > 0,
        "recommend_data_or_chunk_optimization": any(
            key in root_counter for key in ("source_missing", "doc_type_missing")
        ),
        "calls_llm": False,
        "runs_240_case": False,
        "writes_chroma": False,
    }
    write_jsonl(OUT_RESULTS, result_rows)
    write_json(OUT_SUMMARY, summary)
    write_doc(summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
