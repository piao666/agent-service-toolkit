#!/usr/bin/env python3
"""Phase 4E1: API 级别检索冒烟测试 — 3 条 query × 3 种 corpus 模式。

HPC 独立运行，不依赖项目 Python 包。仅需 requests + json。
向运行中的 FastAPI 服务发 POST 请求到 /api/enterprise-kb/retrieval/search。
验证 HTTP 200、results 非空、trace 13 字段完整性。
输出 JSONL trace 到 A_DIR。
"""

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

# ── 路径常量 ────────────────────────────────────────────────────────────────
A_DIR = Path.home() / "jupyterlab" / "RAG" / "A"
BASE_URL = "http://127.0.0.1:8000"
SEARCH_URL = f"{BASE_URL}/api/enterprise-kb/retrieval/search"

# ── 预期的 13 个 trace 字段 ─────────────────────────────────────────────────
EXPECTED_TRACE_FIELDS = [
    "query",
    "top_k",
    "embedding_model",
    "collection_name",
    "persist_dir",
    "retrieved_chunk_ids",
    "retrieved_source_ids",
    "scores",
    "origin_urls",
    "heading_paths",
    "text_previews",
    "latency_ms",
    "errors",
]

# ── 3 条测试 query，每条覆盖一种 corpus 模式 ────────────────────────────────
SMOKE_QUERIES = [
    {
        "id": "api_smoke_001",
        "query": "What is retrieval augmented generation?",
        "corpus": "official_docs",
        "top_k": 5,
    },
    {
        "id": "api_smoke_002",
        "query": "service.py FastAPI enterprise agent query endpoint",
        "corpus": "internal_engineering_docs",
        "top_k": 5,
    },
    {
        "id": "api_smoke_003",
        "query": "Chroma collection embedding function cosine similarity",
        "corpus": "auto",
        "top_k": 5,
    },
]

REQUEST_TIMEOUT = 30  # 秒


def _check_trace_fields(trace: dict) -> dict:
    """检查 trace 中 13 个预期字段是否全部存在且非空。"""
    missing = [f for f in EXPECTED_TRACE_FIELDS if f not in trace]
    empty = [f for f in EXPECTED_TRACE_FIELDS if f in trace and not trace[f] and trace[f] != 0]
    return {
        "all_13_fields_present": len(missing) == 0,
        "missing_fields": missing,
        "empty_fields": empty,
    }


def main() -> None:
    print("=" * 60)
    print("Phase 4E1: API-Level Retrieval Smoke Test")
    print(f"Start: {datetime.now(timezone.utc).isoformat()}")
    print(f"Target: {SEARCH_URL}")
    print("=" * 60)

    # ── 服务可用性检查 ──────────────────────────────────────────────────────
    try:
        health_resp = requests.get(f"{BASE_URL}/health", timeout=10)
        if health_resp.status_code != 200:
            print(f"FATAL: /health returned {health_resp.status_code}")
            sys.exit(1)
        print(f"Service health: {health_resp.json().get('status', 'unknown')}")
    except requests.ConnectionError:
        print(f"FATAL: Cannot connect to {BASE_URL}. Is the service running?")
        sys.exit(1)

    print()

    # ── 逐条测试 ────────────────────────────────────────────────────────────
    A_DIR.mkdir(parents=True, exist_ok=True)
    trace_path = A_DIR / "phase4e1_api_retrieval_smoke_trace.jsonl"
    results_path = A_DIR / "phase4e1_api_retrieval_smoke_results.json"

    all_traces: list[dict] = []
    summary_rows: list[dict] = []

    with open(trace_path, "w", encoding="utf-8") as trace_f:
        for i, sq in enumerate(SMOKE_QUERIES):
            qid = sq["id"]
            payload = {
                "query": sq["query"],
                "top_k": sq["top_k"],
                "corpus": sq["corpus"],
            }

            t_start = time.perf_counter()
            errors: list[str] = []

            try:
                resp = requests.post(
                    SEARCH_URL,
                    json=payload,
                    timeout=REQUEST_TIMEOUT,
                )
                latency_ms = round((time.perf_counter() - t_start) * 1000, 2)

                status_code = resp.status_code
                if status_code != 200:
                    errors.append(f"HTTP {status_code}: {resp.text[:200]}")
                    body = {}
                else:
                    body = resp.json()
            except requests.Timeout:
                latency_ms = REQUEST_TIMEOUT * 1000
                status_code = 0
                errors.append("Request timeout")
                body = {}
            except requests.ConnectionError as e:
                latency_ms = round((time.perf_counter() - t_start) * 1000, 2)
                status_code = 0
                errors.append(f"Connection error: {e}")
                body = {}

            # ── 验证 ─────────────────────────────────────────────────────────
            results_data = body.get("results", [])
            trace_data = body.get("trace", {})
            corpus_used = body.get("corpus_used", "unknown")

            http_ok = status_code == 200
            results_ok = http_ok and len(results_data) > 0
            trace_check = _check_trace_fields(trace_data)
            trace_ok = http_ok and trace_check["all_13_fields_present"] and len(trace_check["empty_fields"]) == 0

            overall_pass = http_ok and results_ok and trace_ok

            # ── 写入 trace JSONL ─────────────────────────────────────────────
            trace_record = {
                "query_id": qid,
                "query": sq["query"],
                "corpus_requested": sq["corpus"],
                "corpus_used": corpus_used,
                "top_k": sq["top_k"],
                "http_status": status_code,
                "latency_api_ms": latency_ms,
                "results_count": len(results_data),
                "http_ok": http_ok,
                "results_ok": results_ok,
                "trace_ok": trace_ok,
                "trace_missing_fields": trace_check["missing_fields"],
                "trace_empty_fields": trace_check["empty_fields"],
                "errors": errors,
                "response_trace": trace_data if trace_data else None,
            }
            all_traces.append(trace_record)
            trace_f.write(json.dumps(trace_record, ensure_ascii=False) + "\n")

            # ── 终端输出 ─────────────────────────────────────────────────────
            status = "PASS" if overall_pass else "FAIL"
            flags = []
            if not http_ok:
                flags.append(f"HTTP{status_code}")
            if not results_ok:
                flags.append("EMPTY")
            if not trace_ok:
                flags.append("TRACE")
            flag_str = f" ({', '.join(flags)})" if flags else ""

            print(f"  [{i + 1}/{len(SMOKE_QUERIES)}] {status}{flag_str} "
                  f"corpus={sq['corpus']}→{corpus_used} "
                  f"hits={len(results_data)} "
                  f"latency={latency_ms:.1f}ms  "
                  f"trace_fields="
                  f"{'OK' if trace_check['all_13_fields_present'] else 'MISSING:' + str(trace_check['missing_fields'])}  "
                  f"{'EMPTY:' + str(trace_check['empty_fields']) if trace_check['empty_fields'] else 'all_non_empty'}  "
                  f"{qid}")

            summary_rows.append({
                "query_id": qid,
                "query": sq["query"],
                "corpus_requested": sq["corpus"],
                "corpus_used": corpus_used,
                "http_ok": http_ok,
                "results_ok": results_ok,
                "trace_ok": trace_ok,
                "overall_pass": overall_pass,
                "results_count": len(results_data),
                "latency_api_ms": latency_ms,
                "errors": errors,
            })

    # ── 汇总 JSON ────────────────────────────────────────────────────────────
    all_pass = all(r["overall_pass"] for r in summary_rows)
    avg_latency = round(sum(r["latency_api_ms"] for r in summary_rows) / len(summary_rows), 2)

    results_summary = {
        "phase": "4E1",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "environment": "HPC",
        "target_url": SEARCH_URL,
        "smoke_test": {
            "total_queries": len(SMOKE_QUERIES),
            "all_pass": all_pass,
            "avg_latency_ms": avg_latency,
            "corpus_modes_tested": sorted(set(q["corpus"] for q in SMOKE_QUERIES)),
        },
        "summary": summary_rows,
    }

    with open(results_path, "w", encoding="utf-8") as f:
        json.dump(results_summary, f, ensure_ascii=False, indent=2)

    # ── 退出码 ───────────────────────────────────────────────────────────────
    print(f"\n{'=' * 60}")
    print(f"Total: {len(SMOKE_QUERIES)} queries")
    print(f"All pass: {all_pass}")
    print(f"Avg latency: {avg_latency}ms")
    print(f"Trace:       {trace_path}")
    print(f"Results:     {results_path}")
    print(f"{'=' * 60}")

    if not all_pass:
        failed = [r["query_id"] for r in summary_rows if not r["overall_pass"]]
        print(f"FAILED: {failed}")
        sys.exit(1)
    else:
        print("DONE: Phase 4E1 API Retrieval Smoke Test — ALL PASS")
        sys.exit(0)


if __name__ == "__main__":
    main()
