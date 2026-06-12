from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import numpy as np

ROOT_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT_DIR / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from run_phase6d_hybrid_retrieval_eval import (  # noqa: E402
    CHUNK_MANIFEST_PATH,
    EVAL_DIR,
    BM25Index,
    build_records,
    contains_any,
    encode_texts,
    exact_scores,
    is_allowed_chunk,
    load_dense_model,
    load_jsonl,
    normalize_scores,
    strategy_scores,
    tokenize,
    write_json,
    write_jsonl,
)
from run_phase6d_hybrid_retrieval_eval import (  # noqa: E402
    MODEL_ALIASES as DENSE_MODEL_ALIASES,
)

DEFAULT_SOURCE_CASES_PATH = EVAL_DIR / "phase6d_hybrid_retrieval_cases.jsonl"
DEFAULT_CASES_PATH = EVAL_DIR / "phase6d_reranker_cases.jsonl"
DEFAULT_RESULTS_PATH = EVAL_DIR / "phase6d_reranker_eval_results.jsonl"
DEFAULT_SUMMARY_PATH = EVAL_DIR / "phase6d_reranker_eval_summary.json"
DEFAULT_LOAD_REPORT_PATH = EVAL_DIR / "phase6d_reranker_model_load_report.json"
PREVIEW_MAX_CHARS = 160
RERANKER_ALIASES = {
    "bge-reranker-base": "<LOCAL_RERANKER_MODEL_ROOT>/bge-reranker-base",
    "qwen3-reranker-0.6b": "<LOCAL_RERANKER_MODEL_ROOT>/Qwen3-Reranker_0.6B",
}
RERANKER_RUNTIME_DIRS = {
    "bge-reranker-base": ["bge-reranker-base"],
    "qwen3-reranker-0.6b": ["Qwen3-Reranker_0.6B", "Qwen3-Reranker-0.6B"],
}
CANDIDATE_STRATEGIES = ["dense_only", "sparse_bm25", "hybrid_weighted"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Phase 6D-4 offline reranker evaluation.")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument("--source-cases", type=Path, default=DEFAULT_SOURCE_CASES_PATH)
    parser.add_argument("--chunk-manifest", type=Path, default=CHUNK_MANIFEST_PATH)
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS_PATH)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY_PATH)
    parser.add_argument("--load-report", type=Path, default=DEFAULT_LOAD_REPORT_PATH)
    parser.add_argument(
        "--reranker-alias",
        default="bge-reranker-base",
        choices=sorted(RERANKER_ALIASES),
    )
    parser.add_argument(
        "--dense-model-alias",
        default="bge-small-zh-v1.5",
        choices=sorted(DENSE_MODEL_ALIASES),
    )
    parser.add_argument("--limit-cases", type=int, default=0)
    parser.add_argument("--limit-chunks", type=int, default=0)
    parser.add_argument("--candidate-pool-size", type=int, default=20)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument("--load-only", action="store_true")
    return parser.parse_args()


def safe_error_message(error: Exception | str) -> str:
    message = str(error)
    for env_name, placeholder in [
        ("LOCAL_RERANKER_MODEL_ROOT", "<LOCAL_RERANKER_MODEL_ROOT>"),
        ("LOCAL_EMBEDDING_MODEL_ROOT", "<LOCAL_EMBEDDING_MODEL_ROOT>"),
    ]:
        runtime_root = os.environ.get(env_name)
        if runtime_root:
            message = message.replace(runtime_root, placeholder)
            message = message.replace(runtime_root.replace("\\", "/"), placeholder)
    message = re.sub(r"[A-Za-z]:[\\/][^\s\"']+", "<LOCAL_PATH>", message)
    user_home_pattern = "/" + "".join(["Us", "ers"]) + r"/[^\s\"']+"
    message = re.sub(user_home_pattern, "<LOCAL_PATH>", message)
    return " ".join(message.split())[:500]


def write_load_report(path: Path, alias: str, payload: dict[str, Any]) -> None:
    report: dict[str, Any] = {
        "phase": "6D-4",
        "models": {},
        "uses_alias_paths_only": True,
        "calls_llm": False,
        "writes_chroma": False,
        "writes_production_chroma_collection": False,
        "modifies_agent": False,
        "modifies_api": False,
    }
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(existing, dict):
            report.update(existing)
            if not isinstance(report.get("models"), dict):
                report["models"] = {}
    report["models"][alias] = payload
    write_json(path, report)


def resolve_reranker_path(alias: str) -> tuple[Path | None, str | None]:
    root = os.environ.get("LOCAL_RERANKER_MODEL_ROOT")
    if not root:
        return None, "missing_LOCAL_RERANKER_MODEL_ROOT"
    for dirname in RERANKER_RUNTIME_DIRS[alias]:
        runtime_path = Path(root) / dirname
        if runtime_path.exists():
            return runtime_path, None
    return Path(root) / RERANKER_RUNTIME_DIRS[alias][0], None


def load_reranker(alias: str, device: str) -> Any:
    runtime_path, error = resolve_reranker_path(alias)
    if error:
        raise RuntimeError(error)
    if runtime_path is None or not runtime_path.exists():
        raise RuntimeError("local reranker alias path does not exist")
    from sentence_transformers import CrossEncoder

    return CrossEncoder(str(runtime_path), device=device, trust_remote_code=True)


def load_reranker_with_report(args: argparse.Namespace) -> tuple[Any | None, dict[str, Any]]:
    start = time.perf_counter()
    try:
        model = load_reranker(args.reranker_alias, args.device)
        latency_ms = (time.perf_counter() - start) * 1000
        report = {
            "alias": args.reranker_alias,
            "model_path_alias": RERANKER_ALIASES[args.reranker_alias],
            "load_success": True,
            "load_latency_ms": round(latency_ms, 2),
            "device": args.device,
            "load_mode": "cross_encoder",
            "local_resource_limited": False,
            "error_summary": None,
        }
        write_load_report(args.load_report, args.reranker_alias, report)
        return model, report
    except Exception as exc:  # noqa: BLE001
        latency_ms = (time.perf_counter() - start) * 1000
        report = {
            "alias": args.reranker_alias,
            "model_path_alias": RERANKER_ALIASES[args.reranker_alias],
            "load_success": False,
            "load_latency_ms": round(latency_ms, 2),
            "device": args.device,
            "load_mode": "cross_encoder",
            "local_resource_limited": True,
            "error_summary": safe_error_message(exc),
        }
        write_load_report(args.load_report, args.reranker_alias, report)
        return None, report


def ensure_reranker_cases(cases_path: Path, source_cases_path: Path) -> list[dict[str, Any]]:
    if cases_path.exists():
        return load_jsonl(cases_path)
    source_cases = load_jsonl(source_cases_path)
    reranker_cases: list[dict[str, Any]] = []
    for index, case in enumerate(source_cases, start=1):
        row = dict(case)
        row["case_id"] = f"rerank_{index:03d}"
        row["source_case_id"] = case.get("case_id")
        row["phase"] = "6D-4"
        row["evaluation_focus"] = "reranker_before_after"
        reranker_cases.append(row)
    write_jsonl(cases_path, reranker_cases)
    return reranker_cases


def top_indices(scores: np.ndarray, limit: int) -> list[int]:
    return [int(index) for index in np.argsort(scores)[::-1][:limit]]


def build_candidate_indices(
    scores_by_strategy: dict[str, np.ndarray],
    candidate_pool_size: int,
) -> list[int]:
    selected: list[int] = []
    seen: set[int] = set()
    for strategy in CANDIDATE_STRATEGIES:
        for index in top_indices(scores_by_strategy[strategy], candidate_pool_size):
            if index not in seen:
                selected.append(index)
                seen.add(index)
    reference_scores = scores_by_strategy["hybrid_weighted"]
    selected.sort(key=lambda item: float(reference_scores[item]), reverse=True)
    return selected[:candidate_pool_size]


def compute_mrr(source_ids: list[str], expected_source: str | None) -> float:
    if not expected_source:
        return 0.0
    for rank, source_id in enumerate(source_ids, start=1):
        if source_id == expected_source:
            return 1.0 / rank
    return 0.0


def public_ranked_rows(
    ranked_indices: list[int],
    records: list[dict[str, Any]],
    scores: np.ndarray,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for rank, index in enumerate(ranked_indices, start=1):
        chunk = records[index]["chunk"]
        rows.append(
            {
                "rank": rank,
                "chunk_id": chunk.get("chunk_id"),
                "source_id": chunk.get("source_id"),
                "doc_type": chunk.get("doc_type"),
                "title": chunk.get("title"),
                "score": round(float(scores[index]), 6),
                "section_path": chunk.get("section_path") or [],
                "content_preview": str(records[index]["content_preview"])[:PREVIEW_MAX_CHARS],
            }
        )
    return rows


def evaluate_ranked(
    case: dict[str, Any],
    ranked_indices: list[int],
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    expected_source = case.get("expected_source_id")
    expected_doc_type = case.get("expected_doc_type")
    expected_keywords = list(case.get("expected_keywords") or [])
    expected_exact_terms = list(case.get("expected_exact_terms") or [])
    banned_source_ids = set(case.get("banned_source_ids") or [])
    source_ids = [str(records[index]["chunk"].get("source_id") or "") for index in ranked_indices]
    doc_types = [str(records[index]["chunk"].get("doc_type") or "") for index in ranked_indices]
    retrieved_text = " ".join(
        f"{records[index]['search_text']} {records[index]['chunk'].get('title') or ''}"
        for index in ranked_indices
    )
    return {
        "source_hit": bool(expected_source) and expected_source in source_ids,
        "doc_type_hit": bool(expected_doc_type) and expected_doc_type in doc_types,
        "keyword_hit": not expected_keywords or contains_any(retrieved_text, expected_keywords),
        "exact_match_hit": bool(case.get("requires_exact_match"))
        and contains_any(retrieved_text, expected_exact_terms),
        "banned_source_returned": bool(banned_source_ids.intersection(source_ids)),
        "top1_source_id": source_ids[0] if source_ids else None,
        "mrr_source": round(compute_mrr(source_ids, expected_source), 4),
    }


def rerank_effect(before: dict[str, Any], after: dict[str, Any]) -> str:
    before_top1 = bool(before["top1_source_id"] == before.get("expected_source_id"))
    after_top1 = bool(after["top1_source_id"] == after.get("expected_source_id"))
    before_mrr = float(before["mrr_source"])
    after_mrr = float(after["mrr_source"])
    if after_top1 and not before_top1:
        return "improved"
    if before_top1 and not after_top1:
        return "degraded"
    if after_mrr > before_mrr:
        return "improved"
    if after_mrr < before_mrr:
        return "degraded"
    return "unchanged"


def predict_reranker_scores(
    model: Any,
    query: str,
    candidate_indices: list[int],
    records: list[dict[str, Any]],
    batch_size: int,
) -> np.ndarray:
    pairs = [(query, records[index]["text"]) for index in candidate_indices]
    scores = model.predict(pairs, batch_size=batch_size, show_progress_bar=False)
    return np.asarray(scores, dtype=np.float32)


def rate(values: list[bool]) -> float:
    return round(sum(1 for value in values if value) / len(values), 4) if values else 0.0


def average(values: list[float]) -> float:
    return round(sum(values) / len(values), 4) if values else 0.0


def metrics_for_results(results: list[dict[str, Any]], prefix: str) -> dict[str, Any]:
    positive = [row for row in results if row.get("expected_source_id")]
    exact_required = [row for row in results if row.get("requires_exact_match")]
    code_api = [row for row in results if row.get("query_type") == "code_api_config"]
    return {
        "case_count": len(results),
        "source_hit_at_k": rate([row[f"{prefix}_source_hit"] for row in positive]),
        "top1_source_hit": rate(
            [row[f"{prefix}_top1_source_id"] == row["expected_source_id"] for row in positive]
        ),
        "mrr_source": average([float(row[f"{prefix}_mrr_source"]) for row in positive]),
        "keyword_hit_at_k": rate([row[f"{prefix}_keyword_hit"] for row in positive]),
        "exact_match_hit_at_k": rate([row[f"{prefix}_exact_match_hit"] for row in exact_required]),
        "code_api_case_hit_at_k": rate([row[f"{prefix}_source_hit"] for row in code_api]),
        "banned_source_result_count": sum(
            1 for row in results if row.get(f"{prefix}_banned_source_returned")
        ),
    }


def grouped_metrics(results: list[dict[str, Any]], prefix: str) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in results:
        grouped[str(row.get("query_type") or "unknown")].append(row)
    return {
        query_type: metrics_for_results(rows, prefix)
        for query_type, rows in sorted(grouped.items())
    }


def query_type_metric(metrics: dict[str, Any], query_type: str, metric_name: str) -> float:
    by_query_type = metrics.get("by_query_type", {})
    query_metrics = by_query_type.get(query_type, {}) if isinstance(by_query_type, dict) else {}
    value = query_metrics.get(metric_name, 0.0) if isinstance(query_metrics, dict) else 0.0
    return float(value) if isinstance(value, (int, float)) else 0.0


def run_eval(args: argparse.Namespace, reranker: Any, load_report: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    cases = ensure_reranker_cases(args.cases, args.source_cases)
    if args.limit_cases > 0:
        cases = cases[: args.limit_cases]
    chunks = load_jsonl(args.chunk_manifest)
    eligible_count = sum(1 for chunk in chunks if is_allowed_chunk(chunk))
    records, selected_count = build_records(chunks, limit=args.limit_chunks)
    if not records:
        raise RuntimeError("No reviewed chunk text could be recovered for reranker evaluation.")

    dense_model = load_dense_model(args.dense_model_alias, args.device)
    texts = [record["text"] for record in records]
    tokenized_docs = [tokenize(record["search_text"]) for record in records]
    bm25 = BM25Index(tokenized_docs)
    doc_embeddings = encode_texts(
        dense_model,
        args.dense_model_alias,
        texts,
        is_query=False,
        batch_size=max(1, args.batch_size),
    )
    query_embeddings = encode_texts(
        dense_model,
        args.dense_model_alias,
        [case["query"] for case in cases],
        is_query=True,
        batch_size=max(1, args.batch_size),
    )
    dense_matrix = query_embeddings @ doc_embeddings.T

    results: list[dict[str, Any]] = []
    rerank_latencies: list[float] = []
    for case_index, case in enumerate(cases):
        dense_scores = normalize_scores(dense_matrix[case_index])
        sparse_scores = bm25.score(case["query"])
        exact, metadata = exact_scores(case["query"], records)
        scores_by_strategy = strategy_scores(dense_scores, sparse_scores, exact, metadata)
        candidate_indices = build_candidate_indices(scores_by_strategy, args.candidate_pool_size)
        before_ranked = candidate_indices[: args.top_k]
        before_eval = evaluate_ranked(case, before_ranked, records)

        start = time.perf_counter()
        reranker_scores = predict_reranker_scores(
            reranker,
            str(case["query"]),
            candidate_indices,
            records,
            max(1, args.batch_size),
        )
        rerank_latencies.append((time.perf_counter() - start) * 1000)
        candidate_score_map = np.full(len(records), -math.inf, dtype=np.float32)
        for index, score in zip(candidate_indices, reranker_scores, strict=True):
            candidate_score_map[index] = float(score)
        sorted_candidate_indices = [
            candidate_indices[index]
            for index in np.argsort(reranker_scores)[::-1][: args.top_k]
        ]
        after_eval = evaluate_ranked(case, sorted_candidate_indices, records)
        expected_source = case.get("expected_source_id")
        candidate_source_ids = [
            str(records[index]["chunk"].get("source_id") or "") for index in candidate_indices
        ]
        row_before = dict(before_eval)
        row_after = dict(after_eval)
        row_before["expected_source_id"] = expected_source
        row_after["expected_source_id"] = expected_source
        effect = rerank_effect(row_before, row_after)
        results.append(
            {
                "case_id": case["case_id"],
                "source_case_id": case.get("source_case_id"),
                "query": case["query"],
                "query_type": case["query_type"],
                "reranker_alias": args.reranker_alias,
                "reranker_model_path_alias": RERANKER_ALIASES[args.reranker_alias],
                "dense_model_alias": args.dense_model_alias,
                "dense_model_path_alias": DENSE_MODEL_ALIASES[args.dense_model_alias],
                "candidate_pool_size": args.candidate_pool_size,
                "top_k": args.top_k,
                "expected_source_id": expected_source,
                "expected_doc_type": case.get("expected_doc_type"),
                "expected_keywords": case.get("expected_keywords") or [],
                "requires_exact_match": bool(case.get("requires_exact_match")),
                "candidate_pool_source_hit": bool(expected_source)
                and expected_source in candidate_source_ids,
                "candidate_pool_count": len(candidate_indices),
                "before_source_hit": before_eval["source_hit"],
                "after_source_hit": after_eval["source_hit"],
                "before_keyword_hit": before_eval["keyword_hit"],
                "after_keyword_hit": after_eval["keyword_hit"],
                "before_exact_match_hit": before_eval["exact_match_hit"],
                "after_exact_match_hit": after_eval["exact_match_hit"],
                "before_banned_source_returned": before_eval["banned_source_returned"],
                "after_banned_source_returned": after_eval["banned_source_returned"],
                "before_top1_source_id": before_eval["top1_source_id"],
                "after_top1_source_id": after_eval["top1_source_id"],
                "before_mrr_source": before_eval["mrr_source"],
                "after_mrr_source": after_eval["mrr_source"],
                "rerank_effect": effect,
                "avg_latency_ms": round(rerank_latencies[-1], 4),
                "before_retrieved": public_ranked_rows(before_ranked, records, scores_by_strategy["hybrid_weighted"]),
                "after_retrieved": public_ranked_rows(
                    sorted_candidate_indices,
                    records,
                    candidate_score_map,
                ),
            }
        )

    before_metrics = {
        **metrics_for_results(results, "before"),
        "by_query_type": grouped_metrics(results, "before"),
    }
    after_metrics = {
        **metrics_for_results(results, "after"),
        "by_query_type": grouped_metrics(results, "after"),
    }
    possible = [row for row in results if row["candidate_pool_source_hit"]]
    summary = {
        "phase": "6D-4",
        "case_count": len(cases),
        "query_type_distribution": dict(sorted(Counter(row["query_type"] for row in cases).items())),
        "reviewed_chunk_eligible_count": eligible_count,
        "reviewed_chunk_selected_count": selected_count,
        "reviewed_chunk_recovered_count": len(records),
        "reranker_alias": args.reranker_alias,
        "reranker_model_path_alias": RERANKER_ALIASES[args.reranker_alias],
        "dense_model_alias": args.dense_model_alias,
        "dense_model_path_alias": DENSE_MODEL_ALIASES[args.dense_model_alias],
        "candidate_pool_size": args.candidate_pool_size,
        "candidate_pool_sources": CANDIDATE_STRATEGIES,
        "top_k": args.top_k,
        "batch_size": args.batch_size,
        "device": args.device,
        "smoke_test": bool(args.smoke_test),
        "reranker_load_success": bool(load_report.get("load_success")),
        "skipped_rerank_eval": False,
        "before_rerank": before_metrics,
        "after_rerank": after_metrics,
        "candidate_pool_source_hit_at_k": rate([row["candidate_pool_source_hit"] for row in results if row.get("expected_source_id")]),
        "reranker_possible_improvement_count": len(possible),
        "reranker_improved_count": sum(1 for row in results if row["rerank_effect"] == "improved"),
        "reranker_degraded_count": sum(1 for row in results if row["rerank_effect"] == "degraded"),
        "reranker_unchanged_count": sum(1 for row in results if row["rerank_effect"] == "unchanged"),
        "banned_source_result_count": after_metrics["banned_source_result_count"],
        "avg_rerank_latency_ms": average(rerank_latencies),
        "focus_query_type_deltas": {
            query_type: {
                "source_hit_at_k_delta": round(
                    query_type_metric(after_metrics, query_type, "source_hit_at_k")
                    - query_type_metric(before_metrics, query_type, "source_hit_at_k"),
                    4,
                ),
                "top1_source_hit_delta": round(
                    query_type_metric(after_metrics, query_type, "top1_source_hit")
                    - query_type_metric(before_metrics, query_type, "top1_source_hit"),
                    4,
                ),
                "mrr_source_delta": round(
                    query_type_metric(after_metrics, query_type, "mrr_source")
                    - query_type_metric(before_metrics, query_type, "mrr_source"),
                    4,
                ),
            }
            for query_type in [
                "exact_metadata_lookup",
                "code_api_config",
                "short_keyword",
                "phase6c_bad_case_regression",
            ]
        },
        "calls_llm": False,
        "writes_chroma": False,
        "writes_production_chroma_collection": False,
        "modifies_agent": False,
        "modifies_api": False,
        "loads_embedding_model": True,
        "loads_reranker_model": True,
        "hpc_full_benchmark_status": "planned_not_run",
    }
    return results, summary


def write_skipped_summary(args: argparse.Namespace, load_report: dict[str, Any]) -> None:
    cases = ensure_reranker_cases(args.cases, args.source_cases)
    summary = {
        "phase": "6D-4",
        "case_count": len(cases),
        "query_type_distribution": dict(sorted(Counter(row["query_type"] for row in cases).items())),
        "reranker_alias": args.reranker_alias,
        "reranker_model_path_alias": RERANKER_ALIASES[args.reranker_alias],
        "dense_model_alias": args.dense_model_alias,
        "dense_model_path_alias": DENSE_MODEL_ALIASES[args.dense_model_alias],
        "candidate_pool_size": args.candidate_pool_size,
        "top_k": args.top_k,
        "reranker_load_success": bool(load_report.get("load_success")),
        "skipped_rerank_eval": True,
        "skip_reason": "load_only_requested" if load_report.get("load_success") else "reranker_load_failed",
        "error_summary": load_report.get("error_summary"),
        "calls_llm": False,
        "writes_chroma": False,
        "writes_production_chroma_collection": False,
        "modifies_agent": False,
        "modifies_api": False,
        "loads_embedding_model": False,
        "loads_reranker_model": bool(load_report.get("load_success")),
        "hpc_full_benchmark_status": "planned_not_run",
    }
    write_json(args.summary, summary)


def main() -> None:
    args = parse_args()
    ensure_reranker_cases(args.cases, args.source_cases)
    reranker, load_report = load_reranker_with_report(args)
    if args.load_only or reranker is None:
        write_skipped_summary(args, load_report)
        print(f"reranker_alias={args.reranker_alias}")
        print(f"load_success={load_report['load_success']}")
        if load_report.get("error_summary"):
            print(f"error_summary={load_report['error_summary']}")
        print(f"load_report={args.load_report}")
        print(f"summary={args.summary}")
        return

    results, summary = run_eval(args, reranker, load_report)
    write_jsonl(args.results, results)
    write_json(args.summary, summary)
    print(f"case_count={summary['case_count']}")
    print(f"reviewed_chunk_recovered_count={summary['reviewed_chunk_recovered_count']}")
    print(f"reranker_alias={summary['reranker_alias']}")
    print(f"dense_model_alias={summary['dense_model_alias']}")
    print(f"candidate_pool_source_hit_at_k={summary['candidate_pool_source_hit_at_k']}")
    print(
        "before_rerank: "
        f"source_hit_at_k={summary['before_rerank']['source_hit_at_k']}, "
        f"top1_source_hit={summary['before_rerank']['top1_source_hit']}, "
        f"mrr_source={summary['before_rerank']['mrr_source']}"
    )
    print(
        "after_rerank: "
        f"source_hit_at_k={summary['after_rerank']['source_hit_at_k']}, "
        f"top1_source_hit={summary['after_rerank']['top1_source_hit']}, "
        f"mrr_source={summary['after_rerank']['mrr_source']}"
    )
    print(
        "rerank_effect: "
        f"improved={summary['reranker_improved_count']}, "
        f"degraded={summary['reranker_degraded_count']}, "
        f"unchanged={summary['reranker_unchanged_count']}"
    )
    print(f"banned_source_result_count={summary['banned_source_result_count']}")
    print(f"avg_rerank_latency_ms={summary['avg_rerank_latency_ms']}")
    print(f"results={args.results}")
    print(f"summary={args.summary}")


if __name__ == "__main__":
    main()
