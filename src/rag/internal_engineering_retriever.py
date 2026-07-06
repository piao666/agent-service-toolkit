"""Phase 4F: Internal engineering corpus retrieval wrapper.

对称 official_docs_retriever，区别：使用 CHROMA_INTERNAL_PERSIST_DIR / CHROMA_INTERNAL_COLLECTION_NAME。
返回格式与 official_docs_retrieve() 完全一致：{"results": [...], "trace": {...}}。
"""

import time
from typing import Any

from rag.config import rag_settings

TEXT_PREVIEW_LEN = 200


def internal_engineering_retrieve(
    query: str,
    top_k: int | None = None,
) -> dict[str, Any]:
    """使用 bge-m3 internal_engineering_docs 索引检索。

    直接复用 rag.retriever.retrieve()，仅 resolve 不同的 persist_dir / collection_name。
    不进入 RAG answer generation，不做 reranker。
    """
    # ponytail: lazy import，只在调用时触发 langchain 导入链
    from rag.retriever import retrieve  # noqa: PLC0415

    errors: list[str] = []
    t0 = time.perf_counter()

    resolved_top_k = top_k or rag_settings.RAG_DEFAULT_TOP_K

    try:
        if not query.strip():
            raise ValueError("query 不能为空")
        results = retrieve(
            query=query,
            top_k=resolved_top_k,
            persist_dir=rag_settings.CHROMA_INTERNAL_PERSIST_DIR,
            collection_name=rag_settings.CHROMA_INTERNAL_COLLECTION_NAME,
        )
    except Exception as e:
        errors.append(str(e))
        results = []

    latency_ms = round((time.perf_counter() - t0) * 1000, 2)

    formatted_results: list[dict[str, Any]] = []
    chunk_ids: list[str] = []
    source_ids: list[str] = []
    scores: list[float] = []
    origin_urls: list[str] = []
    heading_paths: list[str] = []
    text_previews: list[str] = []

    for r in results:
        meta = r.metadata
        sid = str(meta.get("source_id") or meta.get("source_url") or r.source)
        # internal corpus 没有 origin_url，用 local_path 作为引用标识
        local_path = str(meta.get("local_path") or sid)
        heading = str(meta.get("heading_path") or meta.get("section_path") or "")
        normalized = " ".join((r.page_content or "").split())
        preview = normalized[:TEXT_PREVIEW_LEN]

        chunk_ids.append(r.chunk_id)
        source_ids.append(sid)
        scores.append(round(r.relevance_score, 4))
        origin_urls.append(local_path)
        heading_paths.append(heading)
        text_previews.append(preview)

        formatted_results.append({
            "chunk_id": r.chunk_id,
            "source_id": sid,
            "origin_url": local_path,
            "heading_path": heading,
            "score": round(r.relevance_score, 4),
            "distance": round(r.distance, 4),
            "text_preview": preview,
            "doc_type": r.doc_type or "",
            "title": r.title or "",
            "embedding_model": "bge-m3",
            "collection_name": rag_settings.CHROMA_INTERNAL_COLLECTION_NAME,
        })

    trace: dict[str, Any] = {
        "query": query,
        "top_k": resolved_top_k,
        "embedding_model": "bge-m3",
        "collection_name": rag_settings.CHROMA_INTERNAL_COLLECTION_NAME,
        "persist_dir": rag_settings.CHROMA_INTERNAL_PERSIST_DIR,
        "retrieved_chunk_ids": chunk_ids,
        "retrieved_source_ids": list(dict.fromkeys(source_ids)),
        "scores": scores,
        "origin_urls": origin_urls,
        "heading_paths": heading_paths,
        "text_previews": text_previews,
        "latency_ms": latency_ms,
        "errors": errors,
    }

    return {
        "results": formatted_results,
        "trace": trace,
    }
