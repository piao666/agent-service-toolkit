from __future__ import annotations

# ruff: noqa: E402, I001

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from dotenv import load_dotenv  # noqa: E402

from ingest_phase6_chroma import (  # noqa: E402
    CHUNK_MANIFEST_PATH,
    DEFAULT_COLLECTION,
    MODEL_PATH_ALIAS,
    _build_records,
    _is_allowed_candidate,
    _load_jsonl,
)
from rag.config import rag_settings  # noqa: E402
from rag.embeddings import get_embedding_model  # noqa: E402
from rag.vector_store import add_documents, get_collection_count, get_vector_store  # noqa: E402

DEFAULT_RUNTIME_PERSIST_DIR = "chroma_enterprise_phase6_runtime_rebuilt"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Rebuild the ignored Phase 6D runtime Chroma cache from reviewed chunks."
    )
    parser.add_argument("--limit", type=int, default=80)
    parser.add_argument("--persist-dir", default=DEFAULT_RUNTIME_PERSIST_DIR)
    parser.add_argument("--collection-name", default=DEFAULT_COLLECTION)
    parser.add_argument("--model-path", default=None)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--reset", action="store_true")
    return parser.parse_args()


def _resolve_persist_dir(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        path = ROOT_DIR / path
    return path.resolve()


def _safe_reset_dir(path: Path) -> None:
    root = ROOT_DIR.resolve()
    if root not in path.parents:
        raise ValueError("Refusing to reset a path outside the project workspace.")
    if not path.name.startswith("chroma_enterprise"):
        raise ValueError("Refusing to reset a non-Chroma runtime cache directory.")
    if path.exists():
        shutil.rmtree(path)


def _sample_metadata(documents: list[Any]) -> dict[str, Any]:
    if not documents:
        return {}
    metadata = dict(documents[0].metadata)
    return {
        "source_id": metadata.get("source_id"),
        "doc_type": metadata.get("doc_type"),
        "title": metadata.get("title"),
        "chunk_id": metadata.get("chunk_id"),
    }


def main() -> None:
    load_dotenv()
    args = parse_args()
    persist_dir = _resolve_persist_dir(args.persist_dir)
    if args.reset:
        _safe_reset_dir(persist_dir)

    chunks = _load_jsonl(CHUNK_MANIFEST_PATH)
    candidate_chunks = [chunk for chunk in chunks if _is_allowed_candidate(chunk)]
    manifest_records, documents = _build_records(chunks, limit=args.limit)
    model_path = args.model_path or rag_settings.local_embedding_model_path

    embeddings = get_embedding_model(model_path=model_path, device=args.device)
    vector_store = get_vector_store(
        embeddings,
        persist_dir=persist_dir,
        collection_name=args.collection_name,
    )
    written_ids = set(add_documents(vector_store, documents))
    collection_count = get_collection_count(
        persist_dir=persist_dir,
        collection_name=args.collection_name,
    )

    report = {
        "persist_dir": args.persist_dir,
        "collection_name": args.collection_name,
        "collection_count": collection_count,
        "embedding_dimension": 512,
        "model_path_alias": MODEL_PATH_ALIAS,
        "candidate_count": len(candidate_chunks),
        "selected_count": len(manifest_records),
        "text_recovered_count": sum(1 for record in manifest_records if record["text_recovered"]),
        "written_count": len(written_ids),
        "sample_metadata": _sample_metadata(documents),
        "writes_chroma": True,
        "writes_production_chroma_collection": False,
        "calls_embedding": True,
        "calls_llm": False,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
