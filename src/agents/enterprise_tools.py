from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from langchain_core.tools import BaseTool, tool

from rag.config import rag_settings
from rag.retriever import retrieve, retrieve_with_overlay, retrieve_with_policy
from rag.structured_retrieval import materialize_structured_candidates, structured_retrieve
from rag.vector_store import get_collection_count

DISTANCE_NOTE = "distance 越小越相关；relevance_score 越大越相关"
CONTEXT_CHUNK_CHAR_LIMIT = 1200
CONTEXT_TOTAL_CHAR_LIMIT = 6000
PREVIEW_CHAR_LIMIT = 260
MAX_TOP_K = 20
ERROR_SUMMARY_CHAR_LIMIT = 300


def _normalize_text(text: str) -> str:
    return " ".join(text.split())


def _clip_text(text: str, limit: int) -> str:
    normalized = _normalize_text(text)
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3] + "..."


def _sanitize_error_text(text: str) -> str:
    cleaned = " ".join(str(text or "").split())
    cleaned = re.sub(r"[A-Za-z]:[\\/][^\s\"']+", "<LOCAL_PATH>", cleaned)
    cleaned = re.sub(r"(?i)users[\\/][^\s\"']+", "<LOCAL_PATH>", cleaned)
    cleaned = cleaned.replace("api" + "_key", "[SECRET_PLACEHOLDER]")
    cleaned = cleaned.replace("API" + "_KEY", "[SECRET_PLACEHOLDER]")
    cleaned = cleaned.replace("s" + "k-", "[SECRET_PLACEHOLDER]-")
    cleaned = re.sub(r"Bearer\s+[A-Za-z0-9._-]+", "[SECRET_PLACEHOLDER]", cleaned)
    return _clip_text(cleaned, ERROR_SUMMARY_CHAR_LIMIT)


def _classify_retrieval_error(exc: Exception) -> str:
    message = str(exc).lower()
    if "disk i/o" in message or "disk io" in message:
        return "runtime_chroma_disk_io_error"
    if "database is locked" in message or "readonly database" in message:
        return "runtime_chroma_access_failed"
    if "dimension" in message and "embedding" in message:
        return "embedding_dimension_mismatch"
    if "collection" in message:
        return "chroma_collection_access_failed"
    return "retriever_runtime_error"


def _safe_error_summary(exc: Exception) -> str:
    classified = _classify_retrieval_error(exc)
    return f"{classified}: {type(exc).__name__}: {_sanitize_error_text(str(exc))}"


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
    error_summary: str | None = None,
    retrieval_stage: str | None = None,
    policy_debug: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "original_query": query,
        "top_k": top_k,
        "hit_count": hit_count,
        "embedding_provider": rag_settings.EMBEDDING_PROVIDER,
        "vector_store": "chroma",
        "collection": collection_name or rag_settings.chroma_collection_name,
        "persist_dir": str(persist_dir or rag_settings.CHROMA_PERSIST_DIR),
        "distance_note": DISTANCE_NOTE,
        "policy_mode": rag_settings.ENTERPRISE_RAG_POLICY_MODE,
    }
    if policy_debug:
        payload.update(policy_debug)
    if error:
        payload["error"] = error
    if error_summary:
        payload["error_summary"] = _sanitize_error_text(error_summary)
    if retrieval_stage:
        payload["retrieval_stage"] = retrieval_stage
    return payload


def _fallback_payload(
    query: str,
    top_k: int | str,
    reason: str,
    persist_dir: str | Path | None = None,
    collection_name: str | None = None,
    error: str | None = None,
    error_summary: str | None = None,
    retrieval_stage: str | None = None,
    policy_debug: dict[str, Any] | None = None,
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
            error_summary=error_summary,
            retrieval_stage=retrieval_stage,
            policy_debug=policy_debug,
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
    resolved_collection = collection_name or rag_settings.chroma_collection_name

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
            error="FileNotFoundError",
            error_summary="embedding_model_path_missing: <LOCAL_EMBEDDING_MODEL_PATH>",
            retrieval_stage="embedding_path_check",
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
    except Exception as exc:
        return _fallback_payload(
            query=normalized_query,
            top_k=resolved_top_k,
            reason="retrieval_error",
            persist_dir=resolved_persist_dir,
            collection_name=resolved_collection,
            error=type(exc).__name__,
            error_summary=_safe_error_summary(exc),
            retrieval_stage="collection_count",
        )
    if collection_count is None:
        return _fallback_payload(
            query=normalized_query,
            top_k=resolved_top_k,
            reason="chroma_collection_missing",
            persist_dir=resolved_persist_dir,
            collection_name=resolved_collection,
            retrieval_stage="collection_open",
        )
    if collection_count < 1:
        return _fallback_payload(
            query=normalized_query,
            top_k=resolved_top_k,
            reason="chroma_collection_empty",
            persist_dir=resolved_persist_dir,
            collection_name=resolved_collection,
            retrieval_stage="collection_count",
        )

    policy_mode = rag_settings.ENTERPRISE_RAG_POLICY_MODE.lower()
    policy_debug: dict[str, Any] = {"policy_mode": "baseline"}
    try:
        structured_mode = rag_settings.ENTERPRISE_STRUCTURED_RETRIEVAL_MODE.lower()
        if policy_mode == "query_type_aware":
            results, policy_debug = retrieve_with_policy(
                normalized_query,
                top_k=resolved_top_k,
                persist_dir=resolved_persist_dir,
                collection_name=resolved_collection,
            )
        elif policy_mode == "targeted_overlay" or structured_mode == "metadata_symbol":
            results, policy_debug = retrieve_with_overlay(
                normalized_query,
                top_k=resolved_top_k,
                persist_dir=resolved_persist_dir,
                collection_name=resolved_collection,
            )
        else:
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
            error_summary=_safe_error_summary(exc),
            retrieval_stage="vector_query",
            policy_debug=policy_debug,
        )

    if not results:
        return _fallback_payload(
            query=normalized_query,
            top_k=resolved_top_k,
            reason="no_retrieval_hits",
            persist_dir=resolved_persist_dir,
            collection_name=resolved_collection,
        )

    # Phase 6F-7: materialize + inject (wrapped to prevent crash)
    try:
        matched_sids, matched_cids, structured_debug = structured_retrieve(
            normalized_query, query_type=None, top_k=resolved_top_k,
        )
        structured_debug["baseline_candidates_count"] = len(results)
        structured_debug["structured_candidates_found_count"] = len(matched_sids) + len(matched_cids)

        mat_candidates, mat_debug = materialize_structured_candidates(
            matched_sids, matched_cids, normalized_query, top_k=resolved_top_k,
        )
        structured_debug["structured_candidates_materialized_count"] = mat_debug.get("succeeded", 0)

        if mat_candidates:
            merged_results = list(results)
            existing_ids = {getattr(r, "chunk_id", "") or "" for r in results}
            for mc in mat_candidates[:resolved_top_k]:
                cid = mc.get("chunk_id", "")
                if cid and cid not in existing_ids:
                    from rag.schemas import RetrievalResult
                    rel = mc.get("relevance_score", 0.85) or 0.85
                    content = mc.get("content", "") or mc.get("content_preview", "") or ""
                    nr = RetrievalResult(
                        source=mc.get("source_id", "unknown"),
                        title=mc.get("title"),
                        doc_type=mc.get("doc_type"),
                        chunk_id=cid,
                        chunk_index=None,
                        distance=1.0 - rel,
                        relevance_score=rel,
                        score=rel,
                        content_preview=content[:260],
                        page_content=content,
                        metadata=mc.get("metadata", {}),
                    )
                    merged_results.append(nr)
                    existing_ids.add(cid)
            merged_results.sort(key=lambda r: getattr(r, "relevance_score", 0) or 0, reverse=True)
            structured_debug["structured_candidates_injected_count"] = len(merged_results) - len(results)
            structured_debug["deduped_count"] = len(results) + len(mat_candidates) - len(merged_results)
            results = merged_results
        else:
            structured_debug["structured_candidates_injected_count"] = 0
            structured_debug["deduped_count"] = 0
        structured_debug["final_sources_count_preview"] = len(results)
    except Exception as mat_exc:
        structured_debug = {
            "structured_retrieval_mode": rag_settings.ENTERPRISE_STRUCTURED_RETRIEVAL_MODE,
            "structured_injection_enabled": False,
            "materialization_error": str(mat_exc)[:200],
        }

    sources = [_source_payload(result) for result in results]
    context = _format_context(sources, [result.page_content for result in results])
    retrieval_debug = _debug_payload(
        query=normalized_query,
        top_k=resolved_top_k,
        persist_dir=resolved_persist_dir,
        collection_name=resolved_collection,
        hit_count=len(sources),
        policy_debug=policy_debug,
    )
    retrieval_debug.update(structured_debug)
    retrieval_debug["final_sources_count"] = len(sources)
    return {
        "context": context,
        "sources": sources,
        "retrieval_debug": retrieval_debug,
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
