from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from build_phase6_chunks import _paragraph_chunks, _sha256_text  # noqa: E402
from dotenv import load_dotenv  # noqa: E402
from langchain_core.documents import Document  # noqa: E402

from rag.config import rag_settings  # noqa: E402
from rag.embeddings import get_embedding_model  # noqa: E402
from rag.vector_store import add_documents, get_collection_count, get_vector_store  # noqa: E402

try:
    from datetime import UTC as DATETIME_UTC
except ImportError:  # pragma: no cover - Python 3.10 compatibility.
    DATETIME_UTC = timezone.utc  # noqa: UP017


MANIFEST_DIR = ROOT_DIR / "data" / "knowledge_base" / "manifests"
CHUNK_MANIFEST_PATH = MANIFEST_DIR / "chunk_manifest.jsonl"
INGESTION_MANIFEST_PATH = MANIFEST_DIR / "chroma_ingestion_manifest.jsonl"
INGESTION_REPORT_PATH = MANIFEST_DIR / "chroma_ingestion_report.json"
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
    parser = argparse.ArgumentParser(
        description="Phase 6B-2 local-only Chroma ingestion for reviewed chunk candidates."
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Plan ingestion without Chroma writes.")
    mode.add_argument("--execute", action="store_true", help="Write selected chunks to Chroma.")
    parser.add_argument("--limit", type=int, default=80)
    parser.add_argument("--persist-dir", default=DEFAULT_PERSIST_DIR)
    parser.add_argument("--collection-name", default=DEFAULT_COLLECTION)
    parser.add_argument("--model-path", default=None)
    parser.add_argument("--device", default="cpu")
    return parser.parse_args()


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def _write_jsonl(records: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as file:
        for record in records:
            file.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def _write_json(record: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _section_path(value: Any) -> str:
    if isinstance(value, list):
        return " > ".join(str(item) for item in value if item is not None)
    return str(value or "")


def _metadata(chunk: dict[str, Any]) -> dict[str, Any]:
    return {
        "chunk_id": str(chunk.get("chunk_id") or ""),
        "normalized_id": str(chunk.get("normalized_id") or ""),
        "source_id": str(chunk.get("source_id") or ""),
        "doc_type": str(chunk.get("doc_type") or ""),
        "domain": str(chunk.get("domain") or ""),
        "language": str(chunk.get("language") or ""),
        "title": str(chunk.get("title") or ""),
        "source_url": str(chunk.get("source_url") or ""),
        "section_path": _section_path(chunk.get("section_path")),
        "review_status": str(chunk.get("review_status") or ""),
        "ingest_candidate": bool(chunk.get("ingest_candidate")),
    }


def _is_allowed_candidate(chunk: dict[str, Any]) -> bool:
    if chunk.get("ingest_candidate") is not True:
        return False
    if chunk.get("review_status") != "approved":
        return False
    if chunk.get("normalization_status") != "pass":
        return False
    return str(chunk.get("source_id") or "") not in BANNED_SOURCE_IDS


def _recover_chunk_text(chunk: dict[str, Any]) -> tuple[str | None, str | None]:
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


def _select_balanced_candidates(chunks: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for chunk in chunks:
        if _is_allowed_candidate(chunk):
            group_key = str(chunk.get("normalized_id") or chunk.get("source_id") or "unknown")
            grouped[group_key].append(chunk)

    selected: list[dict[str, Any]] = []
    group_keys = sorted(grouped)
    while len(selected) < limit and any(grouped.values()):
        for group_key in group_keys:
            if not grouped[group_key]:
                continue
            selected.append(grouped[group_key].pop(0))
            if len(selected) >= limit:
                break
    return selected


def _build_records(chunks: list[dict[str, Any]], limit: int) -> tuple[list[dict[str, Any]], list[Document]]:
    selected = _select_balanced_candidates(chunks, limit=limit)
    manifest_records: list[dict[str, Any]] = []
    documents: list[Document] = []
    now = datetime.now(DATETIME_UTC).isoformat()

    for chunk in selected:
        text, error = _recover_chunk_text(chunk)
        base = {
            "generated_at": now,
            "chunk_id": chunk.get("chunk_id"),
            "normalized_id": chunk.get("normalized_id"),
            "source_id": chunk.get("source_id"),
            "doc_type": chunk.get("doc_type"),
            "review_status": chunk.get("review_status"),
            "ingest_candidate": chunk.get("ingest_candidate"),
            "selected_for_ingestion": True,
            "text_recovered": error is None,
            "text_chars": len(text or ""),
            "chroma_written": False,
            "error_summary": error,
        }
        manifest_records.append(base)
        if text is None:
            continue
        documents.append(Document(page_content=text, metadata=_metadata(chunk)))

    return manifest_records, documents


def _mark_written(
    manifest_records: list[dict[str, Any]],
    written_ids: set[str],
) -> list[dict[str, Any]]:
    marked: list[dict[str, Any]] = []
    for record in manifest_records:
        chunk_id = str(record.get("chunk_id") or "")
        if chunk_id in written_ids:
            marked.append({**record, "chroma_written": True, "error_summary": None})
        else:
            marked.append(record)
    return marked


def _safe_collection_count(persist_dir: str, collection_name: str) -> int | None:
    try:
        return get_collection_count(persist_dir, collection_name)
    except Exception:
        return None


def _clear_collection(vector_store: Any) -> int:
    collection = vector_store._collection  # noqa: SLF001 - local maintenance script.
    existing = collection.get()
    ids = list(existing.get("ids") or [])
    if ids:
        collection.delete(ids=ids)
    return len(ids)


def main() -> None:
    load_dotenv()
    args = parse_args()
    execute = bool(args.execute)
    if args.dry_run:
        execute = False

    chunks = _load_jsonl(CHUNK_MANIFEST_PATH)
    candidate_chunks = [chunk for chunk in chunks if _is_allowed_candidate(chunk)]
    blocked_sources = sorted(
        {
            str(chunk.get("source_id") or "")
            for chunk in chunks
            if str(chunk.get("source_id") or "") in BANNED_SOURCE_IDS
        }
    )
    manifest_records, documents = _build_records(chunks, limit=args.limit)

    written_ids: set[str] = set()
    embedding_provider = rag_settings.EMBEDDING_PROVIDER
    model_path = str(args.model_path or rag_settings.LOCAL_EMBEDDING_MODEL_PATH)
    collection_count_before = (
        _safe_collection_count(args.persist_dir, args.collection_name) if execute else None
    )
    collection_count_after = collection_count_before
    cleared_existing_count = 0

    if execute and documents:
        embeddings = get_embedding_model(model_path=model_path, device=args.device)
        vector_store = get_vector_store(
            embeddings,
            persist_dir=args.persist_dir,
            collection_name=args.collection_name,
        )
        cleared_existing_count = _clear_collection(vector_store)
        written_ids = set(add_documents(vector_store, documents))
        collection_count_after = _safe_collection_count(args.persist_dir, args.collection_name)

    manifest_records = _mark_written(manifest_records, written_ids)
    _write_jsonl(manifest_records, INGESTION_MANIFEST_PATH)

    report = {
        "generated_at": datetime.now(DATETIME_UTC).isoformat(),
        "execute": execute,
        "dry_run": not execute,
        "limit": args.limit,
        "chunk_manifest_count": len(chunks),
        "eligible_candidate_count": len(candidate_chunks),
        "selected_count": len(manifest_records),
        "text_recovered_count": sum(1 for record in manifest_records if record["text_recovered"]),
        "chroma_written_count": sum(1 for record in manifest_records if record["chroma_written"]),
        "error_count": sum(1 for record in manifest_records if record["error_summary"]),
        "persist_dir": args.persist_dir,
        "collection_name": args.collection_name,
        "collection_count_before": collection_count_before,
        "collection_count_after": collection_count_after,
        "cleared_existing_count": cleared_existing_count,
        "selection_strategy": "round_robin_by_normalized_id",
        "reset_collection_on_execute": execute,
        "embedding_provider": embedding_provider,
        "model_path_alias": MODEL_PATH_ALIAS,
        "banned_sources_present_in_manifest": blocked_sources,
        "banned_source_written_count": sum(
            1
            for record in manifest_records
            if record["chroma_written"] and record.get("source_id") in BANNED_SOURCE_IDS
        ),
        "writes_chroma": execute,
        "calls_embedding": execute,
        "calls_llm": False,
        "qa_evaluation": False,
        "manifest_path": str(INGESTION_MANIFEST_PATH.relative_to(ROOT_DIR)),
        "report_path": str(INGESTION_REPORT_PATH.relative_to(ROOT_DIR)),
    }
    _write_json(report, INGESTION_REPORT_PATH)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
