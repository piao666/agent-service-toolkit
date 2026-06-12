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

from build_phase6_chunks import _paragraph_chunks, _sha256_text  # noqa: E402

EVAL_DIR = ROOT_DIR / "data" / "knowledge_base" / "evaluation"
MANIFEST_DIR = ROOT_DIR / "data" / "knowledge_base" / "manifests"
DEFAULT_CASES_PATH = EVAL_DIR / "phase6d_hybrid_retrieval_cases.jsonl"
DEFAULT_RESULTS_PATH = EVAL_DIR / "phase6d_hybrid_retrieval_results.jsonl"
DEFAULT_SUMMARY_PATH = EVAL_DIR / "phase6d_hybrid_retrieval_summary.json"
CHUNK_MANIFEST_PATH = MANIFEST_DIR / "chunk_manifest.jsonl"
COLLECTION_NAME_ALIAS = "enterprise_ai_learning_kb_reviewed"
PREVIEW_MAX_CHARS = 160
RRF_K = 60
HYBRID_WEIGHTS = {
    "alpha_dense": 0.45,
    "beta_sparse": 0.30,
    "gamma_exact": 0.20,
    "delta_metadata": 0.05,
}
MODEL_ALIASES = {
    "bge-small-zh-v1.5": "<LOCAL_EMBEDDING_MODEL_ROOT>/bge-small-zh-v1.5",
    "bge-m3": "<LOCAL_EMBEDDING_MODEL_ROOT>/bge-m3",
    "multilingual-e5-base": "<LOCAL_EMBEDDING_MODEL_ROOT>/multilingual-e5-base",
    "qwen3-embedding-0.6b": "<LOCAL_EMBEDDING_MODEL_ROOT>/qwen3-embedding-0.6b",
}
BANNED_SOURCE_IDS = {
    "chroma_docs",
    "kubernetes_cn_docs",
    "kubernetes_docs",
    "langgraph_docs",
    "pytorch_docs",
}
STRATEGIES = [
    "dense_only",
    "sparse_bm25",
    "exact_match",
    "hybrid_rrf",
    "hybrid_weighted",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Phase 6D-3 offline hybrid retrieval eval.")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument("--chunk-manifest", type=Path, default=CHUNK_MANIFEST_PATH)
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS_PATH)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY_PATH)
    parser.add_argument("--model-alias", default="bge-small-zh-v1.5", choices=sorted(MODEL_ALIASES))
    parser.add_argument("--limit-cases", type=int, default=0)
    parser.add_argument("--limit-chunks", type=int, default=0)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--smoke-test", action="store_true")
    return parser.parse_args()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            if line.strip():
                rows.append(json.loads(line))
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
        section_path = chunk.get("section_path") if isinstance(chunk.get("section_path"), list) else []
        metadata_text = " ".join(
            str(value)
            for value in [
                chunk.get("chunk_id"),
                chunk.get("normalized_id"),
                chunk.get("source_id"),
                chunk.get("doc_type"),
                chunk.get("title"),
                chunk.get("review_status"),
                chunk.get("ingest_candidate"),
                chunk.get("source_url"),
                COLLECTION_NAME_ALIAS,
                *section_path,
            ]
            if value is not None
        )
        records.append(
            {
                "chunk": chunk,
                "text": text,
                "content_preview": sanitize_preview(text),
                "metadata_text": metadata_text,
                "search_text": f"{metadata_text}\n{text}",
                "recovery_error": error,
            }
        )
    return records, len(selected)


def tokenize(text: str) -> list[str]:
    lowered = text.lower()
    tokens = re.findall(r"[a-z0-9_./=-]+|[\u4e00-\u9fff]", lowered)
    compound_tokens: list[str] = []
    for token in re.findall(r"[\u4e00-\u9fff]{2,}|[a-z0-9_./=-]{2,}", lowered):
        compound_tokens.append(token)
    return tokens + compound_tokens


def normalize_scores(scores: np.ndarray) -> np.ndarray:
    if scores.size == 0:
        return scores
    minimum = float(np.min(scores))
    maximum = float(np.max(scores))
    if math.isclose(maximum, minimum):
        return np.zeros_like(scores, dtype=np.float32)
    return ((scores - minimum) / (maximum - minimum)).astype(np.float32)


class BM25Index:
    def __init__(self, tokenized_docs: list[list[str]]) -> None:
        self.tokenized_docs = tokenized_docs
        self.doc_count = len(tokenized_docs)
        self.avgdl = sum(len(doc) for doc in tokenized_docs) / self.doc_count if self.doc_count else 0.0
        self.doc_term_counts = [Counter(doc) for doc in tokenized_docs]
        doc_frequency: Counter[str] = Counter()
        for terms in self.doc_term_counts:
            doc_frequency.update(terms.keys())
        self.idf = {
            term: math.log(1 + (self.doc_count - freq + 0.5) / (freq + 0.5))
            for term, freq in doc_frequency.items()
        }

    def score(self, query: str) -> np.ndarray:
        query_terms = tokenize(query)
        scores = np.zeros(self.doc_count, dtype=np.float32)
        if not query_terms:
            return scores
        k1 = 1.5
        b = 0.75
        for index, term_counts in enumerate(self.doc_term_counts):
            doc_len = len(self.tokenized_docs[index]) or 1
            score = 0.0
            for term in query_terms:
                freq = term_counts.get(term, 0)
                if not freq:
                    continue
                idf = self.idf.get(term, 0.0)
                denominator = freq + k1 * (1 - b + b * doc_len / (self.avgdl or 1.0))
                score += idf * freq * (k1 + 1) / denominator
            scores[index] = score
        return normalize_scores(scores)


def resolve_model_path(alias: str) -> tuple[Path | None, str | None]:
    root = os.environ.get("LOCAL_EMBEDDING_MODEL_ROOT")
    if not root:
        return None, "missing_LOCAL_EMBEDDING_MODEL_ROOT"
    return Path(root) / alias, None


def load_dense_model(alias: str, device: str) -> Any:
    runtime_path, error = resolve_model_path(alias)
    if error:
        raise RuntimeError(error)
    if runtime_path is None or not runtime_path.exists():
        raise RuntimeError("local model alias path does not exist")
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(str(runtime_path), trust_remote_code=True, device=device)


def encode_texts(
    model: Any,
    alias: str,
    texts: list[str],
    *,
    is_query: bool,
    batch_size: int,
) -> np.ndarray:
    if alias == "multilingual-e5-base":
        prefix = "query: " if is_query else "passage: "
        texts = [prefix + text for text in texts]
    encoded = model.encode(
        texts,
        batch_size=batch_size,
        convert_to_numpy=True,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    return np.asarray(encoded, dtype=np.float32)


def exact_scores(query: str, records: list[dict[str, Any]]) -> tuple[np.ndarray, np.ndarray]:
    lowered_query = query.lower()
    terms = set(tokenize(query))
    phrase_terms = {
        term.lower()
        for term in re.findall(r"[a-z0-9_./=-]{3,}|[\u4e00-\u9fff]{2,}", lowered_query)
    }
    terms.update(phrase_terms)
    if not terms:
        return np.zeros(len(records), dtype=np.float32), np.zeros(len(records), dtype=np.float32)

    exact = np.zeros(len(records), dtype=np.float32)
    metadata = np.zeros(len(records), dtype=np.float32)
    for index, record in enumerate(records):
        search_text = str(record["search_text"]).lower()
        metadata_text = str(record["metadata_text"]).lower()
        for term in terms:
            if term in search_text:
                exact[index] += 1.0
            if term in metadata_text:
                metadata[index] += 1.0
        for marker in ["chunk_id", "source_id", "doc_type", "normalized_id", "collection_name"]:
            if marker in lowered_query and marker in metadata_text:
                metadata[index] += 2.0
                exact[index] += 1.0
    return normalize_scores(exact), normalize_scores(metadata)


def rank_from_scores(scores: np.ndarray) -> dict[int, int]:
    return {int(index): rank for rank, index in enumerate(np.argsort(scores)[::-1], start=1)}


def rrf_scores(score_sets: list[np.ndarray]) -> np.ndarray:
    fused = np.zeros_like(score_sets[0], dtype=np.float32)
    for scores in score_sets:
        ranks = rank_from_scores(scores)
        for index, rank in ranks.items():
            fused[index] += 1.0 / (RRF_K + rank)
    return normalize_scores(fused)


def strategy_scores(
    dense: np.ndarray,
    sparse: np.ndarray,
    exact: np.ndarray,
    metadata: np.ndarray,
) -> dict[str, np.ndarray]:
    return {
        "dense_only": normalize_scores(dense),
        "sparse_bm25": sparse,
        "exact_match": normalize_scores(exact + metadata),
        "hybrid_rrf": rrf_scores([normalize_scores(dense), sparse, normalize_scores(exact + metadata)]),
        "hybrid_weighted": normalize_scores(
            HYBRID_WEIGHTS["alpha_dense"] * normalize_scores(dense)
            + HYBRID_WEIGHTS["beta_sparse"] * sparse
            + HYBRID_WEIGHTS["gamma_exact"] * exact
            + HYBRID_WEIGHTS["delta_metadata"] * metadata
        ),
    }


def contains_any(text: str, terms: list[str]) -> bool:
    lowered = text.lower()
    return any(term.lower() in lowered for term in terms)


def rank_records(
    records: list[dict[str, Any]],
    scores: np.ndarray,
    dense: np.ndarray,
    sparse: np.ndarray,
    exact: np.ndarray,
    top_k: int,
) -> list[dict[str, Any]]:
    if len(records) == 0:
        return []
    top_indices = np.argsort(scores)[::-1][: min(top_k, len(records))]
    retrieved: list[dict[str, Any]] = []
    for rank, index in enumerate(top_indices, start=1):
        record = records[int(index)]
        chunk = record["chunk"]
        retrieved.append(
            {
                "_record_index": int(index),
                "rank": rank,
                "chunk_id": chunk.get("chunk_id"),
                "source_id": chunk.get("source_id"),
                "doc_type": chunk.get("doc_type"),
                "title": chunk.get("title"),
                "score": round(float(scores[int(index)]), 6),
                "dense_score": round(float(dense[int(index)]), 6),
                "sparse_score": round(float(sparse[int(index)]), 6),
                "exact_score": round(float(exact[int(index)]), 6),
                "content_preview": record["content_preview"],
            }
        )
    return retrieved


def evaluate_case_strategy(
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
    source_hit = bool(expected_source) and expected_source in source_ids
    doc_type_hit = bool(expected_doc_type) and expected_doc_type in doc_types
    keyword_hit = not expected_keywords or contains_any(retrieved_text, expected_keywords)
    exact_match_hit = bool(case.get("requires_exact_match")) and contains_any(
        retrieved_text, expected_exact_terms
    )
    banned_source_returned = bool(banned_source_ids.intersection(source_ids))
    mrr_source = 0.0
    for rank, source_id in enumerate(source_ids, start=1):
        if source_id == expected_source:
            mrr_source = 1.0 / rank
            break
    public_retrieved = [{k: v for k, v in row.items() if k != "_record_index"} for row in retrieved]
    return {
        "case_id": case["case_id"],
        "strategy": strategy,
        "query": case["query"],
        "query_type": case["query_type"],
        "top_k": top_k,
        "expected_source_id": expected_source,
        "expected_doc_type": expected_doc_type,
        "source_hit": source_hit,
        "doc_type_hit": doc_type_hit,
        "keyword_hit": keyword_hit,
        "requires_exact_match": bool(case.get("requires_exact_match")),
        "exact_match_hit": exact_match_hit,
        "banned_source_returned": banned_source_returned,
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
    }


def grouped_metrics(results: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in results:
        grouped[str(row.get("query_type") or "unknown")].append(row)
    return {query_type: metrics_for_results(rows) for query_type, rows in sorted(grouped.items())}


def best_strategy(summary: dict[str, Any], metric_path: tuple[str, ...]) -> str | None:
    best_name = None
    best_value = -1.0
    for strategy, metrics in summary["strategies"].items():
        value: Any = metrics
        for key in metric_path:
            value = value.get(key, {}) if isinstance(value, dict) else {}
        if isinstance(value, (int, float)) and float(value) > best_value:
            best_name = strategy
            best_value = float(value)
    return best_name


def improvement(new_value: float, baseline: float) -> float:
    return round(new_value - baseline, 4)


def query_type_metric(metrics: dict[str, Any], query_type: str, metric_name: str) -> float:
    by_query_type = metrics.get("by_query_type", {})
    query_metrics = by_query_type.get(query_type, {}) if isinstance(by_query_type, dict) else {}
    value = query_metrics.get(metric_name, 0.0) if isinstance(query_metrics, dict) else 0.0
    return float(value) if isinstance(value, (int, float)) else 0.0


def run_eval(args: argparse.Namespace) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    cases = load_jsonl(args.cases)
    if args.limit_cases > 0:
        cases = cases[: args.limit_cases]
    chunks = load_jsonl(args.chunk_manifest)
    eligible_count = sum(1 for chunk in chunks if is_allowed_chunk(chunk))
    records, selected_count = build_records(chunks, limit=args.limit_chunks)
    if not records:
        raise RuntimeError("No reviewed chunk text could be recovered for hybrid retrieval.")

    model = load_dense_model(args.model_alias, args.device)
    texts = [record["text"] for record in records]
    tokenized_docs = [tokenize(record["search_text"]) for record in records]
    bm25 = BM25Index(tokenized_docs)
    doc_embeddings = encode_texts(
        model,
        args.model_alias,
        texts,
        is_query=False,
        batch_size=args.batch_size,
    )
    query_embeddings = encode_texts(
        model,
        args.model_alias,
        [case["query"] for case in cases],
        is_query=True,
        batch_size=args.batch_size,
    )
    dense_matrix = query_embeddings @ doc_embeddings.T

    all_results: list[dict[str, Any]] = []
    for case_index, case in enumerate(cases):
        dense_scores = normalize_scores(dense_matrix[case_index])
        sparse_scores = bm25.score(case["query"])
        exact, metadata = exact_scores(case["query"], records)
        scores_by_strategy = strategy_scores(dense_scores, sparse_scores, exact, metadata)
        for strategy in STRATEGIES:
            result = evaluate_case_strategy(
                case,
                strategy,
                records,
                scores_by_strategy[strategy],
                dense_scores,
                sparse_scores,
                exact + metadata,
                args.top_k,
            )
            result["model_alias"] = args.model_alias
            result["model_path_alias"] = MODEL_ALIASES[args.model_alias]
            all_results.append(result)

    strategies: dict[str, Any] = {}
    for strategy in STRATEGIES:
        strategy_results = [row for row in all_results if row["strategy"] == strategy]
        strategies[strategy] = {
            **metrics_for_results(strategy_results),
            "by_query_type": grouped_metrics(strategy_results),
        }

    dense_baseline = strategies["dense_only"]
    summary: dict[str, Any] = {
        "case_count": len(cases),
        "query_type_distribution": dict(sorted(Counter(row["query_type"] for row in cases).items())),
        "reviewed_chunk_eligible_count": eligible_count,
        "reviewed_chunk_selected_count": selected_count,
        "reviewed_chunk_recovered_count": len(records),
        "top_k": args.top_k,
        "model_alias": args.model_alias,
        "model_path_alias": MODEL_ALIASES[args.model_alias],
        "smoke_test": bool(args.smoke_test),
        "strategies": strategies,
        "best_strategies": {},
        "dense_only_baseline": dense_baseline,
        "hybrid_improvements": {},
        "hybrid_weights": HYBRID_WEIGHTS,
        "rrf_k": RRF_K,
        "calls_llm": False,
        "writes_chroma": False,
        "writes_production_chroma_collection": False,
        "modifies_agent": False,
        "modifies_api": False,
        "loads_embedding_model": True,
        "uses_memory_index": True,
    }
    summary["best_strategies"] = {
        "overall_source_hit_at_k": best_strategy(summary, ("source_hit_at_k",)),
        "exact_metadata_lookup": best_strategy(
            summary,
            ("by_query_type", "exact_metadata_lookup", "source_hit_at_k"),
        ),
        "code_api_config": best_strategy(
            summary,
            ("by_query_type", "code_api_config", "source_hit_at_k"),
        ),
        "short_keyword": best_strategy(
            summary,
            ("by_query_type", "short_keyword", "source_hit_at_k"),
        ),
    }
    for strategy in ["sparse_bm25", "exact_match", "hybrid_rrf", "hybrid_weighted"]:
        metrics = strategies[strategy]
        summary["hybrid_improvements"][strategy] = {
            "source_hit_at_k_delta": improvement(
                metrics["source_hit_at_k"], dense_baseline["source_hit_at_k"]
            ),
            "top1_source_hit_delta": improvement(
                metrics["top1_source_hit"], dense_baseline["top1_source_hit"]
            ),
            "mrr_source_delta": improvement(metrics["mrr_source"], dense_baseline["mrr_source"]),
            "exact_metadata_source_hit_delta": improvement(
                query_type_metric(metrics, "exact_metadata_lookup", "source_hit_at_k"),
                query_type_metric(dense_baseline, "exact_metadata_lookup", "source_hit_at_k"),
            ),
            "code_api_source_hit_delta": improvement(
                query_type_metric(metrics, "code_api_config", "source_hit_at_k"),
                query_type_metric(dense_baseline, "code_api_config", "source_hit_at_k"),
            ),
            "short_keyword_source_hit_delta": improvement(
                query_type_metric(metrics, "short_keyword", "source_hit_at_k"),
                query_type_metric(dense_baseline, "short_keyword", "source_hit_at_k"),
            ),
        }
    return all_results, summary


def main() -> None:
    args = parse_args()
    results, summary = run_eval(args)
    write_jsonl(args.results, results)
    write_json(args.summary, summary)
    print(f"case_count={summary['case_count']}")
    print(f"reviewed_chunk_recovered_count={summary['reviewed_chunk_recovered_count']}")
    print(f"model_alias={summary['model_alias']}")
    for strategy, metrics in summary["strategies"].items():
        print(
            f"{strategy}: source_hit_at_k={metrics['source_hit_at_k']}, "
            f"top1_source_hit={metrics['top1_source_hit']}, "
            f"mrr_source={metrics['mrr_source']}, "
            f"banned_source_result_count={metrics['banned_source_result_count']}"
        )
    print(f"results={args.results}")
    print(f"summary={args.summary}")


if __name__ == "__main__":
    main()
