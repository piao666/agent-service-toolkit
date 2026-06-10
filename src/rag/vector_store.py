import shutil
from pathlib import Path

import chromadb
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings

from rag.config import rag_settings


def get_vector_store(
    embeddings: Embeddings,
    persist_dir: str | Path | None = None,
    collection_name: str | None = None,
    reset: bool = False,
) -> Chroma:
    resolved_dir = Path(persist_dir or rag_settings.CHROMA_PERSIST_DIR)
    if reset and resolved_dir.exists():
        shutil.rmtree(resolved_dir)

    resolved_dir.mkdir(parents=True, exist_ok=True)
    return Chroma(
        collection_name=collection_name or rag_settings.CHROMA_COLLECTION_NAME,
        persist_directory=str(resolved_dir),
        embedding_function=embeddings,
    )


def add_documents(vector_store: Chroma, chunks: list[Document]) -> list[str]:
    if not chunks:
        return []
    ids = [str(chunk.metadata["chunk_id"]) for chunk in chunks]
    vector_store.add_documents(chunks, ids=ids)
    return ids


def get_collection_count(
    persist_dir: str | Path | None = None,
    collection_name: str | None = None,
) -> int | None:
    resolved_dir = Path(persist_dir or rag_settings.CHROMA_PERSIST_DIR)
    if not resolved_dir.exists():
        return None

    client = chromadb.PersistentClient(path=str(resolved_dir))
    try:
        collection = client.get_collection(collection_name or rag_settings.CHROMA_COLLECTION_NAME)
    except Exception:
        return None
    return int(collection.count())
