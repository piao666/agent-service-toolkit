from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parents[1]
BASE_URL = "http://127.0.0.1:8000"
QUERY_URL = f"{BASE_URL}/enterprise/agent/query"
HEALTH_URL = f"{BASE_URL}/health"
RESULTS_PATH = (
    REPO_ROOT / "data/knowledge_base/evaluation/phase6g_api_memory_eval_results.jsonl"
)
SUMMARY_PATH = REPO_ROOT / "data/knowledge_base/evaluation/phase6g_api_memory_eval_summary.json"
REQUEST_TIMEOUT_SEC = 30.0
STARTUP_TIMEOUT_SEC = 120.0
LOCAL_AUTH_TOKEN = "phase6g-eval"
REQUIRED_RESPONSE_FIELDS = {
    "answer",
    "sources",
    "retrieval_debug",
    "latency_ms",
    "model_debug",
    "memory_debug",
    "fallback",
    "session_id",
}
REQUIRED_MEMORY_DEBUG_FIELDS = {
    "memory_mode",
    "memory_enabled",
    "session_id",
    "memory_turn_count_before",
    "memory_turn_count_after",
    "is_follow_up",
    "original_query",
    "contextual_query",
    "memory_rewrite_strategy",
    "memory_used_for_retrieval",
    "memory_written",
    "cross_session_isolated",
}


@dataclass(slots=True)
class ManagedService:
    process: subprocess.Popen[str]
    log_path: Path
    log_handle: Any

    def stop(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        self.log_handle.close()
        for _ in range(10):
            try:
                self.log_path.unlink(missing_ok=True)
                break
            except PermissionError:
                time.sleep(0.2)


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def _port_in_use() -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.3)
        return sock.connect_ex(("127.0.0.1", 8000)) == 0


def _safe_error(error: Exception) -> str:
    if isinstance(error, HTTPError):
        return f"http_error:{error.code}"
    if isinstance(error, URLError):
        return f"connection_error:{type(error.reason).__name__}"
    return type(error).__name__


def _request_json(
    url: str,
    payload: dict[str, Any] | None = None,
    timeout: float = REQUEST_TIMEOUT_SEC,
) -> tuple[int, dict[str, Any]]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload else None
    request = Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {LOCAL_AUTH_TOKEN}",
            "Content-Type": "application/json",
        },
        method="POST" if payload is not None else "GET",
    )
    with urlopen(request, timeout=timeout) as response:  # noqa: S310
        body = response.read().decode("utf-8")
        return response.status, json.loads(body)


def _service_environment(memory_mode: str, runtime_dir: Path) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "AUTH_SECRET": LOCAL_AUTH_TOKEN,
            "DEFAULT_MODEL": "fake",
            "USE_FAKE_MODEL": "true",
            "ENTERPRISE_MEMORY_MODE": memory_mode,
            "ENTERPRISE_MEMORY_MAX_TURNS": "5",
            "ENTERPRISE_MEMORY_MAX_ANSWER_CHARS": "1000",
            "LOCAL_EMBEDDING_MODEL_PATH": str(runtime_dir / "missing_embedding_model"),
            "CHROMA_PERSIST_DIR": str(runtime_dir / "unused_chroma"),
            "SQLITE_DB_PATH": str(runtime_dir / f"phase6g_{memory_mode}.db"),
            "LANGCHAIN_TRACING_V2": "false",
            "LANGFUSE_TRACING": "false",
            "MODE": "prod",
            "HOST": "127.0.0.1",
            "PORT": "8000",
            "LOG_LEVEL": "ERROR",
        }
    )
    return env


def _start_service(memory_mode: str, runtime_dir: Path) -> ManagedService:
    if _port_in_use():
        raise RuntimeError("port_8000_already_in_use")
    log_file = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        prefix=f"phase6g_{memory_mode}_",
        suffix=".log",
        delete=False,
    )
    process = subprocess.Popen(  # noqa: S603
        [sys.executable, str(REPO_ROOT / "src/run_service.py")],
        cwd=REPO_ROOT,
        env=_service_environment(memory_mode, runtime_dir),
        stdout=log_file,
        stderr=subprocess.STDOUT,
        text=True,
    )
    managed = ManagedService(process=process, log_path=Path(log_file.name), log_handle=log_file)
    deadline = time.monotonic() + STARTUP_TIMEOUT_SEC
    while time.monotonic() < deadline:
        if process.poll() is not None:
            managed.stop()
            raise RuntimeError("service_process_exited_during_startup")
        try:
            status, _ = _request_json(HEALTH_URL, timeout=2.0)
            if status == 200:
                return managed
        except (HTTPError, URLError, TimeoutError, json.JSONDecodeError):
            time.sleep(0.5)
    managed.stop()
    raise TimeoutError("service_startup_timeout")


def _query_payload(query: str, session_id: str | None) -> dict[str, Any]:
    return {
        "query": query,
        "session_id": session_id,
        "top_k": 3,
        "return_sources": True,
        "model": "fake",
    }


def _response_schema_valid(response: dict[str, Any]) -> bool:
    return bool(
        REQUIRED_RESPONSE_FIELDS.issubset(response)
        and isinstance(response.get("answer"), str)
        and isinstance(response.get("sources"), list)
        and isinstance(response.get("retrieval_debug"), dict)
        and isinstance(response.get("model_debug"), dict)
        and isinstance(response.get("memory_debug"), dict)
        and isinstance(response.get("fallback"), dict)
        and isinstance(response.get("latency_ms"), (int, float))
    )


def _evaluate_request(
    case_id: str,
    case_type: str,
    memory_mode: str,
    request_index: int,
    query: str,
    session_id: str | None,
    expected: dict[str, Any],
) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        status, response = _request_json(QUERY_URL, _query_payload(query, session_id))
    except TimeoutError as error:
        return {
            "case_id": case_id,
            "case_type": case_type,
            "memory_mode": memory_mode,
            "request_index": request_index,
            "query": query,
            "status_code": None,
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            "timeout": True,
            "error": _safe_error(error),
            "passed": False,
        }
    except (HTTPError, URLError, json.JSONDecodeError) as error:
        return {
            "case_id": case_id,
            "case_type": case_type,
            "memory_mode": memory_mode,
            "request_index": request_index,
            "query": query,
            "status_code": error.code if isinstance(error, HTTPError) else None,
            "latency_ms": round((time.perf_counter() - started) * 1000, 2),
            "timeout": False,
            "error": _safe_error(error),
            "passed": False,
        }

    memory_debug = response.get("memory_debug") if isinstance(response, dict) else {}
    debug_complete = isinstance(memory_debug, dict) and REQUIRED_MEMORY_DEBUG_FIELDS.issubset(
        memory_debug
    )
    contextual_query = str(memory_debug.get("contextual_query") or "")
    required_terms = expected.get("contextual_query_contains", [])
    forbidden_terms = expected.get("contextual_query_excludes", [])
    checks = {
        "status_ok": status == 200,
        "response_schema_valid": _response_schema_valid(response),
        "memory_debug_complete": debug_complete,
        "memory_enabled_matches": memory_debug.get("memory_enabled")
        is expected["memory_enabled"],
        "follow_up_matches": memory_debug.get("is_follow_up") is expected["is_follow_up"],
        "memory_used_matches": memory_debug.get("memory_used_for_retrieval")
        is expected["memory_used_for_retrieval"],
        "memory_written_matches": memory_debug.get("memory_written")
        is expected["memory_written"],
        "turn_count_before_matches": memory_debug.get("memory_turn_count_before")
        == expected["memory_turn_count_before"],
        "contextual_query_terms_present": all(
            term.lower() in contextual_query.lower() for term in required_terms
        ),
        "contextual_query_terms_excluded": all(
            term.lower() not in contextual_query.lower() for term in forbidden_terms
        ),
    }
    if expected.get("contextual_query_unchanged"):
        checks["contextual_query_unchanged"] = contextual_query == query
    errors = [name for name, passed in checks.items() if not passed]
    return {
        "case_id": case_id,
        "case_type": case_type,
        "memory_mode": memory_mode,
        "request_index": request_index,
        "query": query,
        "session_id": session_id,
        "status_code": status,
        "latency_ms": round((time.perf_counter() - started) * 1000, 2),
        "timeout": False,
        "response_schema_valid": checks["response_schema_valid"],
        "memory_debug_present": debug_complete,
        "memory_debug": memory_debug,
        "contextual_query_hit": bool(required_terms and checks["contextual_query_terms_present"]),
        "cross_session_leak": not checks["contextual_query_terms_excluded"],
        "checks": checks,
        "errors": errors,
        "passed": not errors,
    }


def _scenarios() -> list[dict[str, Any]]:
    return [
        {
            "case_id": "api_mem_001",
            "case_type": "memory_off_baseline",
            "memory_mode": "off",
            "requests": [
                {
                    "query": "RAG 是什么？",
                    "session_id": "phase6g_api_off_a",
                    "expected": {
                        "memory_enabled": False,
                        "is_follow_up": False,
                        "memory_used_for_retrieval": False,
                        "memory_written": False,
                        "memory_turn_count_before": 0,
                        "contextual_query_unchanged": True,
                    },
                }
            ],
        },
        {
            "case_id": "api_mem_002",
            "case_type": "two_turn_follow_up",
            "memory_mode": "buffer",
            "requests": [
                {
                    "query": "RAG 是什么？",
                    "session_id": "phase6g_api_rag_two",
                    "expected": {
                        "memory_enabled": True,
                        "is_follow_up": False,
                        "memory_used_for_retrieval": False,
                        "memory_written": True,
                        "memory_turn_count_before": 0,
                        "contextual_query_unchanged": True,
                    },
                },
                {
                    "query": "它有什么局限？",
                    "session_id": "phase6g_api_rag_two",
                    "expected": {
                        "memory_enabled": True,
                        "is_follow_up": True,
                        "memory_used_for_retrieval": True,
                        "memory_written": True,
                        "memory_turn_count_before": 1,
                        "contextual_query_contains": ["RAG", "局限"],
                    },
                },
            ],
        },
        {
            "case_id": "api_mem_003",
            "case_type": "three_turn_follow_up",
            "memory_mode": "buffer",
            "requests": [
                {
                    "query": "RAG 是什么？",
                    "session_id": "phase6g_api_rag_three",
                    "expected": {
                        "memory_enabled": True,
                        "is_follow_up": False,
                        "memory_used_for_retrieval": False,
                        "memory_written": True,
                        "memory_turn_count_before": 0,
                        "contextual_query_unchanged": True,
                    },
                },
                {
                    "query": "它有什么局限？",
                    "session_id": "phase6g_api_rag_three",
                    "expected": {
                        "memory_enabled": True,
                        "is_follow_up": True,
                        "memory_used_for_retrieval": True,
                        "memory_written": True,
                        "memory_turn_count_before": 1,
                        "contextual_query_contains": ["RAG", "局限"],
                    },
                },
                {
                    "query": "那它适合什么场景？",
                    "session_id": "phase6g_api_rag_three",
                    "expected": {
                        "memory_enabled": True,
                        "is_follow_up": True,
                        "memory_used_for_retrieval": True,
                        "memory_written": True,
                        "memory_turn_count_before": 2,
                        "contextual_query_contains": ["RAG", "适合什么场景"],
                        "contextual_query_excludes": ["局限:"],
                    },
                },
            ],
        },
        {
            "case_id": "api_mem_004",
            "case_type": "cross_session_isolation",
            "memory_mode": "buffer",
            "requests": [
                {
                    "query": "RAG 是什么？",
                    "session_id": "phase6g_api_iso_rag",
                    "expected": {
                        "memory_enabled": True,
                        "is_follow_up": False,
                        "memory_used_for_retrieval": False,
                        "memory_written": True,
                        "memory_turn_count_before": 0,
                        "contextual_query_unchanged": True,
                    },
                },
                {
                    "query": "LoRA 是什么？",
                    "session_id": "phase6g_api_iso_lora",
                    "expected": {
                        "memory_enabled": True,
                        "is_follow_up": False,
                        "memory_used_for_retrieval": False,
                        "memory_written": True,
                        "memory_turn_count_before": 0,
                        "contextual_query_unchanged": True,
                    },
                },
                {
                    "query": "它有什么局限？",
                    "session_id": "phase6g_api_iso_rag",
                    "expected": {
                        "memory_enabled": True,
                        "is_follow_up": True,
                        "memory_used_for_retrieval": True,
                        "memory_written": True,
                        "memory_turn_count_before": 1,
                        "contextual_query_contains": ["RAG", "局限"],
                        "contextual_query_excludes": ["LoRA"],
                    },
                },
                {
                    "query": "它有什么局限？",
                    "session_id": "phase6g_api_iso_lora",
                    "expected": {
                        "memory_enabled": True,
                        "is_follow_up": True,
                        "memory_used_for_retrieval": True,
                        "memory_written": True,
                        "memory_turn_count_before": 1,
                        "contextual_query_contains": ["LoRA", "局限"],
                        "contextual_query_excludes": ["RAG"],
                    },
                },
            ],
        },
        {
            "case_id": "api_mem_005",
            "case_type": "missing_session_noop",
            "memory_mode": "buffer",
            "requests": [
                {
                    "query": "它有什么局限？",
                    "session_id": None,
                    "expected": {
                        "memory_enabled": False,
                        "is_follow_up": False,
                        "memory_used_for_retrieval": False,
                        "memory_written": False,
                        "memory_turn_count_before": 0,
                        "contextual_query_unchanged": True,
                    },
                }
            ],
        },
        {
            "case_id": "api_mem_006",
            "case_type": "no_context_follow_up",
            "memory_mode": "buffer",
            "requests": [
                {
                    "query": "它有什么局限？",
                    "session_id": "phase6g_api_empty_session",
                    "expected": {
                        "memory_enabled": True,
                        "is_follow_up": True,
                        "memory_used_for_retrieval": False,
                        "memory_written": True,
                        "memory_turn_count_before": 0,
                        "contextual_query_unchanged": True,
                    },
                }
            ],
        },
    ]


def _run_mode(
    memory_mode: str,
    scenarios: list[dict[str, Any]],
    runtime_dir: Path,
) -> tuple[list[dict[str, Any]], bool]:
    service = _start_service(memory_mode, runtime_dir)
    rows: list[dict[str, Any]] = []
    try:
        for scenario in scenarios:
            for request_index, item in enumerate(scenario["requests"], start=1):
                rows.append(
                    _evaluate_request(
                        case_id=scenario["case_id"],
                        case_type=scenario["case_type"],
                        memory_mode=memory_mode,
                        request_index=request_index,
                        query=item["query"],
                        session_id=item["session_id"],
                        expected=item["expected"],
                    )
                )
    finally:
        service.stop()
    return rows, True


def _build_summary(
    scenarios: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    api_available: bool,
    startup_error: str | None,
) -> dict[str, Any]:
    eligible = [
        row
        for row in rows
        if row.get("memory_debug", {}).get("memory_used_for_retrieval") is True
    ]
    hit_count = sum(row.get("contextual_query_hit") is True for row in eligible)
    summary: dict[str, Any] = {
        "phase": "6G-5_api_memory_eval",
        "case_count": len(scenarios),
        "request_count": len(rows),
        "api_available": api_available,
        "startup_error": startup_error,
        "memory_off_noop_count": sum(
            row.get("passed") is True and row.get("case_type") == "memory_off_baseline"
            for row in rows
        ),
        "memory_on_enabled_count": sum(
            row.get("memory_debug", {}).get("memory_enabled") is True for row in rows
        ),
        "follow_up_detected_count": sum(
            row.get("memory_debug", {}).get("is_follow_up") is True for row in rows
        ),
        "contextual_query_returned_count": len(eligible),
        "contextual_query_hit_rate": round(hit_count / len(eligible), 4) if eligible else 0.0,
        "memory_debug_present_count": sum(
            row.get("memory_debug_present") is True for row in rows
        ),
        "cross_session_leak_count": sum(row.get("cross_session_leak") is True for row in rows),
        "missing_session_noop_count": sum(
            row.get("passed") is True and row.get("case_type") == "missing_session_noop"
            for row in rows
        ),
        "no_context_noop_count": sum(
            row.get("passed") is True and row.get("case_type") == "no_context_follow_up"
            for row in rows
        ),
        "response_schema_valid_count": sum(
            row.get("response_schema_valid") is True for row in rows
        ),
        "error_count": sum(row.get("passed") is not True and not row.get("timeout") for row in rows),
        "timeout_count": sum(row.get("timeout") is True for row in rows),
        "failed_case_ids": sorted({row["case_id"] for row in rows if row.get("passed") is not True}),
        "uses_fake_model": True,
        "calls_llm": False,
        "writes_chroma": False,
        "starts_service": True,
    }
    summary["acceptance_passed"] = bool(
        summary["api_available"]
        and summary["error_count"] == 0
        and summary["timeout_count"] == 0
        and summary["cross_session_leak_count"] == 0
        and summary["contextual_query_hit_rate"] >= 0.8
        and summary["memory_debug_present_count"] == summary["request_count"]
        and summary["response_schema_valid_count"] == summary["request_count"]
        and not summary["calls_llm"]
        and not summary["writes_chroma"]
    )
    summary["recommended_checkpoint"] = summary["acceptance_passed"]
    return summary


def main() -> None:
    scenarios = _scenarios()
    rows: list[dict[str, Any]] = []
    api_available = False
    startup_error: str | None = None
    with tempfile.TemporaryDirectory(
        prefix="phase6g_api_memory_", ignore_cleanup_errors=True
    ) as runtime:
        runtime_dir = Path(runtime)
        try:
            off_scenarios = [item for item in scenarios if item["memory_mode"] == "off"]
            buffer_scenarios = [item for item in scenarios if item["memory_mode"] == "buffer"]
            off_rows, off_available = _run_mode("off", off_scenarios, runtime_dir)
            rows.extend(off_rows)
            buffer_rows, buffer_available = _run_mode("buffer", buffer_scenarios, runtime_dir)
            rows.extend(buffer_rows)
            api_available = off_available and buffer_available
        except (RuntimeError, TimeoutError) as error:
            startup_error = _safe_error(error)

    summary = _build_summary(scenarios, rows, api_available, startup_error)
    _write_jsonl(RESULTS_PATH, rows)
    _write_json(SUMMARY_PATH, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    if not summary["acceptance_passed"]:
        raise SystemExit("Phase 6G-5 API memory evaluation did not meet acceptance criteria")


if __name__ == "__main__":
    main()
