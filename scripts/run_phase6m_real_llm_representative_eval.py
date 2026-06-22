#!/usr/bin/env python3
"""Prepare or run a bounded fake/DeepSeek representative endpoint evaluation."""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CASES = ROOT / "data" / "knowledge_base" / "evaluation" / "phase6m_representative_cases.jsonl"
DEFAULT_RESULTS = (
    ROOT
    / "data"
    / "knowledge_base"
    / "evaluation"
    / "phase6m_real_llm_representative_eval_results.jsonl"
)
DEFAULT_SUMMARY = (
    ROOT
    / "data"
    / "knowledge_base"
    / "evaluation"
    / "phase6m_real_llm_representative_eval_summary.json"
)
MODEL_BY_PROVIDER = {"fake": "fake", "deepseek": "deepseek-chat"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run 5-10 representative cases against an already running enterprise API."
    )
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--endpoint", default="/enterprise/agent/query")
    parser.add_argument("--provider", choices=("fake", "deepseek", "both"), default="fake")
    parser.add_argument("--endpoint-mode", choices=("legacy", "custom_graph"), default="legacy")
    parser.add_argument("--limit", type=int, default=8)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Send API requests. Without this flag the script only writes a safe plan summary.",
    )
    return parser.parse_args()


def load_cases(path: Path, limit: int) -> list[dict[str, Any]]:
    if not 1 <= limit <= 10:
        raise ValueError("--limit must be between 1 and 10")
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    selected = rows[:limit]
    if not selected:
        raise ValueError("No representative cases were loaded")
    return selected


def providers_for(value: str) -> list[str]:
    return ["fake", "deepseek"] if value == "both" else [value]


def case_turns(case: dict[str, Any]) -> list[dict[str, Any]]:
    turns = case.get("turns")
    if isinstance(turns, list) and turns:
        return [turn for turn in turns if isinstance(turn, dict)]
    return [{"query": case["query"], "expected_keywords": case.get("expected_keywords", [])}]


def deepseek_key_available() -> bool:
    return bool(os.environ.get("DEEPSEEK_API_KEY", "").strip())


def keyword_notes(answer: str, expected_keywords: list[str]) -> str:
    folded = answer.casefold()
    hits = [term for term in expected_keywords if str(term).casefold() in folded]
    return (
        f"expected_keyword_hits={len(hits)}/{len(expected_keywords)}; "
        "manual_answer_quality_review_required=true"
    )


def planned_row(
    case: dict[str, Any], provider: str, endpoint_mode: str, reason: str
) -> dict[str, Any]:
    return {
        "case_id": case["case_id"],
        "query_type": case["query_type"],
        "provider": provider,
        "endpoint_mode": endpoint_mode,
        "status": "skipped",
        "skipped_due_to_missing_key": provider == "deepseek" and reason == "missing_key",
        "skip_reason": reason,
        "answer_non_empty": False,
        "source_count": 0,
        "grounding_status": None,
        "graph_debug_present": False,
        "answer_quality_notes": "not_evaluated",
        "latency_ms": 0.0,
        "error": None,
        "timeout": False,
    }


def execute_case(
    case: dict[str, Any], provider: str, args: argparse.Namespace
) -> dict[str, Any]:
    endpoint_url = args.base_url.rstrip("/") + "/" + args.endpoint.lstrip("/")
    final_payload: dict[str, Any] = {}
    total_latency_ms = 0.0
    expected_keywords: list[str] = []
    try:
        for turn in case_turns(case):
            expected_keywords = [str(term) for term in turn.get("expected_keywords", [])]
            payload = {
                "query": turn["query"],
                "session_id": case.get("session_id"),
                "top_k": int(case.get("top_k", 5)),
                "return_sources": bool(case.get("return_sources", True)),
                "model": MODEL_BY_PROVIDER[provider],
            }
            started = time.perf_counter()
            response = requests.post(endpoint_url, json=payload, timeout=args.timeout)
            total_latency_ms += (time.perf_counter() - started) * 1000
            response.raise_for_status()
            final_payload = response.json()
            if not isinstance(final_payload, dict):
                raise ValueError("Endpoint response root is not an object")

        answer = str(final_payload.get("answer") or "").strip()
        sources = final_payload.get("sources")
        sources = sources if isinstance(sources, list) else []
        verifier_debug = final_payload.get("verifier_debug")
        verifier_debug = verifier_debug if isinstance(verifier_debug, dict) else {}
        graph_debug = final_payload.get("graph_debug")
        graph_debug = graph_debug if isinstance(graph_debug, dict) else {}
        model_debug = final_payload.get("model_debug")
        model_debug = model_debug if isinstance(model_debug, dict) else {}
        actual_mode = str(model_debug.get("agent_graph_mode") or "legacy")
        mode_matches = actual_mode == args.endpoint_mode
        return {
            "case_id": case["case_id"],
            "query_type": case["query_type"],
            "provider": provider,
            "endpoint_mode": actual_mode,
            "endpoint_mode_matches": mode_matches,
            "status": "completed" if mode_matches else "completed_with_mode_mismatch",
            "skipped_due_to_missing_key": False,
            "answer_non_empty": bool(answer),
            "answer_preview": answer[:500],
            "source_count": len(sources),
            "grounding_status": verifier_debug.get("grounding_status"),
            "graph_debug_present": bool(graph_debug),
            "answer_quality_notes": keyword_notes(answer, expected_keywords),
            "latency_ms": round(total_latency_ms, 2),
            "error": None,
            "timeout": False,
        }
    except requests.Timeout:
        error = "request_timeout"
        timeout = True
    except Exception as exc:  # noqa: BLE001
        error = f"{type(exc).__name__}: {str(exc)[:200]}"
        timeout = False
    return {
        "case_id": case["case_id"],
        "query_type": case["query_type"],
        "provider": provider,
        "endpoint_mode": args.endpoint_mode,
        "status": "failed",
        "skipped_due_to_missing_key": False,
        "answer_non_empty": False,
        "source_count": 0,
        "grounding_status": None,
        "graph_debug_present": False,
        "answer_quality_notes": "not_evaluated",
        "latency_ms": round(total_latency_ms, 2),
        "error": error,
        "timeout": timeout,
    }


def build_summary(
    cases: list[dict[str, Any]], rows: list[dict[str, Any]], args: argparse.Namespace
) -> dict[str, Any]:
    completed = [row for row in rows if str(row["status"]).startswith("completed")]
    return {
        "phase": "6M_real_llm_representative_eval",
        "case_count": len(cases),
        "result_count": len(rows),
        "endpoint_mode_requested": args.endpoint_mode,
        "execute_requested": args.execute,
        "runs_fake_model": any(row["provider"] == "fake" for row in completed),
        "runs_deepseek": any(row["provider"] == "deepseek" for row in completed),
        "skipped_deepseek_reason": next(
            (
                row["skip_reason"]
                for row in rows
                if row["provider"] == "deepseek" and row["status"] == "skipped"
            ),
            None,
        ),
        "completed_count": len(completed),
        "answer_non_empty_count": sum(bool(row["answer_non_empty"]) for row in completed),
        "graph_debug_present_count": sum(bool(row["graph_debug_present"]) for row in completed),
        "error_count": sum(row["status"] == "failed" for row in rows),
        "timeout_count": sum(bool(row["timeout"]) for row in rows),
        "calls_real_llm": any(row["provider"] == "deepseek" for row in completed),
        "writes_chroma": False,
        "runs_240_case": False,
        "runs_benchmark": False,
        "recommended_next_step": (
            "Run in an authorized environment with a DeepSeek key for 5-10 representative cases."
        ),
    }


def main() -> int:
    args = parse_args()
    cases = load_cases(args.cases, args.limit)
    rows: list[dict[str, Any]] = []
    for provider in providers_for(args.provider):
        if not args.execute:
            rows.extend(
                planned_row(case, provider, args.endpoint_mode, "not_requested") for case in cases
            )
        elif provider == "deepseek" and not deepseek_key_available():
            rows.extend(
                planned_row(case, provider, args.endpoint_mode, "missing_key") for case in cases
            )
        else:
            rows.extend(execute_case(case, provider, args) for case in cases)

    summary = build_summary(cases, rows, args)
    args.results.parent.mkdir(parents=True, exist_ok=True)
    args.results.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
    )
    args.summary.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["error_count"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
