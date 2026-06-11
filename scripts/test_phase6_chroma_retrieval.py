from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from dotenv import load_dotenv  # noqa: E402

from rag.config import rag_settings  # noqa: E402
from rag.embeddings import get_embedding_model  # noqa: E402
from rag.vector_store import get_vector_store  # noqa: E402

DEFAULT_PERSIST_DIR = "chroma_enterprise_phase6"
DEFAULT_COLLECTION = "enterprise_ai_learning_kb_reviewed"
MODEL_PATH_ALIAS = "local_bge_small_zh_v1_5"
BANNED_SOURCE_IDS = {
    "chroma_docs",
    "kubernetes_cn_docs",
    "langgraph_docs",
    "pytorch_docs",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Test Phase 6B-2 Chroma retrieval without LLM calls.")
    parser.add_argument("--persist-dir", default=DEFAULT_PERSIST_DIR)
    parser.add_argument("--collection-name", default=DEFAULT_COLLECTION)
    parser.add_argument("--query", required=True)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--model-path", default=None)
    parser.add_argument("--device", default="cpu")
    return parser.parse_args()


def _relevance(distance: float | None) -> float | None:
    if distance is None:
        return None
    return round(1.0 / (1.0 + float(distance)), 6)


def _result_record(index: int, document: Any, distance: float | None) -> dict[str, Any]:
    metadata = dict(document.metadata or {})
    return {
        "rank": index,
        "chunk_id": metadata.get("chunk_id"),
        "source_id": metadata.get("source_id"),
        "doc_type": metadata.get("doc_type"),
        "title": metadata.get("title"),
        "distance": distance,
        "relevance_score": _relevance(distance),
        "review_status": metadata.get("review_status"),
        "ingest_candidate": metadata.get("ingest_candidate"),
        "section_path": metadata.get("section_path"),
    }


def _is_valid_result(record: dict[str, Any]) -> bool:
    return (
        record.get("ingest_candidate") is True
        and record.get("review_status") == "approved"
        and record.get("source_id") not in BANNED_SOURCE_IDS
    )


def main() -> None:
    load_dotenv()
    args = parse_args()
    model_path = str(args.model_path or rag_settings.LOCAL_EMBEDDING_MODEL_PATH)
    embeddings = get_embedding_model(model_path=model_path, device=args.device)
    vector_store = get_vector_store(
        embeddings,
        persist_dir=args.persist_dir,
        collection_name=args.collection_name,
    )
    results = vector_store.similarity_search_with_score(args.query, k=args.top_k)
    records = [
        _result_record(index, document, float(distance) if distance is not None else None)
        for index, (document, distance) in enumerate(results, start=1)
    ]
    invalid = [record for record in records if not _is_valid_result(record)]
    banned_source_results = [
        record for record in records if record.get("source_id") in BANNED_SOURCE_IDS
    ]
    payload = {
        "query": args.query,
        "top_k": args.top_k,
        "result_count": len(records),
        "persist_dir": args.persist_dir,
        "collection_name": args.collection_name,
        "embedding_provider": rag_settings.EMBEDDING_PROVIDER,
        "model_path_alias": MODEL_PATH_ALIAS,
        "results": records,
        "banned_source_result_count": len(banned_source_results),
        "invalid_result_count": len(invalid),
        "semantic_quality_evaluated": False,
        "calls_llm": False,
        "uses_enterprise_query_api": False,
    }
    output = json.dumps(payload, ensure_ascii=False, indent=2)
    sys.stdout.buffer.write(output.encode("utf-8", errors="backslashreplace") + b"\n")
    if invalid:
        raise SystemExit("retrieval returned non-approved or banned-source chunks")


if __name__ == "__main__":
    main()
