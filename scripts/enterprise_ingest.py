from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from dotenv import load_dotenv

from rag.config import rag_settings
from rag.document_loader import load_documents
from rag.embeddings import get_embedding_model
from rag.schemas import IngestStats
from rag.splitter import split_documents
from rag.vector_store import add_documents, get_vector_store


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ingest enterprise knowledge documents.")
    parser.add_argument("--data-dir", default="data/enterprise_docs")
    parser.add_argument("--persist-dir", default=None)
    parser.add_argument("--collection-name", default=None)
    parser.add_argument("--chunk-size", type=int, default=None)
    parser.add_argument("--chunk-overlap", type=int, default=None)
    parser.add_argument("--reset", action="store_true")
    parser.add_argument("--model-path", default=None)
    return parser.parse_args()


def main() -> None:
    load_dotenv()
    args = parse_args()

    persist_dir = args.persist_dir or rag_settings.CHROMA_PERSIST_DIR
    collection_name = args.collection_name or rag_settings.CHROMA_COLLECTION_NAME
    model_path = args.model_path or rag_settings.LOCAL_EMBEDDING_MODEL_PATH

    documents = load_documents(args.data_dir)
    chunks = split_documents(
        documents,
        chunk_size=args.chunk_size,
        chunk_overlap=args.chunk_overlap,
    )
    embeddings = get_embedding_model(model_path=model_path)
    vector_store = get_vector_store(
        embeddings,
        persist_dir=persist_dir,
        collection_name=collection_name,
        reset=args.reset,
    )
    add_documents(vector_store, chunks)

    stats = IngestStats(
        document_count=len(documents),
        chunk_count=len(chunks),
        persist_dir=str(persist_dir),
        collection_name=str(collection_name),
        embedding_provider=rag_settings.EMBEDDING_PROVIDER,
        model_path=str(model_path),
    )
    print(json.dumps(stats.model_dump(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

