from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from dotenv import load_dotenv  # noqa: E402

from rag.config import rag_settings  # noqa: E402
from rag.embeddings import get_embedding_model  # noqa: E402
from rag.vector_store import get_vector_store  # noqa: E402

try:
    from datetime import UTC as DATETIME_UTC
except ImportError:  # pragma: no cover - Python 3.10 compatibility.
    DATETIME_UTC = timezone.utc  # noqa: UP017


EVAL_DIR = ROOT_DIR / "data" / "knowledge_base" / "evaluation"
DEFAULT_CASES_PATH = EVAL_DIR / "phase6_qa_cases.jsonl"
DEFAULT_RESULTS_PATH = EVAL_DIR / "phase6_retrieval_eval_results.jsonl"
DEFAULT_SUMMARY_PATH = EVAL_DIR / "phase6_retrieval_eval_summary.json"
DEFAULT_PERSIST_DIR = "chroma_enterprise_phase6"
DEFAULT_COLLECTION = "enterprise_ai_learning_kb_reviewed"
MODEL_PATH_ALIAS = "local_bge_small_zh_v1_5"
BANNED_SOURCE_IDS = {
    "chroma_docs",
    "kubernetes_cn_docs",
    "langgraph_docs",
    "pytorch_docs",
}
PREVIEW_MAX_CHARS = 200


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Phase 6C retrieval-only QA evaluation.")
    parser.add_argument("--persist-dir", default=DEFAULT_PERSIST_DIR)
    parser.add_argument("--collection-name", default=DEFAULT_COLLECTION)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS_PATH)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY_PATH)
    parser.add_argument("--model-path", default=None)
    parser.add_argument("--device", default="cpu")
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


def _section_path(value: Any) -> str:
    if isinstance(value, list):
        return " > ".join(str(item) for item in value if item is not None)
    return str(value or "")


def _relevance(distance: float | None) -> float | None:
    if distance is None:
        return None
    return round(1.0 / (1.0 + float(distance)), 6)


def _safe_preview(text: str) -> str:
    collapsed = " ".join(text.split())
    collapsed = re.sub(r"sk-[A-Za-z0-9_-]+", "[SECRET_PLACEHOLDER]", collapsed)
    collapsed = re.sub(r"tvly-[A-Za-z0-9_-]+", "[SECRET_PLACEHOLDER]", collapsed)
    replacements = {
        ".env": "[CONFIG_FILE]",
        "api_key": "[SECRET_PLACEHOLDER]",
        "API_KEY": "[SECRET_PLACEHOLDER]",
        "Bearer": "[SECRET_PLACEHOLDER]",
        "password": "[SECRET_PLACEHOLDER]",
        "secret": "[SECRET_PLACEHOLDER]",
    }
    for needle, replacement in replacements.items():
        collapsed = collapsed.replace(needle, replacement)
    return collapsed[:PREVIEW_MAX_CHARS]


def _is_true(value: Any) -> bool:
    return value is True or str(value).lower() == "true"


def _result_record(index: int, document: Any, distance: float | None) -> dict[str, Any]:
    metadata = dict(document.metadata or {})
    return {
        "rank": index,
        "chunk_id": metadata.get("chunk_id"),
        "normalized_id": metadata.get("normalized_id"),
        "source_id": metadata.get("source_id"),
        "doc_type": metadata.get("doc_type"),
        "domain": metadata.get("domain"),
        "title": metadata.get("title"),
        "source_url": metadata.get("source_url"),
        "section_path_available": bool(_section_path(metadata.get("section_path"))),
        "distance": distance,
        "relevance_score": _relevance(distance),
        "review_status": metadata.get("review_status"),
        "ingest_candidate": _is_true(metadata.get("ingest_candidate")),
        "content_preview": _safe_preview(str(document.page_content or "")),
    }


def _is_valid_result(record: dict[str, Any]) -> bool:
    return (
        record.get("review_status") == "approved"
        and record.get("ingest_candidate") is True
        and record.get("source_id") not in BANNED_SOURCE_IDS
    )


def _keyword_hit(expected_keywords: list[str], documents: list[Any]) -> bool:
    if not expected_keywords:
        return True
    haystack = "\n".join(str(document.page_content or "") for document in documents).lower()
    return any(keyword.lower() in haystack for keyword in expected_keywords)


def _reciprocal_rank(expected_sources: list[str], records: list[dict[str, Any]]) -> float:
    if not expected_sources:
        return 0.0
    expected = set(expected_sources)
    for record in records:
        if record.get("source_id") in expected:
            return round(1.0 / int(record["rank"]), 6)
    return 0.0


def _evaluate_case(case: dict[str, Any], vector_store: Any) -> dict[str, Any]:
    top_k = int(case.get("top_k") or 5)
    results = vector_store.similarity_search_with_score(str(case["query"]), k=top_k)
    documents = [document for document, _distance in results]
    records = [
        _result_record(rank, document, float(distance) if distance is not None else None)
        for rank, (document, distance) in enumerate(results, start=1)
    ]
    expected_sources = _as_list(case.get("expected_source_ids"))
    expected_doc_types = _as_list(case.get("expected_doc_types"))
    expected_keywords = _as_list(case.get("expected_keywords"))
    returned_sources = [str(record.get("source_id") or "") for record in records]
    returned_doc_types = [str(record.get("doc_type") or "") for record in records]
    banned_result_count = sum(1 for source_id in returned_sources if source_id in BANNED_SOURCE_IDS)
    invalid_result_count = sum(1 for record in records if not _is_valid_result(record))
    negative = bool(case.get("negative"))
    source_hit = bool(set(expected_sources) & set(returned_sources)) if expected_sources else negative
    doc_type_hit = (
        bool(set(expected_doc_types) & set(returned_doc_types)) if expected_doc_types else negative
    )
    keyword_hit = _keyword_hit(expected_keywords, documents) if not negative else True
    top1_source_hit = bool(records and records[0].get("source_id") in expected_sources)
    best_relevance = records[0].get("relevance_score") if records else None
    return {
        "case_id": case.get("case_id"),
        "query": case.get("query"),
        "category": case.get("category"),
        "negative": negative,
        "top_k": top_k,
        "result_count": len(records),
        "expected_source_ids": expected_sources,
        "expected_doc_types": expected_doc_types,
        "returned_source_ids": returned_sources,
        "returned_doc_types": returned_doc_types,
        "source_hit_at_k": source_hit,
        "doc_type_hit_at_k": doc_type_hit,
        "keyword_hit_at_k": keyword_hit,
        "top1_source_hit": top1_source_hit,
        "mrr_source": _reciprocal_rank(expected_sources, records),
        "best_relevance_score": best_relevance,
        "empty_result": not records,
        "banned_source_result_count": banned_result_count,
        "invalid_result_count": invalid_result_count,
        "results": records,
    }


def _rate(rows: list[dict[str, Any]], key: str) -> float:
    if not rows:
        return 0.0
    return round(sum(1 for row in rows if row.get(key)) / len(rows), 4)


def _summary(rows: list[dict[str, Any]], args: argparse.Namespace) -> dict[str, Any]:
    positive_rows = [row for row in rows if not row.get("negative")]
    relevance_scores = [
        float(row["best_relevance_score"])
        for row in rows
        if row.get("best_relevance_score") is not None
    ]
    return {
        "generated_at": datetime.now(DATETIME_UTC).isoformat(),
        "phase": "6C",
        "eval_type": "retrieval_only",
        "case_count": len(rows),
        "positive_case_count": len(positive_rows),
        "negative_case_count": len(rows) - len(positive_rows),
        "persist_dir": args.persist_dir,
        "collection_name": args.collection_name,
        "embedding_provider": rag_settings.EMBEDDING_PROVIDER,
        "model_path_alias": MODEL_PATH_ALIAS,
        "source_hit_at_k": _rate(positive_rows, "source_hit_at_k"),
        "doc_type_hit_at_k": _rate(positive_rows, "doc_type_hit_at_k"),
        "keyword_hit_at_k": _rate(positive_rows, "keyword_hit_at_k"),
        "top1_source_hit": _rate(positive_rows, "top1_source_hit"),
        "mrr_source": round(mean(row["mrr_source"] for row in positive_rows), 4)
        if positive_rows
        else 0.0,
        "empty_result_count": sum(1 for row in rows if row.get("empty_result")),
        "banned_source_result_count": sum(
            int(row.get("banned_source_result_count") or 0) for row in rows
        ),
        "invalid_result_count": sum(int(row.get("invalid_result_count") or 0) for row in rows),
        "avg_best_relevance_score": round(mean(relevance_scores), 6) if relevance_scores else None,
        "writes_chroma": False,
        "expands_ingestion_scope": False,
        "calls_llm": False,
        "uses_enterprise_query_api": False,
        "stores_full_chunk_text": False,
    }


def main() -> None:
    load_dotenv()
    args = parse_args()
    if not Path(args.persist_dir).exists():
        raise SystemExit(f"persist_dir is missing: {args.persist_dir}")
    cases = [
        case for case in _load_jsonl(args.cases) if "retrieval" in _as_list(case.get("eval_modes"))
    ]
    embeddings = get_embedding_model(
        model_path=str(args.model_path or rag_settings.LOCAL_EMBEDDING_MODEL_PATH),
        device=args.device,
    )
    vector_store = get_vector_store(
        embeddings,
        persist_dir=args.persist_dir,
        collection_name=args.collection_name,
    )
    rows = [_evaluate_case(case, vector_store) for case in cases]
    summary = _summary(rows, args)
    _write_jsonl(args.results, rows)
    _write_json(args.summary, summary)
    output = json.dumps(summary, ensure_ascii=False, indent=2)
    sys.stdout.buffer.write(output.encode("utf-8", errors="backslashreplace") + b"\n")


if __name__ == "__main__":
    main()
