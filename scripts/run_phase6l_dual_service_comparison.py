#!/usr/bin/env python3
"""Run a guarded Phase 6L comparison against two isolated service processes."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
EVAL = ROOT / "data" / "knowledge_base" / "evaluation"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--legacy-port", type=int, default=8011)
    parser.add_argument("--custom-port", type=int, default=8012)
    parser.add_argument("--startup-timeout", type=float, default=60.0)
    parser.add_argument("--request-timeout", type=float, default=30.0)
    return parser.parse_args()


def service_env(mode: str, port: int) -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "PYTHONPATH": str(SRC),
            "PORT": str(port),
            "USE_FAKE_MODEL": "true",
            "DEFAULT_MODEL": "fake",
            "ENTERPRISE_AGENT_GRAPH_MODE": mode,
        }
    )
    return env


def start_service(mode: str, port: int) -> subprocess.Popen[str]:
    return subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "service.service:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--log-level",
            "error",
        ],
        cwd=ROOT,
        env=service_env(mode, port),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )


def wait_for_health(port: int, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    url = f"http://127.0.0.1:{port}/health"
    while time.monotonic() < deadline:
        try:
            if requests.get(url, timeout=2).status_code == 200:
                return
        except requests.RequestException:
            pass
        time.sleep(0.5)
    raise RuntimeError(f"service_start_timeout:{port}")


def diagnostic(port: int, expected_mode: str, timeout: float) -> dict[str, Any]:
    response = requests.post(
        f"http://127.0.0.1:{port}/enterprise/agent/query",
        json={
            "query": "What is RAG?",
            "session_id": f"phase6l-diagnostic-{expected_mode}",
            "top_k": 1,
            "return_sources": False,
            "model": "fake",
        },
        timeout=timeout,
    )
    payload = response.json()
    model_mode = (payload.get("model_debug") or {}).get("agent_graph_mode")
    graph_debug = payload.get("graph_debug") or {}
    nodes = graph_debug.get("nodes_executed") or []
    valid = response.status_code == 200 and model_mode == expected_mode
    if expected_mode == "custom_graph":
        valid = bool(
            valid
            and graph_debug.get("graph_mode") == "custom_graph"
            and isinstance(nodes, list)
            and nodes
        )
    elif graph_debug:
        valid = False
    return {
        "status_code": response.status_code,
        "model_mode": model_mode,
        "graph_mode": graph_debug.get("graph_mode"),
        "nodes_count": len(nodes) if isinstance(nodes, list) else 0,
        "valid": valid,
    }


def stop_service(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def main() -> int:
    args = parse_args()
    processes = [
        start_service("legacy", args.legacy_port),
        start_service("custom_graph", args.custom_port),
    ]
    try:
        wait_for_health(args.legacy_port, args.startup_timeout)
        wait_for_health(args.custom_port, args.startup_timeout)
        diagnostics = {
            "legacy": diagnostic(
                args.legacy_port, "legacy", args.request_timeout
            ),
            "custom_graph": diagnostic(
                args.custom_port, "custom_graph", args.request_timeout
            ),
        }
        if not all(item["valid"] for item in diagnostics.values()):
            print(json.dumps({"diagnostics": diagnostics}, indent=2))
            return 2

        completed = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "run_phase6l_endpoint_comparison.py"),
                "--legacy-url",
                f"http://127.0.0.1:{args.legacy_port}/enterprise/agent/query",
                "--custom-graph-url",
                f"http://127.0.0.1:{args.custom_port}/enterprise/agent/query",
                "--timeout",
                str(args.request_timeout),
            ],
            cwd=ROOT,
            check=False,
        )
        if completed.returncode != 0:
            return completed.returncode

        source_names = (
            "phase6l_endpoint_comparison_cases.jsonl",
            "phase6l_endpoint_comparison_results.jsonl",
            "phase6l_endpoint_comparison_summary.json",
        )
        target_names = (
            "phase6l_dual_service_comparison_cases.jsonl",
            "phase6l_dual_service_comparison_results.jsonl",
            "phase6l_dual_service_comparison_summary.json",
        )
        for source_name, target_name in zip(source_names, target_names, strict=True):
            shutil.copyfile(EVAL / source_name, EVAL / target_name)
        print(json.dumps({"diagnostics": diagnostics}, indent=2))
        return 0
    finally:
        for process in processes:
            stop_service(process)


if __name__ == "__main__":
    raise SystemExit(main())
