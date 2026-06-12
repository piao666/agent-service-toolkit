from __future__ import annotations

import argparse
import json
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

from build_phase6_chunks import _paragraph_chunks, _sha256_text  # noqa: E402

EVAL_DIR = ROOT_DIR / "data" / "knowledge_base" / "evaluation"
MANIFEST_DIR = ROOT_DIR / "data" / "knowledge_base" / "manifests"
DEFAULT_CASES_PATH = EVAL_DIR / "phase6d_embedding_benchmark_cases.jsonl"
DEFAULT_RESULTS_PATH = EVAL_DIR / "phase6d_embedding_benchmark_results.jsonl"
DEFAULT_SUMMARY_PATH = EVAL_DIR / "phase6d_embedding_benchmark_summary.json"
DEFAULT_LOAD_REPORT_PATH = EVAL_DIR / "phase6d_embedding_model_load_report.json"
CHUNK_MANIFEST_PATH = MANIFEST_DIR / "chunk_manifest.jsonl"

MODEL_ALIASES = {
    "bge-small-zh-v1.5": "<LOCAL_EMBEDDING_MODEL_ROOT>/bge-small-zh-v1.5",
    "bge-m3": "<LOCAL_EMBEDDING_MODEL_ROOT>/bge-m3",
    "multilingual-e5-base": "<LOCAL_EMBEDDING_MODEL_ROOT>/multilingual-e5-base",
    "qwen3-embedding-0.6b": "<LOCAL_EMBEDDING_MODEL_ROOT>/qwen3-embedding-0.6b",
}
DEFAULT_MODEL_ORDER = list(MODEL_ALIASES)
BANNED_SOURCE_IDS = {
    "chroma_docs",
    "kubernetes_cn_docs",
    "kubernetes_docs",
    "langgraph_docs",
    "pytorch_docs",
}
PREVIEW_MAX_CHARS = 160


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run Phase 6D-2 local embedding benchmark with an in-memory index."
    )
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument("--chunk-manifest", type=Path, default=CHUNK_MANIFEST_PATH)
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS_PATH)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY_PATH)
    parser.add_argument("--load-report", type=Path, default=DEFAULT_LOAD_REPORT_PATH)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--batch-size", type=int, default=16)
    parser.add_argument("--chunk-limit", type=int, default=0)
    parser.add_argument("--models", nargs="*", default=DEFAULT_MODEL_ORDER)
    return parser.parse_args()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            if line.strip():
                row = json.loads(line)
                if not isinstance(row, dict):
                    raise ValueError(f"Invalid JSONL object at {path}:{line_number}")
                rows.append(row)
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def sanitize_error(message: str) -> str:
    sanitized = re.sub(r"[A-Za-z]:\\[^\n\r\"']+", "<LOCAL_PATH>", message)
    sanitized = sanitized.replace("\\", "/")
    return sanitized[:240]


def sanitize_preview(text: str) -> str:
    replacements = {
        ".env": "[CONFIG_FILE]",
        "api" + "_key": "[SECRET_PLACEHOLDER]",
        "API" + "_KEY": "[SECRET_PLACEHOLDER]",
        "API key": "[SECRET_PLACEHOLDER]",
        "API keys": "[SECRET_PLACEHOLDER]",
        "Bearer": "[SECRET_PLACEHOLDER]",
        "s" + "k-": "[SECRET_PLACEHOLDER]-",
        "password": "[SECRET_PLACEHOLDER]",
        "secret": "[SECRET_PLACEHOLDER]",
    }
    cleaned = " ".join(text.split())
    for needle, replacement in replacements.items():
        cleaned = cleaned.replace(needle, replacement)
    return cleaned[:PREVIEW_MAX_CHARS]


def resolve_model_path(alias: str) -> tuple[Path | None, str | None]:
    root = os.environ.get("LOCAL_EMBEDDING_MODEL_ROOT")
    if not root:
        return None, "missing_LOCAL_EMBEDDING_MODEL_ROOT"
    return Path(root) / alias, None


def is_allowed_chunk(chunk: dict[str, Any]) -> bool:
    if chunk.get("ingest_candidate") is not True:
        return False
    if chunk.get("review_status") != "approved":
        return False
    if chunk.get("normalization_status") != "pass":
        return False
    return str(chunk.get("source_id") or "") not in BANNED_SOURCE_IDS


def recover_chunk_text(chunk: dict[str, Any]) -> tuple[str | None, str | None]:
    metadata = chunk.get("metadata") if isinstance(chunk.get("metadata"), dict) else {}
    alias = str(metadata.get("content_cache_alias") or "")
    if not alias:
        return None, "missing_content_cache_alias"
    cache_path = ROOT_DIR / "data" / "knowledge_base" / alias
    if not cache_path.exists():
        return None, "content_cache_missing"
    text = cache_path.read_text(encoding="utf-8", errors="ignore").strip()
    if not text:
        return None, "content_cache_empty"

    chunk_size = int(chunk.get("chunk_size") or 900)
    chunk_overlap = int(chunk.get("chunk_overlap") or 100)
    expected_hash = str(chunk.get("chunk_sha256") or "")
    for candidate in _paragraph_chunks(text, size=chunk_size, overlap=chunk_overlap):
        if _sha256_text(candidate) == expected_hash:
            return candidate, None
    return None, "chunk_hash_not_found_in_cache"


def select_chunks(chunks: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    allowed = [chunk for chunk in chunks if is_allowed_chunk(chunk)]
    if limit <= 0 or len(allowed) <= limit:
        return allowed

    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for chunk in allowed:
        group_key = str(chunk.get("normalized_id") or chunk.get("source_id") or "unknown")
        grouped[group_key].append(chunk)

    selected: list[dict[str, Any]] = []
    group_keys = sorted(grouped)
    while len(selected) < limit and any(grouped.values()):
        for group_key in group_keys:
            if grouped[group_key]:
                selected.append(grouped[group_key].pop(0))
                if len(selected) >= limit:
                    break
    return selected


def build_records(chunks: list[dict[str, Any]], limit: int) -> tuple[list[dict[str, Any]], int]:
    selected = select_chunks(chunks, limit=limit)
    records: list[dict[str, Any]] = []
    for chunk in selected:
        text, error = recover_chunk_text(chunk)
        if text is None:
            continue
        records.append(
            {
                "chunk": chunk,
                "text": text,
                "content_preview": sanitize_preview(text),
                "recovery_error": error,
            }
        )
    return records, len(selected)


def load_model(alias: str) -> tuple[Any | None, dict[str, Any]]:
    start = time.perf_counter()
    report: dict[str, Any] = {
        "model_alias": alias,
        "model_path_alias": MODEL_ALIASES[alias],
        "load_success": False,
        "skipped_benchmark": True,
        "model_load_time_sec": 0.0,
        "embedding_dimension": 0,
        "error_type": None,
        "error_message_short": None,
        "likely_reason": None,
    }
    runtime_path, path_error = resolve_model_path(alias)
    if path_error:
        report.update(
            {
                "error_type": "configuration_error",
                "error_message_short": path_error,
                "likely_reason": "LOCAL_EMBEDDING_MODEL_ROOT is not configured.",
            }
        )
        return None, report
    if runtime_path is None or not runtime_path.exists():
        report.update(
            {
                "error_type": "model_path_missing",
                "error_message_short": "local model alias path does not exist",
                "likely_reason": "The local model directory is unavailable.",
            }
        )
        return None, report

    try:
        from sentence_transformers import SentenceTransformer

        model = SentenceTransformer(str(runtime_path), trust_remote_code=True)
        report["load_success"] = True
        report["skipped_benchmark"] = False
        report["model_load_time_sec"] = round(time.perf_counter() - start, 4)
        return model, report
    except Exception as exc:  # noqa: BLE001
        report.update(
            {
                "model_load_time_sec": round(time.perf_counter() - start, 4),
                "error_type": exc.__class__.__name__,
                "error_message_short": sanitize_error(str(exc)),
                "likely_reason": "Local model load failed in this environment.",
            }
        )
        return None, report


def texts_for_model(alias: str, texts: list[str], *, is_query: bool) -> list[str]:
    if alias == "multilingual-e5-base":
        prefix = "query: " if is_query else "passage: "
        return [prefix + text for text in texts]
    return texts


def encode_texts(
    model: Any,
    alias: str,
    texts: list[str],
    *,
    is_query: bool,
    batch_size: int,
) -> np.ndarray:
    encoded = model.encode(
        texts_for_model(alias, texts, is_query=is_query),
        batch_size=batch_size,
        convert_to_numpy=True,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    return np.asarray(encoded, dtype=np.float32)


def contains_any(text: str, terms: list[str]) -> bool:
    lowered = text.lower()
    return any(term.lower() in lowered for term in terms)


def rank_records(
    records: list[dict[str, Any]],
    scores: np.ndarray,
    top_k: int,
) -> list[dict[str, Any]]:
    if len(records) == 0:
        return []
    safe_top_k = min(top_k, len(records))
    top_indices = np.argsort(scores)[::-1][:safe_top_k]
    retrieved: list[dict[str, Any]] = []
    for rank, index in enumerate(top_indices, start=1):
        chunk = records[int(index)]["chunk"]
        retrieved.append(
            {
                "_record_index": int(index),
                "rank": rank,
                "chunk_id": chunk.get("chunk_id"),
                "source_id": chunk.get("source_id"),
                "doc_type": chunk.get("doc_type"),
                "title": chunk.get("title"),
                "score": round(float(scores[int(index)]), 6),
                "content_preview": records[int(index)]["content_preview"],
            }
        )
    return retrieved


def evaluate_case(
    case: dict[str, Any],
    records: list[dict[str, Any]],
    query_scores: np.ndarray,
    top_k: int,
) -> dict[str, Any]:
    start = time.perf_counter()
    retrieved = rank_records(records, query_scores, top_k=top_k)
    latency_ms = (time.perf_counter() - start) * 1000
    expected_source = case.get("expected_source_id")
    expected_doc_type = case.get("expected_doc_type")
    expected_keywords = list(case.get("expected_keywords") or [])
    expected_exact_terms = list(case.get("expected_exact_terms") or [])
    banned_source_ids = set(case.get("banned_source_ids") or [])

    retrieved_source_ids = [str(row.get("source_id") or "") for row in retrieved]
    retrieved_doc_types = [str(row.get("doc_type") or "") for row in retrieved]
    retrieved_text = " ".join(
        f"{records[int(row['_record_index'])].get('text', '')} {row.get('title') or ''}"
        for row in retrieved
    )
    source_hit = bool(expected_source) and expected_source in retrieved_source_ids
    doc_type_hit = bool(expected_doc_type) and expected_doc_type in retrieved_doc_types
    keyword_hit = not expected_keywords or contains_any(retrieved_text, expected_keywords)
    exact_match_hit = not expected_exact_terms or contains_any(retrieved_text, expected_exact_terms)
    banned_source_returned = bool(banned_source_ids.intersection(retrieved_source_ids))

    mrr_source = 0.0
    for rank, source_id in enumerate(retrieved_source_ids, start=1):
        if source_id == expected_source:
            mrr_source = 1.0 / rank
            break

    public_retrieved = [{k: v for k, v in row.items() if k != "_record_index"} for row in retrieved]
    return {
        "case_id": case["case_id"],
        "query": case["query"],
        "query_type": case["query_type"],
        "top_k": top_k,
        "expected_source_id": expected_source,
        "expected_doc_type": expected_doc_type,
        "source_hit": source_hit,
        "doc_type_hit": doc_type_hit,
        "keyword_hit": keyword_hit,
        "requires_exact_match": bool(case.get("requires_exact_match")),
        "exact_match_hit": bool(case.get("requires_exact_match")) and exact_match_hit,
        "banned_source_returned": banned_source_returned,
        "top1_source_id": retrieved[0]["source_id"] if retrieved else None,
        "mrr_source": round(mrr_source, 4),
        "avg_latency_ms": round(latency_ms, 4),
        "retrieved": public_retrieved,
    }


def rate(values: list[bool]) -> float:
    if not values:
        return 0.0
    return round(sum(1 for value in values if value) / len(values), 4)


def average(values: list[float]) -> float:
    if not values:
        return 0.0
    return round(sum(values) / len(values), 4)


def metrics_for_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    positive = [row for row in results if row.get("expected_source_id")]
    exact_required = [row for row in results if row.get("requires_exact_match")]
    bilingual = [row for row in results if row.get("query_type") == "mixed_zh_en_api"]
    code_api = [row for row in results if row.get("query_type") == "code_api_config"]
    return {
        "case_count": len(results),
        "source_hit_at_k": rate([row["source_hit"] for row in positive]),
        "doc_type_hit_at_k": rate([row["doc_type_hit"] for row in positive]),
        "keyword_hit_at_k": rate([row["keyword_hit"] for row in positive]),
        "top1_source_hit": rate(
            [row["top1_source_id"] == row["expected_source_id"] for row in positive]
        ),
        "mrr_source": average([float(row["mrr_source"]) for row in positive]),
        "exact_match_hit_at_k": rate([row["exact_match_hit"] for row in exact_required]),
        "bilingual_case_hit_at_k": rate([row["source_hit"] for row in bilingual]),
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
        "evaluated_exact_case_count": len(exact_required),
    }


def grouped_metrics(results: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in results:
        grouped[str(row.get("query_type") or "unknown")].append(row)
    return {query_type: metrics_for_results(rows) for query_type, rows in sorted(grouped.items())}


def run_model(
    alias: str,
    cases: list[dict[str, Any]],
    records: list[dict[str, Any]],
    top_k: int,
    batch_size: int,
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    model, load_report = load_model(alias)
    if model is None:
        skipped_summary = {
            "model_alias": alias,
            "model_path_alias": MODEL_ALIASES[alias],
            "model_load_success": False,
            "skipped_benchmark": True,
            "case_count": 0,
            "source_hit_at_k": 0.0,
            "doc_type_hit_at_k": 0.0,
            "keyword_hit_at_k": 0.0,
            "top1_source_hit": 0.0,
            "mrr_source": 0.0,
            "exact_match_hit_at_k": 0.0,
            "bilingual_case_hit_at_k": 0.0,
            "code_api_case_hit_at_k": 0.0,
            "empty_result_count": 0,
            "invalid_result_count": 0,
            "banned_source_result_count": 0,
            "model_load_time_sec": load_report["model_load_time_sec"],
            "indexing_time_sec": 0.0,
            "avg_query_latency_ms": 0.0,
            "embedding_dimension": 0,
            "by_query_type": {},
        }
        return [], skipped_summary, load_report

    texts = [record["text"] for record in records]
    query_texts = [case["query"] for case in cases]
    index_start = time.perf_counter()
    document_embeddings = encode_texts(
        model,
        alias,
        texts,
        is_query=False,
        batch_size=batch_size,
    )
    indexing_time_sec = round(time.perf_counter() - index_start, 4)
    load_report["embedding_dimension"] = int(document_embeddings.shape[1])

    query_start = time.perf_counter()
    query_embeddings = encode_texts(
        model,
        alias,
        query_texts,
        is_query=True,
        batch_size=batch_size,
    )
    similarity = query_embeddings @ document_embeddings.T
    query_latency_total_ms = (time.perf_counter() - query_start) * 1000

    model_results: list[dict[str, Any]] = []
    for case, scores in zip(cases, similarity, strict=True):
        result = evaluate_case(case, records, scores, top_k=top_k)
        result["model_alias"] = alias
        result["model_path_alias"] = MODEL_ALIASES[alias]
        model_results.append(result)

    core_metrics = metrics_for_results(model_results)
    model_summary = {
        "model_alias": alias,
        "model_path_alias": MODEL_ALIASES[alias],
        "model_load_success": True,
        "skipped_benchmark": False,
        **core_metrics,
        "model_load_time_sec": load_report["model_load_time_sec"],
        "indexing_time_sec": indexing_time_sec,
        "avg_query_latency_ms": round(query_latency_total_ms / len(cases), 4),
        "embedding_dimension": int(document_embeddings.shape[1]),
        "by_query_type": grouped_metrics(model_results),
    }
    return model_results, model_summary, load_report


def best_model_for(summary: dict[str, Any], metric_path: tuple[str, ...]) -> str | None:
    best_alias = None
    best_value = -1.0
    for alias, model_summary in summary.get("models", {}).items():
        if model_summary.get("skipped_benchmark"):
            continue
        value: Any = model_summary
        for key in metric_path:
            value = value.get(key, {}) if isinstance(value, dict) else {}
        if isinstance(value, (int, float)) and value > best_value:
            best_alias = alias
            best_value = float(value)
    return best_alias


def main() -> None:
    args = parse_args()
    unknown_models = [alias for alias in args.models if alias not in MODEL_ALIASES]
    if unknown_models:
        raise ValueError(f"Unknown model aliases: {unknown_models}")

    cases = load_jsonl(args.cases)
    chunks = load_jsonl(args.chunk_manifest)
    eligible_count = sum(1 for chunk in chunks if is_allowed_chunk(chunk))
    records, selected_count = build_records(chunks, limit=args.chunk_limit)
    if not records:
        raise RuntimeError("No reviewed chunk text could be recovered for benchmarking.")

    all_results: list[dict[str, Any]] = []
    load_reports: list[dict[str, Any]] = []
    model_summaries: dict[str, Any] = {}
    for alias in args.models:
        model_results, model_summary, load_report = run_model(
            alias,
            cases,
            records,
            top_k=args.top_k,
            batch_size=args.batch_size,
        )
        all_results.extend(model_results)
        load_reports.append(load_report)
        model_summaries[alias] = model_summary

    summary = {
        "case_count": len(cases),
        "query_type_distribution": dict(sorted(Counter(row["query_type"] for row in cases).items())),
        "reviewed_chunk_eligible_count": eligible_count,
        "reviewed_chunk_selected_count": selected_count,
        "reviewed_chunk_recovered_count": len(records),
        "top_k": args.top_k,
        "models": model_summaries,
        "best_models": {},
        "writes_chroma": False,
        "writes_production_chroma_collection": False,
        "calls_llm": False,
        "modifies_agent": False,
        "modifies_api": False,
        "uses_memory_index": True,
    }
    summary["best_models"] = {
        "mixed_zh_en_api": best_model_for(
            summary,
            ("by_query_type", "mixed_zh_en_api", "source_hit_at_k"),
        ),
        "exact_metadata_lookup": best_model_for(
            summary,
            ("by_query_type", "exact_metadata_lookup", "source_hit_at_k"),
        ),
        "code_api_config": best_model_for(
            summary,
            ("by_query_type", "code_api_config", "source_hit_at_k"),
        ),
        "overall_source_hit_at_k": best_model_for(summary, ("source_hit_at_k",)),
    }

    write_jsonl(args.results, all_results)
    write_json(args.summary, summary)
    write_json(args.load_report, {"models": load_reports})

    print(f"case_count={summary['case_count']}")
    print(f"reviewed_chunk_recovered_count={summary['reviewed_chunk_recovered_count']}")
    for alias, model_summary in model_summaries.items():
        status = "skipped" if model_summary["skipped_benchmark"] else "completed"
        print(
            f"{alias}: {status}, source_hit_at_k={model_summary['source_hit_at_k']}, "
            f"mrr_source={model_summary['mrr_source']}"
        )
    print(f"results={args.results}")
    print(f"summary={args.summary}")
    print(f"load_report={args.load_report}")


if __name__ == "__main__":
    main()
