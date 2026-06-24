"""Analyze Phase 7E answer/source alignment from persisted previews.

The script is offline-only: it reads persisted JSON/JSONL artifacts, compares
legacy and custom_graph rows, and writes diagnosis outputs. It does not call
endpoints, LLMs, or Chroma.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

EVAL_DIR = Path("data/knowledge_base/evaluation")
DEFAULT_RESULTS = EVAL_DIR / "phase7e_answer_source_topk10_results.jsonl"
DEFAULT_SUMMARY = EVAL_DIR / "phase7e_answer_source_topk10_summary.json"
DEFAULT_OUTPUT_JSON = EVAL_DIR / "phase7e_answer_source_alignment_diagnosis.json"
DEFAULT_OUTPUT_JSONL = EVAL_DIR / "phase7e_answer_source_alignment_results.jsonl"
DEFAULT_OUTPUT_MD = Path("docs/enterprise_rag_backend/PHASE7E_ANSWER_SOURCE_ALIGNMENT_DIAGNOSIS.md")


def resolve_path(value: str | Path, *, default_dir: Path = EVAL_DIR) -> Path:
    path = Path(value)
    if path.is_absolute() or path.parent != Path("."):
        return path
    candidate = default_dir / path
    return candidate if candidate.exists() or path.suffix else path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze Phase 7E answer/source alignment.")
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT_JSON)
    parser.add_argument("--output-jsonl", type=Path, default=DEFAULT_OUTPUT_JSONL)
    parser.add_argument("--output-md", type=Path, default=DEFAULT_OUTPUT_MD)
    return parser.parse_args()


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


def group_by_case(rows: list[dict[str, Any]]) -> dict[str, dict[str, dict[str, Any]]]:
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


def source_hashes(row: dict[str, Any]) -> list[Any]:
    previews = row.get("source_previews")
    if not isinstance(previews, list):
        return []
    hashes = []
    for source in previews:
        if isinstance(source, dict):
            hashes.append(source.get("content_sha256"))
    return hashes


def source_sequences_match(legacy: dict[str, Any], custom: dict[str, Any]) -> bool:
    return (
        sequence(legacy, "source_id_sequence") == sequence(custom, "source_id_sequence")
        and sequence(legacy, "doc_type_sequence") == sequence(custom, "doc_type_sequence")
        and sequence(legacy, "chunk_id_sequence") == sequence(custom, "chunk_id_sequence")
    )


def source_previews_match_or_overlap(legacy: dict[str, Any], custom: dict[str, Any]) -> dict[str, Any]:
    legacy_hashes = [value for value in source_hashes(legacy) if value]
    custom_hashes = [value for value in source_hashes(custom) if value]
    if not legacy_hashes or not custom_hashes:
        return {"match": False, "overlap_rate": 0.0, "reason": "missing_source_preview_hashes"}
    shared = set(legacy_hashes) & set(custom_hashes)
    denominator = max(len(set(legacy_hashes)), len(set(custom_hashes)))
    overlap_rate = len(shared) / denominator if denominator else 0.0
    return {
        "match": legacy_hashes == custom_hashes,
        "overlap_rate": round(overlap_rate, 4),
        "shared_hash_count": len(shared),
    }


def answer_keyword_hit(row: dict[str, Any]) -> bool:
    keywords = [str(item).lower() for item in row.get("expected_keywords") or [] if str(item).strip()]
    answer = str(row.get("answer_preview") or "").lower()
    return bool(keywords) and all(keyword in answer for keyword in keywords)


def prompt_profile_diff(legacy: dict[str, Any], custom: dict[str, Any]) -> bool:
    legacy_profile = legacy.get("prompt_profile") if isinstance(legacy.get("prompt_profile"), dict) else {}
    custom_profile = custom.get("prompt_profile") if isinstance(custom.get("prompt_profile"), dict) else {}
    comparable_keys = ["top_k", "planner_mode", "multi_hop_mode", "judge_mode", "evidence_verifier_mode"]
    for key in comparable_keys:
        if legacy_profile.get(key) != custom_profile.get(key):
            return True
    return False


def classify_case(legacy: dict[str, Any], custom: dict[str, Any]) -> list[str]:
    causes: list[str] = []
    same_sources = source_sequences_match(legacy, custom)
    if same_sources and legacy.get("answer_sha256") != custom.get("answer_sha256"):
        causes.append("same_sources_answer_diff")
    if not same_sources:
        causes.append("source_order_diff")
    if not custom.get("sources_persisted"):
        causes.append("source_serialization_diff")
    if not custom.get("source_hit") or not custom.get("doc_type_hit"):
        causes.append("source_missing_or_doc_type_gap")
    if not custom.get("keyword_hit"):
        causes.append("custom_missing_keyword_in_answer")
    if answer_keyword_hit(legacy) and not answer_keyword_hit(custom):
        causes.append("legacy_keyword_present_custom_missing")
    if prompt_profile_diff(legacy, custom):
        causes.append("prompt_profile_diff")
    if (
        same_sources
        and legacy.get("answer_sha256") != custom.get("answer_sha256")
        and not custom.get("keyword_hit")
    ):
        causes.append("suspected_stochastic_or_synthesis_diff")
    return causes or ["no_clear_alignment_root_cause"]


def comparison_row(case_id: str, delta_type: str, modes: dict[str, dict[str, Any]]) -> dict[str, Any]:
    legacy = modes.get("legacy", {})
    custom = modes.get("custom_graph", {})
    reference = custom or legacy
    preview_overlap = source_previews_match_or_overlap(legacy, custom)
    return {
        "case_id": case_id,
        "delta_type": delta_type,
        "query": reference.get("query"),
        "query_type": reference.get("query_type"),
        "expected_source_id": reference.get("expected_source_id"),
        "expected_doc_type": reference.get("expected_doc_type"),
        "expected_keywords": reference.get("expected_keywords") or [],
        "legacy_bad_case": is_bad(legacy),
        "custom_bad_case": is_bad(custom),
        "legacy_bad_case_reasons": legacy.get("bad_case_reasons") or [],
        "custom_bad_case_reasons": custom.get("bad_case_reasons") or [],
        "legacy_answer_chars": legacy.get("answer_chars"),
        "custom_answer_chars": custom.get("answer_chars"),
        "answer_chars_delta": (custom.get("answer_chars") or 0) - (legacy.get("answer_chars") or 0),
        "answer_sha256_same": legacy.get("answer_sha256") == custom.get("answer_sha256"),
        "legacy_answer_preview": legacy.get("answer_preview"),
        "custom_answer_preview": custom.get("answer_preview"),
        "legacy_answer_keyword_hit": answer_keyword_hit(legacy),
        "custom_answer_keyword_hit": answer_keyword_hit(custom),
        "legacy_source_id_sequence": sequence(legacy, "source_id_sequence"),
        "custom_source_id_sequence": sequence(custom, "source_id_sequence"),
        "legacy_doc_type_sequence": sequence(legacy, "doc_type_sequence"),
        "custom_doc_type_sequence": sequence(custom, "doc_type_sequence"),
        "legacy_chunk_id_sequence": sequence(legacy, "chunk_id_sequence"),
        "custom_chunk_id_sequence": sequence(custom, "chunk_id_sequence"),
        "source_id_sequence_same": sequence(legacy, "source_id_sequence")
        == sequence(custom, "source_id_sequence"),
        "doc_type_sequence_same": sequence(legacy, "doc_type_sequence")
        == sequence(custom, "doc_type_sequence"),
        "chunk_id_sequence_same": sequence(legacy, "chunk_id_sequence")
        == sequence(custom, "chunk_id_sequence"),
        "source_previews_overlap": preview_overlap,
        "legacy_sources_persisted": bool(legacy.get("sources_persisted")),
        "custom_sources_persisted": bool(custom.get("sources_persisted")),
        "legacy_prompt_profile": legacy.get("prompt_profile") or {},
        "custom_prompt_profile": custom.get("prompt_profile") or {},
        "prompt_profile_diff": prompt_profile_diff(legacy, custom),
        "root_causes": classify_case(legacy, custom),
    }


def case_sets(summary: dict[str, Any], grouped: dict[str, dict[str, dict[str, Any]]]) -> dict[str, list[str]]:
    legacy_bad = set(summary.get("legacy_calibrated_bad_case_ids") or summary.get("legacy_bad_case_ids") or [])
    custom_bad = set(
        summary.get("custom_graph_calibrated_bad_case_ids")
        or summary.get("custom_graph_bad_case_ids")
        or []
    )
    if not legacy_bad and not custom_bad:
        legacy_bad = {case_id for case_id, modes in grouped.items() if is_bad(modes.get("legacy", {}))}
        custom_bad = {
            case_id for case_id, modes in grouped.items() if is_bad(modes.get("custom_graph", {}))
        }
    return {
        "shared_bad": sorted(legacy_bad & custom_bad),
        "only_custom_bad": sorted(custom_bad - legacy_bad),
        "only_legacy_bad": sorted(legacy_bad - custom_bad),
        "legacy_bad": sorted(legacy_bad),
        "custom_bad": sorted(custom_bad),
    }


def build_outputs(summary: dict[str, Any], rows: list[dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    grouped = group_by_case(rows)
    sets = case_sets(summary, grouped)
    result_rows: list[dict[str, Any]] = []
    for delta_type in ("only_custom_bad", "only_legacy_bad", "shared_bad"):
        for case_id in sets[delta_type]:
            result_rows.append(comparison_row(case_id, delta_type, grouped.get(case_id, {})))

    only_custom_rows = [row for row in result_rows if row["delta_type"] == "only_custom_bad"]
    root_counter: Counter[str] = Counter()
    for row in only_custom_rows:
        root_counter.update(row["root_causes"])

    output_summary = {
        "phase": "7E-4C_answer_source_alignment_diagnosis",
        "case_count": summary.get("case_count", len(grouped)),
        "request_count": summary.get("request_count", len(rows)),
        "legacy_bad_count": len(sets["legacy_bad"]),
        "custom_bad_count": len(sets["custom_bad"]),
        "shared_bad_count": len(sets["shared_bad"]),
        "only_custom_bad_count": len(sets["only_custom_bad"]),
        "only_custom_bad_case_ids": sets["only_custom_bad"],
        "only_legacy_bad_count": len(sets["only_legacy_bad"]),
        "only_legacy_bad_case_ids": sets["only_legacy_bad"],
        "same_sources_answer_diff_count": root_counter["same_sources_answer_diff"],
        "source_order_diff_count": root_counter["source_order_diff"],
        "source_serialization_diff_count": root_counter["source_serialization_diff"],
        "source_missing_or_doc_type_gap_count": root_counter["source_missing_or_doc_type_gap"],
        "prompt_profile_diff_count": root_counter["prompt_profile_diff"],
        "suspected_stochastic_or_synthesis_diff_count": root_counter[
            "suspected_stochastic_or_synthesis_diff"
        ],
        "only_custom_root_cause_distribution": dict(sorted(root_counter.items())),
        "custom_graph_error_count": summary.get("custom_graph", {}).get("error_count", 0),
        "legacy_error_count": summary.get("legacy", {}).get("error_count", 0),
        "custom_graph_timeout_count": summary.get("custom_graph", {}).get("timeout_count", 0),
        "legacy_timeout_count": summary.get("legacy", {}).get("timeout_count", 0),
        "sources_persisted_all_only_custom": all(
            row["custom_sources_persisted"] for row in only_custom_rows
        ),
        "calls_llm": False,
        "runs_full_240_case": False,
        "writes_chroma": False,
        "recommend_prompt_alignment": root_counter["same_sources_answer_diff"] > 0
        or root_counter["suspected_stochastic_or_synthesis_diff"] > 0,
        "recommend_source_ordering_fix": root_counter["source_order_diff"] > 0,
        "recommend_data_or_chunk_optimization": root_counter["source_missing_or_doc_type_gap"] > 0,
        "recommend_full_240_with_topk10": False,
    }
    return output_summary, result_rows


def write_doc(path: Path, summary: dict[str, Any]) -> None:
    root_lines = "\n".join(
        f"- {key}: {value}" for key, value in summary["only_custom_root_cause_distribution"].items()
    )
    text = f"""# Phase 7E Answer / Source Alignment Diagnosis

## Scope

This document summarizes an offline diagnosis of Phase 7E-4B answer/source persistence results. It reads JSONL artifacts only. It does not call an endpoint, does not call an LLM, does not run a full 240-case evaluation, and does not write Chroma.

## Overview

- case_count: {summary["case_count"]}
- request_count: {summary["request_count"]}
- legacy_bad: {summary["legacy_bad_count"]}
- custom_graph_bad: {summary["custom_bad_count"]}
- shared_bad: {summary["shared_bad_count"]}
- only_custom_bad: {summary["only_custom_bad_count"]}
- only_legacy_bad: {summary["only_legacy_bad_count"]}
- custom_graph_error_count: {summary["custom_graph_error_count"]}
- legacy_error_count: {summary["legacy_error_count"]}

## Delta Cases

- only_custom_bad case ids: {", ".join(summary["only_custom_bad_case_ids"]) or "none"}
- only_legacy_bad case ids: {", ".join(summary["only_legacy_bad_case_ids"]) or "none"}

## Only-Custom Root Cause Distribution

{root_lines}

## Alignment Signals

- same_sources_answer_diff_count: {summary["same_sources_answer_diff_count"]}
- source_order_diff_count: {summary["source_order_diff_count"]}
- source_serialization_diff_count: {summary["source_serialization_diff_count"]}
- source_missing_or_doc_type_gap_count: {summary["source_missing_or_doc_type_gap_count"]}
- prompt_profile_diff_count: {summary["prompt_profile_diff_count"]}
- suspected_stochastic_or_synthesis_diff_count: {summary["suspected_stochastic_or_synthesis_diff_count"]}

## Interpretation

custom_graph has no error or timeout in this delta run, but it still does not match legacy on bad-case count. If same-source answer differences dominate, the next diagnostic direction should be answer synthesis behavior. If source order differences dominate, source ordering should be inspected. If source/doc-type gaps dominate, the issue should move back to retrieval/data/chunk coverage.

This diagnosis does not claim custom_graph is better than legacy and does not justify a full 240-case top_k=10 run by itself.
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def main() -> int:
    args = parse_args()
    results_path = resolve_path(args.results)
    summary_path = resolve_path(args.summary)
    output_json = resolve_path(args.output_json)
    output_jsonl = resolve_path(args.output_jsonl)
    output_md = args.output_md

    if not results_path.exists() or not summary_path.exists():
        print("Phase 7E-4B results not found. Run HPC answer/source persistence eval first.")
        return 0

    source_summary = read_json(summary_path)
    source_rows = read_jsonl(results_path)
    output_summary, result_rows = build_outputs(source_summary, source_rows)
    output_summary["input_results"] = str(results_path)
    output_summary["input_summary"] = str(summary_path)
    output_summary["output_results"] = str(output_jsonl)
    output_summary["output_markdown"] = str(output_md)

    write_json(output_json, output_summary)
    write_jsonl(output_jsonl, result_rows)
    write_doc(output_md, output_summary)
    print(json.dumps(output_summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
