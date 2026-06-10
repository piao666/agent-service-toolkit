from __future__ import annotations

from pathlib import Path
from typing import Any

from langchain_core.tools import BaseTool, tool

from rag.config import rag_settings
from rag.retriever import retrieve
from rag.vector_store import get_collection_count

DISTANCE_NOTE = "distance 越小越相关；relevance_score 越大越相关"
CONTEXT_CHUNK_CHAR_LIMIT = 1200
CONTEXT_TOTAL_CHAR_LIMIT = 6000
PREVIEW_CHAR_LIMIT = 260
MAX_TOP_K = 20


def _normalize_text(text: str) -> str:
    return " ".join(text.split())


def _clip_text(text: str, limit: int) -> str:
    normalized = _normalize_text(text)
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3] + "..."


def _normalize_top_k(top_k: int | str | None) -> tuple[int, int | str, str | None]:
    if top_k is None:
        return rag_settings.RAG_DEFAULT_TOP_K, rag_settings.RAG_DEFAULT_TOP_K, None
    try:
        parsed = int(top_k)
    except (TypeError, ValueError):
        return rag_settings.RAG_DEFAULT_TOP_K, str(top_k), "invalid_top_k"
    if parsed < 1 or parsed > MAX_TOP_K:
        return parsed, parsed, "invalid_top_k"
    return parsed, parsed, None


def _debug_payload(
    query: str,
    top_k: int | str,
    persist_dir: str | Path | None = None,
    collection_name: str | None = None,
    hit_count: int = 0,
    error: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "original_query": query,
        "top_k": top_k,
        "hit_count": hit_count,
        "embedding_provider": rag_settings.EMBEDDING_PROVIDER,
        "vector_store": "chroma",
        "collection": collection_name or rag_settings.CHROMA_COLLECTION_NAME,
        "persist_dir": str(persist_dir or rag_settings.CHROMA_PERSIST_DIR),
        "distance_note": DISTANCE_NOTE,
    }
    if error:
        payload["error"] = error
    return payload


def _fallback_payload(
    query: str,
    top_k: int | str,
    reason: str,
    persist_dir: str | Path | None = None,
    collection_name: str | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    return {
        "context": "",
        "sources": [],
        "retrieval_debug": _debug_payload(
            query=query,
            top_k=top_k,
            persist_dir=persist_dir,
            collection_name=collection_name,
            hit_count=0,
            error=error,
        ),
        "fallback": {
            "triggered": True,
            "reason": reason,
        },
    }


def _source_payload(result: Any) -> dict[str, Any]:
    metadata = dict(result.metadata or {})
    return {
        "source": result.source,
        "title": result.title,
        "doc_type": result.doc_type,
        "chunk_id": result.chunk_id,
        "chunk_index": result.chunk_index,
        "distance": result.distance,
        "relevance_score": result.relevance_score,
        "content_preview": _clip_text(result.content_preview, PREVIEW_CHAR_LIMIT),
        "metadata": metadata,
    }


def _format_context(sources: list[dict[str, Any]], page_contents: list[str]) -> str:
    blocks: list[str] = []
    total_length = 0

    for index, (source, page_content) in enumerate(zip(sources, page_contents), start=1):
        content = _clip_text(page_content, CONTEXT_CHUNK_CHAR_LIMIT)
        block = "\n".join(
            [
                f"[Source {index}]",
                f"title: {source.get('title') or ''}",
                f"source: {source.get('source') or ''}",
                f"chunk_id: {source.get('chunk_id') or ''}",
                f"distance: {source.get('distance')}",
                "content:",
                content,
            ]
        )
        if total_length + len(block) > CONTEXT_TOTAL_CHAR_LIMIT:
            break
        blocks.append(block)
        total_length += len(block)

    return "\n\n".join(blocks)


def build_enterprise_retrieval_payload(
    query: str,
    top_k: int | str | None = None,
    persist_dir: str | Path | None = None,
    collection_name: str | None = None,
) -> dict[str, Any]:
    """Return structured retrieval output for the enterprise knowledge base."""
    normalized_query = (query or "").strip()
    resolved_top_k, debug_top_k, top_k_error = _normalize_top_k(top_k)
    resolved_persist_dir = Path(persist_dir or rag_settings.CHROMA_PERSIST_DIR)
    resolved_collection = collection_name or rag_settings.CHROMA_COLLECTION_NAME

    if not normalized_query:
        return _fallback_payload(
            query=normalized_query,
            top_k=debug_top_k,
            reason="empty_query",
            persist_dir=resolved_persist_dir,
            collection_name=resolved_collection,
        )
    if top_k_error:
        return _fallback_payload(
            query=normalized_query,
            top_k=debug_top_k,
            reason=top_k_error,
            persist_dir=resolved_persist_dir,
            collection_name=resolved_collection,
        )
    if rag_settings.EMBEDDING_PROVIDER.lower() != "local":
        return _fallback_payload(
            query=normalized_query,
            top_k=resolved_top_k,
            reason="unsupported_embedding_provider",
            persist_dir=resolved_persist_dir,
            collection_name=resolved_collection,
            error=f"provider={rag_settings.EMBEDDING_PROVIDER}",
        )
    if not rag_settings.local_embedding_model_path.exists():
        return _fallback_payload(
            query=normalized_query,
            top_k=resolved_top_k,
            reason="embedding_model_path_missing",
            persist_dir=resolved_persist_dir,
            collection_name=resolved_collection,
            error=str(rag_settings.local_embedding_model_path),
        )
    if not resolved_persist_dir.exists():
        return _fallback_payload(
            query=normalized_query,
            top_k=resolved_top_k,
            reason="chroma_persist_dir_missing",
            persist_dir=resolved_persist_dir,
            collection_name=resolved_collection,
        )

    try:
        collection_count = get_collection_count(
            persist_dir=resolved_persist_dir,
            collection_name=resolved_collection,
        )
        if collection_count is None:
            return _fallback_payload(
                query=normalized_query,
                top_k=resolved_top_k,
                reason="chroma_collection_missing",
                persist_dir=resolved_persist_dir,
                collection_name=resolved_collection,
            )
        if collection_count < 1:
            return _fallback_payload(
                query=normalized_query,
                top_k=resolved_top_k,
                reason="chroma_collection_empty",
                persist_dir=resolved_persist_dir,
                collection_name=resolved_collection,
            )

        results = retrieve(
            normalized_query,
            top_k=resolved_top_k,
            persist_dir=resolved_persist_dir,
            collection_name=resolved_collection,
        )
    except Exception as exc:
        return _fallback_payload(
            query=normalized_query,
            top_k=resolved_top_k,
            reason="retrieval_error",
            persist_dir=resolved_persist_dir,
            collection_name=resolved_collection,
            error=type(exc).__name__,
        )

    if not results:
        return _fallback_payload(
            query=normalized_query,
            top_k=resolved_top_k,
            reason="no_retrieval_hits",
            persist_dir=resolved_persist_dir,
            collection_name=resolved_collection,
        )

    sources = [_source_payload(result) for result in results]
    context = _format_context(sources, [result.page_content for result in results])
    return {
        "context": context,
        "sources": sources,
        "retrieval_debug": _debug_payload(
            query=normalized_query,
            top_k=resolved_top_k,
            persist_dir=resolved_persist_dir,
            collection_name=resolved_collection,
            hit_count=len(sources),
        ),
        "fallback": {
            "triggered": False,
            "reason": None,
        },
    }


def enterprise_knowledge_retriever_func(
    query: str,
    top_k: int | None = None,
) -> dict[str, Any]:
    """Retrieve enterprise knowledge-base context for answer synthesis.

    Args:
        query: User question or rewritten retrieval query.
        top_k: Maximum number of source chunks to return.

    Returns:
        A structured dictionary with context, sources, retrieval_debug, and fallback.
    """
    return build_enterprise_retrieval_payload(query=query, top_k=top_k)


enterprise_retrieval_tool: BaseTool = tool(enterprise_knowledge_retriever_func)
enterprise_retrieval_tool.name = "enterprise_knowledge_retriever"
enterprise_knowledge_retriever = enterprise_retrieval_tool
