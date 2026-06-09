from pathlib import Path

from langchain_core.embeddings import Embeddings

from rag.config import rag_settings
from rag.embeddings import get_embedding_model
from rag.schemas import RetrievalResult
from rag.vector_store import get_vector_store


def _preview(text: str, limit: int = 240) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3] + "..."


def retrieve(
    query: str,
    top_k: int | None = None,
    persist_dir: str | Path | None = None,
    collection_name: str | None = None,
    embeddings: Embeddings | None = None,
) -> list[RetrievalResult]:
    if not query.strip():
        raise ValueError("Query must not be empty.")

    embedding_model = embeddings or get_embedding_model()
    vector_store = get_vector_store(
        embedding_model,
        persist_dir=persist_dir or rag_settings.CHROMA_PERSIST_DIR,
        collection_name=collection_name or rag_settings.CHROMA_COLLECTION_NAME,
        reset=False,
    )
    results = vector_store.similarity_search_with_score(
        query,
        k=top_k or rag_settings.RAG_DEFAULT_TOP_K,
    )

    output: list[RetrievalResult] = []
    for doc, score in results:
        metadata = dict(doc.metadata)
        output.append(
            RetrievalResult(
                source=str(metadata.get("source", "unknown")),
                title=metadata.get("title"),
                doc_type=metadata.get("doc_type"),
                chunk_id=str(metadata.get("chunk_id", "")),
                score=float(score),
                metadata=metadata,
                content_preview=_preview(doc.page_content),
                page_content=doc.page_content,
            )
        )
    return output

