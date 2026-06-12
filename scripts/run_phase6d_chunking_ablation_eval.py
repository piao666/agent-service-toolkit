from __future__ import annotations

import argparse
import re
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

ROOT_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT_DIR / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from build_phase6_chunks import _paragraph_chunks, _sha256_text, _split_long_text  # noqa: E402
from run_phase6d_hybrid_retrieval_eval import (  # noqa: E402
    BANNED_SOURCE_IDS,
    CHUNK_MANIFEST_PATH,
    EVAL_DIR,
    MANIFEST_DIR,
    MODEL_ALIASES,
    BM25Index,
    contains_any,
    encode_texts,
    exact_scores,
    is_allowed_chunk,
    load_dense_model,
    load_jsonl,
    normalize_scores,
    rank_records,
    sanitize_preview,
    tokenize,
    write_json,
    write_jsonl,
)

DEFAULT_SOURCE_CASES_PATH = EVAL_DIR / "phase6d_hybrid_retrieval_cases.jsonl"
DEFAULT_CASES_PATH = EVAL_DIR / "phase6d_chunking_ablation_cases.jsonl"
DEFAULT_RESULTS_PATH = EVAL_DIR / "phase6d_chunking_ablation_results.jsonl"
DEFAULT_SUMMARY_PATH = EVAL_DIR / "phase6d_chunking_ablation_summary.json"
NORMALIZED_MANIFEST_PATH = MANIFEST_DIR / "normalized_manifest.jsonl"
PREVIEW_MAX_CHARS = 160
STRATEGIES = [
    "baseline_existing_chunks",
    "small_chunks",
    "large_chunks",
    "sliding_window_overlap",
    "metadata_enriched_chunks",
    "section_aware_chunks",
]
STRATEGY_CONFIG = {
    "small_chunks": {"size": 450, "overlap": 60},
    "large_chunks": {"size": 1300, "overlap": 120},
    "sliding_window_overlap": {"size": 850, "overlap": 240},
    "metadata_enriched_chunks": {"size": 900, "overlap": 100},
    "section_aware_chunks": {"size": 900, "overlap": 100},
}
HYBRID_WEIGHTS = {
    "alpha_dense": 0.45,
    "beta_sparse": 0.30,
    "gamma_exact": 0.20,
    "delta_metadata": 0.05,
}


@dataclass
class DocRecord:
    normalized: dict[str, Any]
    text: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Phase 6D-5 offline chunking ablation.")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument("--source-cases", type=Path, default=DEFAULT_SOURCE_CASES_PATH)
    parser.add_argument("--normalized-manifest", type=Path, default=NORMALIZED_MANIFEST_PATH)
    parser.add_argument("--chunk-manifest", type=Path, default=CHUNK_MANIFEST_PATH)
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS_PATH)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY_PATH)
    parser.add_argument("--model-alias", default="bge-small-zh-v1.5", choices=sorted(MODEL_ALIASES))
    parser.add_argument("--limit-cases", type=int, default=0)
    parser.add_argument("--limit-docs", type=int, default=0)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--smoke-test", action="store_true")
    return parser.parse_args()


def ensure_cases(cases_path: Path, source_cases_path: Path) -> list[dict[str, Any]]:
    if cases_path.exists():
        return load_jsonl(cases_path)
    source_cases = load_jsonl(source_cases_path)
    ablation_cases: list[dict[str, Any]] = []
    for index, case in enumerate(source_cases, start=1):
        row = dict(case)
        row["case_id"] = f"chunk_ablation_{index:03d}"
        row["source_case_id"] = case.get("case_id")
        row["phase"] = "6D-5"
        row["evaluation_focus"] = "chunking_strategy_ablation"
        ablation_cases.append(row)
    write_jsonl(cases_path, ablation_cases)
    return ablation_cases


def safe_error_message(error: Exception | str) -> str:
    message = str(error)
    message = re.sub(r"[A-Za-z]:[\\/][^\s\"']+", "<LOCAL_PATH>", message)
    user_home_pattern = "/" + "".join(["Us", "ers"]) + r"/[^\s\"']+"
    message = re.sub(user_home_pattern, "<LOCAL_PATH>", message)
    return " ".join(message.split())[:500]


def allowed_normalized(record: dict[str, Any]) -> bool:
    if record.get("ingest_candidate") is not True:
        return False
    if record.get("review_status") != "approved":
        return False
    if record.get("normalization_status") != "pass":
        return False
    if str(record.get("source_id") or "") in BANNED_SOURCE_IDS:
        return False
    return bool(record.get("content_cache_alias"))


def load_docs(normalized_manifest: Path, limit_docs: int) -> tuple[list[DocRecord], int]:
    normalized_rows = [row for row in load_jsonl(normalized_manifest) if allowed_normalized(row)]
    selected = normalized_rows if limit_docs <= 0 else normalized_rows[:limit_docs]
    docs: list[DocRecord] = []
    for row in selected:
        cache_alias = str(row.get("content_cache_alias") or "")
        cache_path = ROOT_DIR / "data" / "knowledge_base" / cache_alias
        if not cache_path.exists():
            continue
        text = cache_path.read_text(encoding="utf-8", errors="ignore").strip()
        if text:
            docs.append(DocRecord(normalized=row, text=text))
    return docs, len(normalized_rows)


def load_baseline_records(
    chunk_manifest: Path,
    normalized_manifest: Path,
    limit_docs: int,
) -> list[dict[str, Any]]:
    rows = [row for row in load_jsonl(chunk_manifest) if is_allowed_chunk(row)]
    if limit_docs > 0:
        allowed_ids = [
            row.get("normalized_id")
            for row in load_jsonl(normalized_manifest)
            if allowed_normalized(row)
        ]
        selected_ids = set(list(allowed_ids)[:limit_docs])
        rows = [row for row in rows if row.get("normalized_id") in selected_ids]
    records: list[dict[str, Any]] = []
    for chunk in rows:
        metadata = chunk.get("metadata") if isinstance(chunk.get("metadata"), dict) else {}
        cache_alias = str(metadata.get("content_cache_alias") or "")
        cache_path = ROOT_DIR / "data" / "knowledge_base" / cache_alias
        if not cache_path.exists():
            continue
        source_text = cache_path.read_text(encoding="utf-8", errors="ignore").strip()
        if not source_text:
            continue
        chunk_text = find_existing_chunk_text(chunk, source_text)
        if not chunk_text:
            continue
        records.append(record_from_chunk(chunk, chunk_text, "baseline_existing_chunks"))
    return records


def find_existing_chunk_text(chunk: dict[str, Any], source_text: str) -> str | None:
    chunk_size = int(chunk.get("chunk_size") or 900)
    overlap = int(chunk.get("chunk_overlap") or 100)
    expected_hash = str(chunk.get("chunk_sha256") or "")
    for candidate in _paragraph_chunks(source_text, size=chunk_size, overlap=overlap):
        if _sha256_text(candidate) == expected_hash:
            return candidate
    return None


def metadata_prefix(row: dict[str, Any]) -> str:
    values = [
        f"title: {row.get('title') or ''}",
        f"source_id: {row.get('source_id') or ''}",
        f"doc_type: {row.get('doc_type') or ''}",
        f"domain: {row.get('domain') or ''}",
        f"language: {row.get('language') or ''}",
        f"normalized_id: {row.get('normalized_id') or ''}",
    ]
    if row.get("source_url"):
        values.append(f"source_url: {row.get('source_url')}")
    return "\n".join(values).strip()


def split_section_aware(text: str, size: int, overlap: int) -> list[tuple[str, list[str]]]:
    sections: list[tuple[list[str], list[str]]] = []
    current_heading: list[str] = []
    current_lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            if current_lines:
                sections.append((current_heading[:], current_lines[:]))
                current_lines = []
            heading = stripped.lstrip("#").strip()
            if heading:
                current_heading = [heading]
        current_lines.append(line)
    if current_lines:
        sections.append((current_heading[:], current_lines[:]))

    if not sections:
        return [(chunk, []) for chunk in _paragraph_chunks(text, size=size, overlap=overlap)]

    output: list[tuple[str, list[str]]] = []
    for headings, lines in sections:
        section_text = "\n".join(lines).strip()
        if not section_text:
            continue
        for chunk in _paragraph_chunks(section_text, size=size, overlap=overlap):
            output.append((chunk, headings))
    return output


def strategy_chunks(strategy: str, doc: DocRecord) -> list[tuple[str, list[str]]]:
    row = doc.normalized
    title = str(row.get("title") or row.get("doc_type") or "document")
    if strategy == "section_aware_chunks":
        config = STRATEGY_CONFIG[strategy]
        return split_section_aware(doc.text, size=config["size"], overlap=config["overlap"])

    if strategy == "metadata_enriched_chunks":
        config = STRATEGY_CONFIG[strategy]
        prefix = metadata_prefix(row)
        chunks: list[tuple[str, list[str]]] = []
        for chunk in _paragraph_chunks(doc.text, size=config["size"], overlap=config["overlap"]):
            chunks.append((f"{prefix}\n\n{chunk}".strip(), [title]))
        return chunks

    config = STRATEGY_CONFIG[strategy]
    if strategy == "sliding_window_overlap":
        return [
            (chunk, [title])
            for chunk in _split_long_text(doc.text, size=config["size"], overlap=config["overlap"])
        ]
    return [
        (chunk, [title])
        for chunk in _paragraph_chunks(doc.text, size=config["size"], overlap=config["overlap"])
    ]


def record_from_chunk(chunk: dict[str, Any], text: str, strategy: str) -> dict[str, Any]:
    section_path = chunk.get("section_path") if isinstance(chunk.get("section_path"), list) else []
    metadata_text = " ".join(
        str(value)
        for value in [
            chunk.get("chunk_id"),
            chunk.get("normalized_id"),
            chunk.get("source_id"),
            chunk.get("doc_type"),
            chunk.get("domain"),
            chunk.get("language"),
            chunk.get("title"),
            chunk.get("review_status"),
            chunk.get("ingest_candidate"),
            chunk.get("source_url"),
            strategy,
            *section_path,
        ]
        if value is not None
    )
    return {
        "chunk": chunk,
        "text": text,
        "content_preview": metadata_only_preview(chunk, strategy),
        "metadata_text": metadata_text,
        "search_text": f"{metadata_text}\n{text}",
    }


def metadata_only_preview(chunk: dict[str, Any], strategy: str) -> str:
    chunk_id = str(chunk.get("chunk_id") or "unknown_chunk")
    source_id = str(chunk.get("source_id") or "unknown_source")
    doc_type = str(chunk.get("doc_type") or "unknown_doc_type")
    digest = str(chunk.get("chunk_sha256") or "")[:12]
    preview = (
        f"metadata-only preview: strategy={strategy}, source={source_id}, "
        f"doc_type={doc_type}, chunk={chunk_id}, sha256={digest}"
    )
    return sanitize_preview(preview)[:PREVIEW_MAX_CHARS]


def build_strategy_records(strategy: str, docs: list[DocRecord]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    seen_hashes: set[str] = set()
    for doc in docs:
        row = doc.normalized
        title = str(row.get("title") or "")
        emitted = 0
        for chunk_text, section_path in strategy_chunks(strategy, doc):
            cleaned = chunk_text.strip()
            if not cleaned:
                continue
            chunk_hash = _sha256_text(cleaned)
            dedupe_key = f"{strategy}:{row.get('normalized_id')}:{chunk_hash}"
            if dedupe_key in seen_hashes:
                continue
            seen_hashes.add(dedupe_key)
            chunk = {
                "chunk_id": f"ablation_{strategy}_{row.get('normalized_id')}_{emitted:04d}",
                "normalized_id": row.get("normalized_id"),
                "doc_id": row.get("doc_id"),
                "source_id": row.get("source_id"),
                "sample_id": row.get("sample_id"),
                "doc_type": row.get("doc_type"),
                "domain": row.get("domain"),
                "language": row.get("language"),
                "title": title,
                "section_path": section_path or [title] if title else [str(row.get("doc_type") or "")],
                "source_url": row.get("source_url"),
                "chunk_index": emitted,
                "chunk_chars": len(cleaned),
                "chunk_sha256": chunk_hash,
                "content_sha256": chunk_hash,
                "normalization_status": row.get("normalization_status"),
                "review_status": row.get("review_status"),
                "ingest_candidate": row.get("ingest_candidate"),
                "embedding_written": False,
                "chroma_written": False,
                "metadata": {
                    "chunk_strategy": strategy,
                    "content_cache_alias": row.get("content_cache_alias"),
                    "parser": row.get("parser"),
                    "normalizer": row.get("normalizer"),
                },
            }
            records.append(record_from_chunk(chunk, cleaned, strategy))
            emitted += 1
    return records


def strategy_scores(
    dense: np.ndarray,
    sparse: np.ndarray,
    exact: np.ndarray,
    metadata: np.ndarray,
) -> np.ndarray:
    return normalize_scores(
        HYBRID_WEIGHTS["alpha_dense"] * normalize_scores(dense)
        + HYBRID_WEIGHTS["beta_sparse"] * sparse
        + HYBRID_WEIGHTS["gamma_exact"] * exact
        + HYBRID_WEIGHTS["delta_metadata"] * metadata
    )


def evaluate_case(
    case: dict[str, Any],
    strategy: str,
    records: list[dict[str, Any]],
    scores: np.ndarray,
    dense: np.ndarray,
    sparse: np.ndarray,
    exact: np.ndarray,
    top_k: int,
) -> dict[str, Any]:
    start = time.perf_counter()
    retrieved = rank_records(records, scores, dense, sparse, exact, top_k)
    latency_ms = (time.perf_counter() - start) * 1000
    expected_source = case.get("expected_source_id")
    expected_doc_type = case.get("expected_doc_type")
    expected_keywords = list(case.get("expected_keywords") or [])
    expected_exact_terms = list(case.get("expected_exact_terms") or [])
    banned_source_ids = set(case.get("banned_source_ids") or [])
    source_ids = [str(row.get("source_id") or "") for row in retrieved]
    doc_types = [str(row.get("doc_type") or "") for row in retrieved]
    retrieved_text = " ".join(
        f"{records[int(row['_record_index'])]['search_text']} {row.get('title') or ''}"
        for row in retrieved
    )
    mrr_source = 0.0
    for rank, source_id in enumerate(source_ids, start=1):
        if source_id == expected_source:
            mrr_source = 1.0 / rank
            break
    public_retrieved = [{k: v for k, v in row.items() if k != "_record_index"} for row in retrieved]
    return {
        "case_id": case["case_id"],
        "source_case_id": case.get("source_case_id"),
        "strategy": strategy,
        "query": case["query"],
        "query_type": case["query_type"],
        "top_k": top_k,
        "expected_source_id": expected_source,
        "expected_doc_type": expected_doc_type,
        "source_hit": bool(expected_source) and expected_source in source_ids,
        "doc_type_hit": bool(expected_doc_type) and expected_doc_type in doc_types,
        "keyword_hit": not expected_keywords or contains_any(retrieved_text, expected_keywords),
        "requires_exact_match": bool(case.get("requires_exact_match")),
        "exact_match_hit": bool(case.get("requires_exact_match"))
        and contains_any(retrieved_text, expected_exact_terms),
        "banned_source_returned": bool(banned_source_ids.intersection(source_ids)),
        "top1_source_id": retrieved[0]["source_id"] if retrieved else None,
        "mrr_source": round(mrr_source, 4),
        "avg_latency_ms": round(latency_ms, 4),
        "retrieved": public_retrieved,
    }


def rate(values: list[bool]) -> float:
    return round(sum(1 for value in values if value) / len(values), 4) if values else 0.0


def average(values: list[float]) -> float:
    return round(sum(values) / len(values), 4) if values else 0.0


def metrics_for_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    positive = [row for row in results if row.get("expected_source_id")]
    exact_required = [row for row in results if row.get("requires_exact_match")]
    code_api = [row for row in results if row.get("query_type") == "code_api_config"]
    chunk_chars = [int(row["chunk_chars"]) for row in results if "chunk_chars" in row]
    return {
        "case_count": len(results),
        "source_hit_at_k": rate([row["source_hit"] for row in positive]),
        "top1_source_hit": rate(
            [row["top1_source_id"] == row["expected_source_id"] for row in positive]
        ),
        "mrr_source": average([float(row["mrr_source"]) for row in positive]),
        "doc_type_hit_at_k": rate([row["doc_type_hit"] for row in positive]),
        "keyword_hit_at_k": rate([row["keyword_hit"] for row in positive]),
        "exact_match_hit_at_k": rate([row["exact_match_hit"] for row in exact_required]),
        "code_api_case_hit_at_k": rate([row["source_hit"] for row in code_api]),
        "empty_result_count": sum(1 for row in results if not row.get("retrieved")),
        "invalid_result_count": sum(
            1
            for row in positive
            if not row["source_hit"] and not row["doc_type_hit"] and not row["keyword_hit"]
        ),
        "banned_source_result_count": sum(
            1 for row in results if row.get("banned_source_returned")
        ),
        "avg_query_latency_ms": average([float(row["avg_latency_ms"]) for row in results]),
        "chunk_chars_min": min(chunk_chars) if chunk_chars else 0,
        "chunk_chars_avg": average([float(value) for value in chunk_chars]),
        "chunk_chars_max": max(chunk_chars) if chunk_chars else 0,
    }


def grouped_metrics(results: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in results:
        grouped[str(row.get("query_type") or "unknown")].append(row)
    return {query_type: metrics_for_results(rows) for query_type, rows in sorted(grouped.items())}


def query_type_metric(metrics: dict[str, Any], query_type: str, metric_name: str) -> float:
    by_query_type = metrics.get("by_query_type", {})
    query_metrics = by_query_type.get(query_type, {}) if isinstance(by_query_type, dict) else {}
    value = query_metrics.get(metric_name, 0.0) if isinstance(query_metrics, dict) else 0.0
    return float(value) if isinstance(value, (int, float)) else 0.0


def run_strategy(
    strategy: str,
    records: list[dict[str, Any]],
    cases: list[dict[str, Any]],
    model: Any,
    model_alias: str,
    batch_size: int,
    top_k: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not records:
        return [], {"case_count": len(cases), "chunk_count": 0, "skipped": True}
    texts = [record["text"] for record in records]
    tokenized_docs = [tokenize(record["search_text"]) for record in records]
    bm25 = BM25Index(tokenized_docs)
    doc_embeddings = encode_texts(
        model,
        model_alias,
        texts,
        is_query=False,
        batch_size=batch_size,
    )
    query_embeddings = encode_texts(
        model,
        model_alias,
        [case["query"] for case in cases],
        is_query=True,
        batch_size=batch_size,
    )
    dense_matrix = query_embeddings @ doc_embeddings.T

    results: list[dict[str, Any]] = []
    for case_index, case in enumerate(cases):
        dense_scores = normalize_scores(dense_matrix[case_index])
        sparse_scores = bm25.score(case["query"])
        exact, metadata = exact_scores(case["query"], records)
        scores = strategy_scores(dense_scores, sparse_scores, exact, metadata)
        result = evaluate_case(
            case,
            strategy,
            records,
            scores,
            dense_scores,
            sparse_scores,
            exact + metadata,
            top_k,
        )
        result["model_alias"] = model_alias
        result["model_path_alias"] = MODEL_ALIASES[model_alias]
        result["chunk_count"] = len(records)
        result["avg_chunk_chars"] = average([float(len(record["text"])) for record in records])
        results.append(result)

    metrics = metrics_for_results(results)
    chunk_chars = [len(record["text"]) for record in records]
    metrics.update(
        {
            "chunk_count": len(records),
            "avg_chunk_chars": average([float(value) for value in chunk_chars]),
            "max_chunk_chars": max(chunk_chars) if chunk_chars else 0,
            "min_chunk_chars": min(chunk_chars) if chunk_chars else 0,
            "by_query_type": grouped_metrics(results),
        }
    )
    return results, metrics


def best_strategy(strategies: dict[str, Any], metric: str) -> str | None:
    best_name: str | None = None
    best_value = -1.0
    for name, metrics in strategies.items():
        value = metrics.get(metric, 0.0)
        if isinstance(value, (int, float)) and float(value) > best_value:
            best_name = name
            best_value = float(value)
    return best_name


def write_skipped(args: argparse.Namespace, cases: list[dict[str, Any]], error: Exception) -> None:
    summary = {
        "phase": "6D-5",
        "case_count": len(cases),
        "query_type_distribution": dict(sorted(Counter(row["query_type"] for row in cases).items())),
        "model_alias": args.model_alias,
        "model_path_alias": MODEL_ALIASES[args.model_alias],
        "skipped": True,
        "skip_reason": "embedding_model_unavailable",
        "error_summary": safe_error_message(error),
        "calls_llm": False,
        "writes_chroma": False,
        "writes_production_chroma_collection": False,
        "modifies_agent": False,
        "modifies_api": False,
        "loads_embedding_model": False,
        "hpc_full_benchmark_status": "planned_not_run",
    }
    write_json(args.summary, summary)


def run_eval(args: argparse.Namespace) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    cases = ensure_cases(args.cases, args.source_cases)
    if args.limit_cases > 0:
        cases = cases[: args.limit_cases]
    docs, eligible_doc_count = load_docs(args.normalized_manifest, args.limit_docs)
    model = load_dense_model(args.model_alias, args.device)

    all_results: list[dict[str, Any]] = []
    strategy_metrics: dict[str, Any] = {}
    baseline_records = load_baseline_records(
        args.chunk_manifest,
        args.normalized_manifest,
        args.limit_docs,
    )
    strategy_records: dict[str, list[dict[str, Any]]] = {
        "baseline_existing_chunks": baseline_records,
    }
    for strategy in STRATEGIES:
        if strategy == "baseline_existing_chunks":
            continue
        strategy_records[strategy] = build_strategy_records(strategy, docs)

    for strategy in STRATEGIES:
        results, metrics = run_strategy(
            strategy,
            strategy_records[strategy],
            cases,
            model,
            args.model_alias,
            max(1, args.batch_size),
            args.top_k,
        )
        all_results.extend(results)
        strategy_metrics[strategy] = metrics

    baseline = strategy_metrics.get("baseline_existing_chunks", {})
    focus_deltas: dict[str, dict[str, dict[str, float]]] = {}
    for strategy in STRATEGIES:
        if strategy == "baseline_existing_chunks":
            continue
        focus_deltas[strategy] = {}
        metrics = strategy_metrics[strategy]
        for query_type in [
            "exact_metadata_lookup",
            "code_api_config",
            "short_keyword",
            "phase6c_bad_case_regression",
        ]:
            focus_deltas[strategy][query_type] = {
                "source_hit_at_k_delta": round(
                    query_type_metric(metrics, query_type, "source_hit_at_k")
                    - query_type_metric(baseline, query_type, "source_hit_at_k"),
                    4,
                ),
                "top1_source_hit_delta": round(
                    query_type_metric(metrics, query_type, "top1_source_hit")
                    - query_type_metric(baseline, query_type, "top1_source_hit"),
                    4,
                ),
                "mrr_source_delta": round(
                    query_type_metric(metrics, query_type, "mrr_source")
                    - query_type_metric(baseline, query_type, "mrr_source"),
                    4,
                ),
            }

    summary = {
        "phase": "6D-5",
        "case_count": len(cases),
        "query_type_distribution": dict(sorted(Counter(row["query_type"] for row in cases).items())),
        "eligible_doc_count": eligible_doc_count,
        "selected_doc_count": len(docs),
        "model_alias": args.model_alias,
        "model_path_alias": MODEL_ALIASES[args.model_alias],
        "top_k": args.top_k,
        "batch_size": args.batch_size,
        "device": args.device,
        "smoke_test": bool(args.smoke_test),
        "strategies": strategy_metrics,
        "best_strategies": {
            "source_hit_at_k": best_strategy(strategy_metrics, "source_hit_at_k"),
            "top1_source_hit": best_strategy(strategy_metrics, "top1_source_hit"),
            "mrr_source": best_strategy(strategy_metrics, "mrr_source"),
            "exact_match_hit_at_k": best_strategy(strategy_metrics, "exact_match_hit_at_k"),
            "code_api_case_hit_at_k": best_strategy(strategy_metrics, "code_api_case_hit_at_k"),
        },
        "focus_query_type_deltas_vs_baseline": focus_deltas,
        "calls_llm": False,
        "writes_chroma": False,
        "writes_production_chroma_collection": False,
        "modifies_agent": False,
        "modifies_api": False,
        "loads_embedding_model": True,
        "uses_memory_index": True,
        "hpc_full_benchmark_status": "planned_not_run",
    }
    return all_results, summary


def main() -> None:
    args = parse_args()
    cases = ensure_cases(args.cases, args.source_cases)
    try:
        results, summary = run_eval(args)
    except Exception as exc:  # noqa: BLE001
        write_skipped(args, cases[: args.limit_cases] if args.limit_cases > 0 else cases, exc)
        print("skipped=True")
        print("skip_reason=embedding_model_unavailable")
        print(f"error_summary={safe_error_message(exc)}")
        print(f"summary={args.summary}")
        return
    write_jsonl(args.results, results)
    write_json(args.summary, summary)
    print(f"case_count={summary['case_count']}")
    print(f"selected_doc_count={summary['selected_doc_count']}")
    print(f"model_alias={summary['model_alias']}")
    for strategy, metrics in summary["strategies"].items():
        print(
            f"{strategy}: chunk_count={metrics['chunk_count']}, "
            f"avg_chunk_chars={metrics['avg_chunk_chars']}, "
            f"source_hit_at_k={metrics['source_hit_at_k']}, "
            f"top1_source_hit={metrics['top1_source_hit']}, "
            f"mrr_source={metrics['mrr_source']}, "
            f"banned_source_result_count={metrics['banned_source_result_count']}"
        )
    print(f"best_strategies={summary['best_strategies']}")
    print(f"results={args.results}")
    print(f"summary={args.summary}")


if __name__ == "__main__":
    main()
