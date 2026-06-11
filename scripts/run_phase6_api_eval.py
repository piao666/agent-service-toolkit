from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any

try:
    from datetime import UTC as DATETIME_UTC
except ImportError:  # pragma: no cover - Python 3.10 compatibility.
    DATETIME_UTC = timezone.utc  # noqa: UP017


ROOT_DIR = Path(__file__).resolve().parents[1]
EVAL_DIR = ROOT_DIR / "data" / "knowledge_base" / "evaluation"
DEFAULT_CASES_PATH = EVAL_DIR / "phase6_qa_cases.jsonl"
DEFAULT_RESULTS_PATH = EVAL_DIR / "phase6_api_eval_results.jsonl"
DEFAULT_SUMMARY_PATH = EVAL_DIR / "phase6_api_eval_summary.json"
ANSWER_PREVIEW_CHARS = 200


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Phase 6C lightweight endpoint evaluation.")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--max-cases", type=int, default=10)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS_PATH)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY_PATH)
    return parser.parse_args()


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _as_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if item is not None]


def _answer_preview(answer: str) -> str:
    collapsed = " ".join(answer.split())
    return collapsed[:ANSWER_PREVIEW_CHARS]


def _request_json(url: str, payload: dict[str, Any] | None, timeout: float) -> tuple[int, dict[str, Any]]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="GET" if payload is None else "POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        body = response.read().decode("utf-8")
        return int(response.status), json.loads(body) if body else {}


def _health_error(base_url: str, timeout: float) -> str | None:
    try:
        status_code, _payload = _request_json(f"{base_url.rstrip('/')}/health", None, timeout)
    except (OSError, TimeoutError, urllib.error.URLError, urllib.error.HTTPError):
        return "local_service_unavailable"
    if status_code >= 400:
        return "local_service_unavailable"
    return None


def _skipped_rows(cases: list[dict[str, Any]], reason: str) -> list[dict[str, Any]]:
    return [
        {
            "case_id": case.get("case_id"),
            "query": case.get("query"),
            "category": case.get("category"),
            "api_eval_status": "skipped",
            "error_summary": reason,
            "status_code": None,
            "answer_length": 0,
            "answer_preview": "",
            "source_count": 0,
            "returned_source_ids": [],
            "whether_expected_source_hit": False,
            "whether_expected_keywords_in_answer": False,
            "fallback_triggered": None,
            "latency_ms": None,
        }
        for case in cases
    ]


def _evaluate_case(case: dict[str, Any], base_url: str, timeout: float) -> dict[str, Any]:
    expected_sources = set(_as_list(case.get("expected_source_ids")))
    expected_keywords = _as_list(case.get("expected_keywords"))
    payload = {
        "query": case.get("query"),
        "session_id": f"phase6c-{case.get('case_id')}",
        "top_k": int(case.get("top_k") or 5),
        "return_sources": True,
    }
    started = time.perf_counter()
    try:
        status_code, response_payload = _request_json(
            f"{base_url.rstrip('/')}/enterprise/agent/query",
            payload,
            timeout,
        )
    except (OSError, TimeoutError, urllib.error.URLError, urllib.error.HTTPError) as exc:
        return {
            "case_id": case.get("case_id"),
            "query": case.get("query"),
            "category": case.get("category"),
            "api_eval_status": "error",
            "error_summary": exc.__class__.__name__,
            "status_code": None,
            "answer_length": 0,
            "answer_preview": "",
            "source_count": 0,
            "returned_source_ids": [],
            "whether_expected_source_hit": False,
            "whether_expected_keywords_in_answer": False,
            "fallback_triggered": None,
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
        }

    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    answer = str(response_payload.get("answer") or "")
    sources = response_payload.get("sources") if isinstance(response_payload.get("sources"), list) else []
    returned_source_ids = [
        str(source.get("source_id") or source.get("source") or "")
        for source in sources
        if isinstance(source, dict)
    ]
    fallback = response_payload.get("fallback")
    fallback_triggered = bool(fallback.get("triggered")) if isinstance(fallback, dict) else False
    answer_lower = answer.lower()
    return {
        "case_id": case.get("case_id"),
        "query": case.get("query"),
        "category": case.get("category"),
        "api_eval_status": "completed" if status_code < 400 else "error",
        "error_summary": None if status_code < 400 else f"status_{status_code}",
        "status_code": status_code,
        "answer_length": len(answer),
        "answer_preview": _answer_preview(answer),
        "source_count": len(sources),
        "returned_source_ids": returned_source_ids,
        "whether_expected_source_hit": bool(expected_sources & set(returned_source_ids)),
        "whether_expected_keywords_in_answer": any(
            keyword.lower() in answer_lower for keyword in expected_keywords
        )
        if expected_keywords
        else True,
        "fallback_triggered": fallback_triggered,
        "latency_ms": response_payload.get("latency_ms") or elapsed_ms,
        "model_debug": response_payload.get("model_debug") if isinstance(response_payload, dict) else {},
    }


def _rate(rows: list[dict[str, Any]], key: str) -> float:
    if not rows:
        return 0.0
    return round(sum(1 for row in rows if row.get(key)) / len(rows), 4)


def _summary(rows: list[dict[str, Any]], selected_count: int, reason: str | None) -> dict[str, Any]:
    completed = [row for row in rows if row.get("api_eval_status") == "completed"]
    latencies = [float(row["latency_ms"]) for row in completed if row.get("latency_ms") is not None]
    return {
        "generated_at": datetime.now(DATETIME_UTC).isoformat(),
        "phase": "6C",
        "eval_type": "api_endpoint",
        "api_eval_status": "completed" if completed else "skipped",
        "skip_reason": reason,
        "case_count_selected": selected_count,
        "case_count_run": len(completed),
        "skipped_count": sum(1 for row in rows if row.get("api_eval_status") == "skipped"),
        "error_count": sum(1 for row in rows if row.get("api_eval_status") == "error"),
        "expected_source_hit_rate": _rate(completed, "whether_expected_source_hit"),
        "expected_keyword_hit_rate": _rate(completed, "whether_expected_keywords_in_answer"),
        "fallback_count": sum(1 for row in completed if row.get("fallback_triggered")),
        "avg_latency_ms": round(mean(latencies), 2) if latencies else None,
        "calls_llm": bool(completed),
        "end_to_end_agent_eval_passed": False,
        "writes_chroma": False,
        "expands_ingestion_scope": False,
        "stores_full_answer": False,
    }


def main() -> None:
    args = parse_args()
    cases = [
        case
        for case in _load_jsonl(args.cases)
        if "api" in _as_list(case.get("eval_modes")) and not bool(case.get("negative"))
    ][: args.max_cases]
    health_error = _health_error(args.base_url, args.timeout)
    if health_error:
        rows = _skipped_rows(cases, health_error)
        summary = _summary(rows, len(cases), health_error)
    else:
        rows = [_evaluate_case(case, args.base_url, args.timeout) for case in cases]
        summary = _summary(rows, len(cases), None)

    _write_jsonl(args.results, rows)
    _write_json(args.summary, summary)
    output = json.dumps(summary, ensure_ascii=False, indent=2)
    sys.stdout.buffer.write(output.encode("utf-8", errors="backslashreplace") + b"\n")


if __name__ == "__main__":
    main()
