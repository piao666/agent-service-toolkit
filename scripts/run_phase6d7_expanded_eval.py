#!/usr/bin/env python3
"""Phase 6D-7 总控脚本：顺序执行 embedding → retrieval → reranker → agent/api 复验。

通过调用现有 Phase 6D eval 脚本, 传入 expanded cases 文件路径实现复用.
每个子阶段独立 try/except, 一个失败不影响后续.

用法:
  python scripts/run_phase6d7_expanded_eval.py [--device cuda] [--skip-agent]
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
EVAL_DIR = ROOT_DIR / "data" / "knowledge_base" / "evaluation"
SCRIPTS_DIR = ROOT_DIR / "scripts"

EXPANDED_CASES = EVAL_DIR / "phase6d7_expanded_cases.jsonl"
CHUNK_MANIFEST = ROOT_DIR / "data" / "knowledge_base" / "manifests" / "chunk_manifest.jsonl"


def run_cmd(cmd: list[str], label: str, timeout: int = 3600) -> int:
    """运行子进程, 打印输出, 返回 exit code。"""
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"  {' '.join(str(x) for x in cmd)}")
    print(f"{'='*60}")
    start = time.time()
    try:
        result = subprocess.run(
            [str(x) for x in cmd],
            cwd=str(ROOT_DIR),
            timeout=timeout,
        )
        elapsed = time.time() - start
        if result.returncode == 0:
            print(f"[OK] {label} — {elapsed:.0f}s")
        else:
            print(f"[FAIL] {label} (exit={result.returncode}) — {elapsed:.0f}s")
        return result.returncode
    except subprocess.TimeoutExpired:
        elapsed = time.time() - start
        print(f"[TIMEOUT] {label} — {elapsed:.0f}s")
        return -1
    except Exception as exc:
        print(f"[ERROR] {label}: {exc}")
        return -2


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase 6D-7 expanded evaluation orchestrator")
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--skip-agent", action="store_true", help="跳过 Agent/API 评估")
    parser.add_argument("--python", default=sys.executable, help="Python 解释器路径")
    args = parser.parse_args()

    # 确认 expanded cases 存在
    if not EXPANDED_CASES.exists():
        print(f"ERROR: expanded cases not found: {EXPANDED_CASES}")
        print("Run: python scripts/build_phase6d7_expanded_cases.py")
        sys.exit(1)

    python = args.python
    device = args.device
    results: dict[str, int] = {}

    # ── 1. Embedding benchmark (3 模型) ──
    embedding_cmd = [
        python,
        str(SCRIPTS_DIR / "run_phase6d_embedding_benchmark.py"),
        "--cases", str(EXPANDED_CASES),
        "--chunk-manifest", str(CHUNK_MANIFEST),
        "--results", str(EVAL_DIR / "phase6d7_embedding_results.jsonl"),
        "--summary", str(EVAL_DIR / "phase6d7_embedding_summary.json"),
        "--load-report", str(EVAL_DIR / "phase6d7_embedding_model_load_report.json"),
        "--models", "bge-small-zh-v1.5", "bge-m3", "qwen3-embedding-0.6b",
        "--batch-size", "16",
        "--top-k", "5",
    ]
    results["embedding"] = run_cmd(embedding_cmd, "Embedding Benchmark (3 models)")

    # ── 2. Retrieval strategy eval ──
    retrieval_cmd = [
        python,
        str(SCRIPTS_DIR / "run_phase6d_hybrid_retrieval_eval.py"),
        "--cases", str(EXPANDED_CASES),
        "--chunk-manifest", str(CHUNK_MANIFEST),
        "--results", str(EVAL_DIR / "phase6d7_retrieval_strategy_results.jsonl"),
        "--summary", str(EVAL_DIR / "phase6d7_retrieval_strategy_summary.json"),
        "--model-alias", "bge-small-zh-v1.5",
        "--batch-size", "16",
        "--top-k", "5",
        "--device", device,
    ]
    results["retrieval"] = run_cmd(retrieval_cmd, "Retrieval Strategy Eval (5 strategies)")

    # ── 3. Reranker eval (bge-reranker-base) ──
    reranker_bge_cmd = [
        python,
        str(SCRIPTS_DIR / "run_phase6d_reranker_eval.py"),
        "--cases", str(EXPANDED_CASES),
        "--chunk-manifest", str(CHUNK_MANIFEST),
        "--results", str(EVAL_DIR / "phase6d7_reranker_bge_results.jsonl"),
        "--summary", str(EVAL_DIR / "phase6d7_reranker_bge_summary.json"),
        "--load-report", str(EVAL_DIR / "phase6d7_reranker_bge_model_load_report.json"),
        "--reranker-alias", "bge-reranker-base",
        "--dense-model-alias", "bge-small-zh-v1.5",
        "--candidate-pool-size", "20",
        "--top-k", "5",
        "--batch-size", "8",
        "--device", device,
    ]
    results["reranker_bge"] = run_cmd(reranker_bge_cmd, "Reranker: bge-reranker-base")

    # ── 4. Reranker eval (qwen3-reranker-0.6b) ──
    reranker_qwen_cmd = [
        python,
        str(SCRIPTS_DIR / "run_phase6d_reranker_eval.py"),
        "--cases", str(EXPANDED_CASES),
        "--chunk-manifest", str(CHUNK_MANIFEST),
        "--results", str(EVAL_DIR / "phase6d7_reranker_qwen_results.jsonl"),
        "--summary", str(EVAL_DIR / "phase6d7_reranker_qwen_summary.json"),
        "--load-report", str(EVAL_DIR / "phase6d7_reranker_qwen_model_load_report.json"),
        "--reranker-alias", "qwen3-reranker-0.6b",
        "--dense-model-alias", "bge-small-zh-v1.5",
        "--candidate-pool-size", "10",
        "--top-k", "5",
        "--batch-size", "1",
        "--device", device,
    ]
    results["reranker_qwen"] = run_cmd(reranker_qwen_cmd, "Reranker: qwen3-reranker-0.6b")

    # ── 5. Agent/API eval ──
    if not args.skip_agent:
        agent_cmd = [
            python,
            str(SCRIPTS_DIR / "run_phase6d_agent_api_eval.py"),
            "--cases", str(EXPANDED_CASES),
            "--results", str(EVAL_DIR / "phase6d7_agent_api_results.jsonl"),
            "--summary", str(EVAL_DIR / "phase6d7_agent_api_summary.json"),
        ]
        results["agent_api"] = run_cmd(agent_cmd, "Agent/API Eval (240 cases)", timeout=7200)
    else:
        results["agent_api"] = -99  # skipped

    # ── 汇总 ──
    print(f"\n{'='*60}")
    print("  Phase 6D-7 复验完成")
    print(f"{'='*60}")
    for label, code in results.items():
        if code == 0:
            status = "PASS"
        elif code == -99:
            status = "SKIPPED"
        elif code == -1:
            status = "TIMEOUT"
        else:
            status = f"FAIL({code})"
        print(f"  {label:20s}: {status}")
    print(f"\n结果目录: {EVAL_DIR}")


if __name__ == "__main__":
    main()
