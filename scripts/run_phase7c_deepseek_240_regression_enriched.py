"""Phase 7C enriched endpoint regression runner.

This script prepares richer per-case instrumentation for a future DeepSeek 240-case
legacy-vs-custom_graph run. It does not write Chroma and it only calls endpoints when
--execute is provided explicitly.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
EVAL_DIR = ROOT / "data" / "knowledge_base" / "evaluation"
DEFAULT_CASES = EVAL_DIR / "phase6d_agent_api_cases.jsonl"
DEFAULT_RESULTS = EVAL_DIR / "phase7c_enriched_deepseek_240_results.jsonl"
DEFAULT_SUMMARY = EVAL_DIR / "phase7c_enriched_deepseek_240_summary.json"

DEFAULT_LEGACY_URL = "http://127.0.0.1:8011/enterprise/agent/query"
DEFAULT_CUSTOM_GRAPH_URL = "http://127.0.0.1:8012/enterprise/agent/query"
ANSWER_PREVIEW_CHARS = 800
SOURCE_PREVIEW_CHARS = 500
MAX_PERSISTED_SOURCES = 10


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run enriched Phase 7C endpoint regression.")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--legacy-url", default=DEFAULT_LEGACY_URL)
    parser.add_argument("--custom-graph-url", default=DEFAULT_CUSTOM_GRAPH_URL)
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument("--limit-cases", type=int, default=0)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--execute", action="store_true")
    return parser.parse_args()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def source_values(source: dict[str, Any]) -> list[str]:
    metadata = source.get("metadata") if isinstance(source.get("metadata"), dict) else {}
    values = [
        source.get("source_id"),
        source.get("source"),
        source.get("doc_id"),
        source.get("title"),
        source.get("doc_type"),
        source.get("section_path"),
        source.get("source_url"),
        source.get("chunk_id"),
        metadata.get("source_id"),
        metadata.get("doc_id"),
        metadata.get("title"),
        metadata.get("doc_type"),
        metadata.get("section_path"),
        metadata.get("source_url"),
        metadata.get("chunk_id"),
    ]
    return [str(value) for value in values if value not in (None, "", "unknown")]


def source_text(source: dict[str, Any]) -> str:
    metadata = source.get("metadata") if isinstance(source.get("metadata"), dict) else {}
    values = source_values(source)
    values.extend(
        str(value)
        for value in [
            source.get("content_preview"),
            source.get("preview"),
            source.get("content"),
            source.get("text"),
            metadata.get("content_preview"),
            metadata.get("preview"),
        ]
        if value
    )
    return " ".join(values).lower()


def text_hash(value: str) -> str | None:
    if not value:
        return None
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def first_text_value(*values: Any) -> str | None:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value
    return None


def source_field(source: dict[str, Any], *keys: str) -> Any:
    metadata = source.get("metadata") if isinstance(source.get("metadata"), dict) else {}
    for key in keys:
        value = source.get(key)
        if value not in (None, ""):
            return value
        value = metadata.get(key)
        if value not in (None, ""):
            return value
    return None


def source_content(source: dict[str, Any]) -> str:
    metadata = source.get("metadata") if isinstance(source.get("metadata"), dict) else {}
    return first_text_value(
        source.get("content_preview"),
        source.get("preview"),
        source.get("content"),
        source.get("text"),
        metadata.get("content_preview"),
        metadata.get("preview"),
        metadata.get("content"),
        metadata.get("text"),
    ) or ""


def source_previews(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    previews: list[dict[str, Any]] = []
    for rank, source in enumerate(sources[:MAX_PERSISTED_SOURCES], start=1):
        content = source_content(source)
        previews.append(
            {
                "rank": rank,
                "source_id": source_field(source, "source_id", "doc_id", "source"),
                "source_url": source_field(source, "source_url"),
                "title": source_field(source, "title"),
                "doc_type": source_field(source, "doc_type"),
                "chunk_id": source_field(source, "chunk_id"),
                "score": source_field(source, "score", "relevance_score", "distance"),
                "content_preview": content[:SOURCE_PREVIEW_CHARS],
                "content_sha256": text_hash(content),
            }
        )
    return previews


def sequence_from_sources(sources: list[dict[str, Any]], *keys: str) -> list[Any]:
    return [source_field(source, *keys) for source in sources[:MAX_PERSISTED_SOURCES]]


def prompt_profile(mode: str, top_k: int) -> dict[str, Any]:
    answer_synthesis_profile = (
        "keyword_coverage_v1" if mode == "custom_graph" else "legacy_default"
    )
    return {
        "mode": mode,
        "agent_graph_mode": "legacy" if mode == "legacy" else "custom_graph",
        "answer_synthesis_profile": answer_synthesis_profile,
        "answer_synthesis_mode": answer_synthesis_profile,
        "planner_mode": os.getenv("ENTERPRISE_PLANNER_MODE"),
        "multi_hop_mode": os.getenv("ENTERPRISE_MULTI_HOP_MODE"),
        "judge_mode": os.getenv("ENTERPRISE_LLM_JUDGE_MODE")
        or os.getenv("ENTERPRISE_JUDGE_MODE"),
        "evidence_verifier_mode": os.getenv("ENTERPRISE_EVIDENCE_VERIFIER_MODE"),
        "top_k": top_k,
    }


def contains_any(text: str, needles: list[str]) -> bool:
    if not needles:
        return True
    low = text.lower()
    return any(str(needle).lower() in low for needle in needles if str(needle).strip())


def check_source_hit(sources: list[dict[str, Any]], expected_source_id: str | None) -> bool:
    if not expected_source_id:
        return True
    expected = str(expected_source_id).lower()
    return any(expected in " ".join(source_values(source)).lower() for source in sources)


def check_doc_type_hit(sources: list[dict[str, Any]], expected_doc_type: str | None) -> bool:
    if not expected_doc_type:
        return True
    expected = str(expected_doc_type).lower()
    for source in sources:
        metadata = source.get("metadata") if isinstance(source.get("metadata"), dict) else {}
        doc_type = source.get("doc_type") or metadata.get("doc_type")
        if str(doc_type or "").lower() == expected:
            return True
    return False


def check_keyword_hit(
    *,
    answer: str,
    sources: list[dict[str, Any]],
    expected_keywords: list[str],
) -> bool:
    if not expected_keywords:
        return True
    text = (answer + " " + " ".join(source_text(source) for source in sources)).lower()
    return all(str(keyword).lower() in text for keyword in expected_keywords if str(keyword).strip())


def bad_reasons(row: dict[str, Any]) -> list[str]:
    reasons: list[str] = []
    if row["error"]:
        reasons.append("runtime_error")
    if row["timeout"]:
        reasons.append("timeout")
    if not row["schema_valid"]:
        reasons.append("schema_invalid")
    if not row["answer_non_empty"]:
        reasons.append("empty_answer")
    if not row["source_hit"]:
        reasons.append("source_miss")
    if not row["doc_type_hit"]:
        reasons.append("doc_type_miss")
    if not row["keyword_hit"]:
        reasons.append("keyword_miss")
    if row["mode"] == "custom_graph":
        if not row["graph_debug_present"]:
            reasons.append("graph_debug_missing")
        if row["graph_debug"].get("graph_mode") != "custom_graph":
            reasons.append("graph_mode_not_custom_graph")
        if row["nodes_executed_count"] <= 0:
            reasons.append("nodes_executed_missing")
        if not row["planner_present"]:
            reasons.append("planner_debug_missing")
        if not row["judge_present"] and row["query_type"] not in {
            "ambiguous_query",
            "unsupported_query",
            "negative_banned_source",
        }:
            reasons.append("judge_debug_missing")
    return reasons


def calibrated_reasons(row: dict[str, Any]) -> list[str]:
    # Keep the first enriched calibrator conservative and transparent. It persists the
    # full set of case IDs and explicit reasons so later analysis no longer needs proxy IDs.
    return bad_reasons(row)


def post_json(url: str, payload: dict[str, Any], timeout: float) -> tuple[int, dict[str, Any], float, str | None]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            latency_ms = (time.perf_counter() - start) * 1000
            return response.status, json.loads(raw or "{}"), latency_ms, None
    except urllib.error.HTTPError as exc:
        latency_ms = (time.perf_counter() - start) * 1000
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw or "{}")
        except json.JSONDecodeError:
            payload = {"raw_error": raw[:500]}
        return exc.code, payload, latency_ms, f"http_error_{exc.code}"
    except TimeoutError as exc:
        latency_ms = (time.perf_counter() - start) * 1000
        return 0, {}, latency_ms, f"timeout: {exc}"
    except OSError as exc:
        latency_ms = (time.perf_counter() - start) * 1000
        error_text = str(exc)
        if "timed out" in error_text.lower():
            return 0, {}, latency_ms, f"timeout: {error_text}"
        return 0, {}, latency_ms, error_text[:300]


def normalized_case(raw: dict[str, Any], index: int) -> dict[str, Any]:
    return {
        "case_id": str(raw.get("case_id") or raw.get("id") or f"case_{index:03d}"),
        "query": str(raw.get("query") or raw.get("question") or ""),
        "query_type": str(raw.get("query_type") or "unknown"),
        "expected_source_id": raw.get("expected_source_id"),
        "expected_doc_type": raw.get("expected_doc_type"),
        "expected_keywords": list(raw.get("expected_keywords") or raw.get("keywords") or []),
        "session_id": raw.get("session_id"),
    }


def extract_planner_type(planner_debug: dict[str, Any], query_type: str) -> str | None:
    for key in ("planner_type", "query_complexity", "query_type"):
        value = planner_debug.get(key)
        if value:
            return str(value)
    if query_type == "multi_hop_lookup":
        return "multi_hop"
    return None


def build_result(
    *,
    case: dict[str, Any],
    mode: str,
    payload: dict[str, Any],
    status_code: int,
    latency_ms: float,
    error: str | None,
    top_k: int,
) -> dict[str, Any]:
    answer = str(payload.get("answer") or "")
    sources = payload.get("sources") if isinstance(payload.get("sources"), list) else []
    retrieval_debug = payload.get("retrieval_debug") if isinstance(payload.get("retrieval_debug"), dict) else {}
    verifier_debug = payload.get("verifier_debug") if isinstance(payload.get("verifier_debug"), dict) else {}
    planner_debug = payload.get("planner_debug") if isinstance(payload.get("planner_debug"), dict) else {}
    judge_debug = payload.get("judge_debug") if isinstance(payload.get("judge_debug"), dict) else {}
    graph_debug = payload.get("graph_debug") if isinstance(payload.get("graph_debug"), dict) else {}
    nodes = graph_debug.get("nodes_executed") if isinstance(graph_debug.get("nodes_executed"), list) else []
    planner_type = extract_planner_type(planner_debug, case["query_type"])
    requires_multi_hop = bool(planner_debug.get("requires_multi_hop")) or case["query_type"] == "multi_hop_lookup"
    row: dict[str, Any] = {
        "case_id": case["case_id"],
        "mode": mode,
        "query": case["query"],
        "query_type": case["query_type"],
        "expected_source_id": case["expected_source_id"],
        "expected_doc_type": case["expected_doc_type"],
        "expected_keywords": case["expected_keywords"],
        "answer_non_empty": bool(answer.strip()),
        "answer_preview": answer[:ANSWER_PREVIEW_CHARS],
        "answer_chars": len(answer),
        "answer_sha256": text_hash(answer),
        "schema_valid": all(key in payload for key in ("answer", "sources", "retrieval_debug")),
        "sources_persisted": bool(sources),
        "sources_persisted_reason": "sources_present" if sources else "response_sources_empty_or_missing",
        "source_count": len(sources),
        "source_previews": source_previews(sources),
        "source_id_sequence": sequence_from_sources(sources, "source_id", "doc_id", "source"),
        "doc_type_sequence": sequence_from_sources(sources, "doc_type"),
        "chunk_id_sequence": sequence_from_sources(sources, "chunk_id"),
        "source_hit": check_source_hit(sources, case["expected_source_id"]),
        "doc_type_hit": check_doc_type_hit(sources, case["expected_doc_type"]),
        "keyword_hit": check_keyword_hit(
            answer=answer,
            sources=sources,
            expected_keywords=case["expected_keywords"],
        ),
        "bad_case": False,
        "bad_case_reasons": [],
        "calibrated_bad_case": False,
        "calibrated_bad_case_reasons": [],
        "latency_ms": round(latency_ms, 2),
        "http_status": status_code,
        "error": error,
        "timeout": bool(error and "timeout" in error.lower()),
        "retrieval_debug": retrieval_debug,
        "verifier_debug": verifier_debug,
        "planner_debug": planner_debug,
        "judge_debug": judge_debug,
        "graph_debug": graph_debug,
        "nodes_executed": nodes,
        "planner_type": planner_type,
        "requires_multi_hop": requires_multi_hop,
        "multi_hop_enabled": "multi_hop_retriever" in nodes,
        "judge_verdict": judge_debug.get("verdict") or judge_debug.get("status"),
        "prompt_profile": prompt_profile(mode, top_k),
        "graph_debug_present": bool(graph_debug),
        "graph_mode": graph_debug.get("graph_mode"),
        "nodes_executed_count": len(nodes),
        "planner_present": bool(planner_debug),
        "judge_present": bool(judge_debug),
        "writes_chroma": bool(graph_debug.get("writes_chroma", False)),
    }
    row["bad_case_reasons"] = bad_reasons(row)
    row["bad_case"] = bool(row["bad_case_reasons"])
    row["calibrated_bad_case_reasons"] = calibrated_reasons(row)
    row["calibrated_bad_case"] = bool(row["calibrated_bad_case_reasons"])
    return row


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    by_mode = {"legacy": [], "custom_graph": []}
    for row in rows:
        by_mode.setdefault(str(row["mode"]), []).append(row)

    def ids(mode: str, key: str) -> list[str]:
        return sorted(str(row["case_id"]) for row in by_mode.get(mode, []) if row.get(key))

    legacy_bad = set(ids("legacy", "bad_case"))
    custom_bad = set(ids("custom_graph", "bad_case"))
    legacy_cal = set(ids("legacy", "calibrated_bad_case"))
    custom_cal = set(ids("custom_graph", "calibrated_bad_case"))

    def mode_summary(mode: str) -> dict[str, Any]:
        mode_rows = by_mode.get(mode, [])
        planner = Counter(str(row.get("planner_type") or "none") for row in mode_rows)
        judge = Counter(str(row.get("judge_verdict") or "none") for row in mode_rows)
        judge_bad = Counter(
            str(row.get("judge_verdict") or "none")
            for row in mode_rows
            if row.get("calibrated_bad_case")
        )
        return {
            "case_count": len(mode_rows),
            "bad_case_count": sum(bool(row.get("bad_case")) for row in mode_rows),
            "calibrated_bad_case_count": sum(
                bool(row.get("calibrated_bad_case")) for row in mode_rows
            ),
            "source_miss_count": sum(row.get("source_hit") is False for row in mode_rows),
            "doc_type_miss_count": sum(row.get("doc_type_hit") is False for row in mode_rows),
            "source_and_doc_type_miss_count": sum(
                row.get("source_hit") is False and row.get("doc_type_hit") is False
                for row in mode_rows
            ),
            "keyword_miss_count": sum(row.get("keyword_hit") is False for row in mode_rows),
            "multi_hop_enabled_count": sum(bool(row.get("multi_hop_enabled")) for row in mode_rows),
            "multi_hop_bad_case_count": sum(
                bool(row.get("multi_hop_enabled")) and bool(row.get("calibrated_bad_case"))
                for row in mode_rows
            ),
            "planner_type_distribution": dict(planner),
            "judge_verdict_distribution": dict(judge),
            "judge_bad_case_distribution": dict(judge_bad),
            "error_count": sum(bool(row.get("error")) for row in mode_rows),
            "timeout_count": sum(bool(row.get("timeout")) for row in mode_rows),
        }

    return {
        "phase": "7C_enriched_deepseek_240_regression",
        "case_count": max(len(by_mode.get("legacy", [])), len(by_mode.get("custom_graph", []))),
        "request_count": len(rows),
        "legacy": mode_summary("legacy"),
        "custom_graph": mode_summary("custom_graph"),
        "legacy_bad_case_ids": sorted(legacy_bad),
        "custom_graph_bad_case_ids": sorted(custom_bad),
        "legacy_calibrated_bad_case_ids": sorted(legacy_cal),
        "custom_graph_calibrated_bad_case_ids": sorted(custom_cal),
        "shared_bad_case_ids": sorted(legacy_bad & custom_bad),
        "only_legacy_bad_case_ids": sorted(legacy_bad - custom_bad),
        "only_custom_graph_bad_case_ids": sorted(custom_bad - legacy_bad),
        "shared_calibrated_bad_case_ids": sorted(legacy_cal & custom_cal),
        "only_legacy_calibrated_bad_case_ids": sorted(legacy_cal - custom_cal),
        "only_custom_graph_calibrated_bad_case_ids": sorted(custom_cal - legacy_cal),
        "calls_real_llm": True,
        "writes_chroma": False,
        "runs_240_case": True,
        "runs_benchmark": False,
        "note": "This summary is produced only when --execute is used against running endpoints.",
    }


def write_skipped_summary(args: argparse.Namespace, cases: list[dict[str, Any]]) -> None:
    summary = {
        "phase": "7C_enriched_deepseek_240_regression",
        "case_count": len(cases),
        "request_count": 0,
        "skipped": True,
        "skipped_reason": "missing --execute",
        "results_path": str(args.results),
        "summary_path": str(args.summary),
        "calls_real_llm": False,
        "writes_chroma": False,
        "runs_240_case": False,
        "runs_benchmark": False,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


def main() -> int:
    args = parse_args()
    raw_cases = load_jsonl(args.cases)
    cases = [normalized_case(raw, index) for index, raw in enumerate(raw_cases, start=1)]
    if args.limit_cases > 0:
        cases = cases[: args.limit_cases]
    if not args.execute:
        write_skipped_summary(args, cases)
        return 0

    rows: list[dict[str, Any]] = []
    urls = {"legacy": args.legacy_url, "custom_graph": args.custom_graph_url}
    for case in cases:
        for mode, url in urls.items():
            request_payload = {
                "query": case["query"],
                "session_id": case["session_id"] or f"phase7c-{mode}-{case['case_id']}",
                "top_k": args.top_k,
                "return_sources": True,
            }
            status, payload, latency_ms, error = post_json(url, request_payload, args.timeout)
            rows.append(
                build_result(
                    case=case,
                    mode=mode,
                    payload=payload,
                    status_code=status,
                    latency_ms=latency_ms,
                    error=error,
                    top_k=args.top_k,
                )
            )

    args.results.parent.mkdir(parents=True, exist_ok=True)
    args.results.write_text(
        "\n".join(json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows) + "\n",
        encoding="utf-8",
    )
    summary = summarize(rows)
    args.summary.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
