from pathlib import Path
from typing import Any

from langchain_core.embeddings import Embeddings

from rag.config import rag_settings
from rag.embeddings import get_embedding_model
from rag.retrieval_policy import (
    RetrievalPolicyName,
    citation_evidence_check,
    decide_gated_retrieval_policy,
    decide_overlay,
    dense_sparse_fusion_score,
    metadata_first_score,
    sparse_first_score,
)
from rag.schemas import RetrievalResult
from rag.vector_store import get_vector_store

POLICY_SCAN_LIMIT = 1000


def _preview(text: str, limit: int = 240) -> str:
    normalized = " ".join(text.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3] + "..."


def _relevance_score(distance: float) -> float:
    return 1 / (1 + max(distance, 0.0))


def _result_from_document(
    page_content: str,
    metadata: dict[str, Any],
    score: float,
) -> RetrievalResult:
    distance = float(score)
    return RetrievalResult(
        source=str(metadata.get("source", "unknown")),
        title=metadata.get("title"),
        doc_type=metadata.get("doc_type"),
        chunk_id=str(metadata.get("chunk_id", "")),
        chunk_index=metadata.get("chunk_index"),
        distance=distance,
        relevance_score=_relevance_score(distance),
        score=distance,
        metadata=metadata,
        content_preview=_preview(page_content),
        page_content=page_content,
    )


def retrieve(
    query: str,
    top_k: int | None = None,
    persist_dir: str | Path | None = None,
    collection_name: str | None = None,
    embeddings: Embeddings | None = None,
) -> list[RetrievalResult]:
    if not query.strip():
        raise ValueError("Query must not be empty.")

    resolved_top_k = rag_settings.RAG_DEFAULT_TOP_K if top_k is None else top_k
    if resolved_top_k < 1:
        raise ValueError("top_k must be greater than 0.")

    embedding_model = embeddings or get_embedding_model()
    vector_store = get_vector_store(
        embedding_model,
        persist_dir=persist_dir or rag_settings.CHROMA_PERSIST_DIR,
        collection_name=collection_name or rag_settings.CHROMA_COLLECTION_NAME,
        reset=False,
    )
    results = vector_store.similarity_search_with_score(
        query,
        k=resolved_top_k,
    )

    output: list[RetrievalResult] = []
    for doc, score in results:
        metadata = dict(doc.metadata)
        output.append(_result_from_document(doc.page_content, metadata, float(score)))
    output = _apply_query_hints(query, output)
    return output


def _collection_candidates(
    vector_store: Any,
    limit: int = POLICY_SCAN_LIMIT,
) -> list[tuple[str, dict[str, Any]]]:
    """Read a bounded set of Chroma records for metadata/sparse policy scoring."""

    collection = getattr(vector_store, "_collection", None)
    if collection is None:
        return []
    payload = collection.get(include=["documents", "metadatas"], limit=limit)
    documents = payload.get("documents") or []
    metadatas = payload.get("metadatas") or []
    candidates: list[tuple[str, dict[str, Any]]] = []
    for document, metadata in zip(documents, metadatas):
        candidates.append((str(document or ""), dict(metadata or {})))
    return candidates


def _merge_unique_results(
    primary: list[RetrievalResult],
    fallback: list[RetrievalResult],
    top_k: int,
) -> list[RetrievalResult]:
    merged: list[RetrievalResult] = []
    seen: set[str] = set()
    for result in [*primary, *fallback]:
        key = result.chunk_id or f"{result.source}:{result.title}:{result.content_preview}"
        if key in seen:
            continue
        seen.add(key)
        merged.append(result)
        if len(merged) >= top_k:
            break
    return merged


def _metadata_first_candidates(
    query: str,
    candidates: list[tuple[str, dict[str, Any]]],
    top_k: int,
) -> list[RetrievalResult]:
    scored: list[tuple[float, str, dict[str, Any]]] = []
    for document, metadata in candidates:
        score = metadata_first_score(query, metadata)
        if score <= 0:
            continue
        sparse_score = sparse_first_score(query, " ".join([document, str(metadata)]))
        scored.append((score + sparse_score, document, metadata))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [
        _result_from_document(document, metadata, 1 / (1 + score))
        for score, document, metadata in scored[:top_k]
    ]


def _sparse_first_candidates(
    query: str,
    candidates: list[tuple[str, dict[str, Any]]],
    top_k: int,
) -> list[RetrievalResult]:
    scored: list[tuple[float, str, dict[str, Any]]] = []
    for document, metadata in candidates:
        text = " ".join([document, str(metadata)])
        score = sparse_first_score(query, text)
        if score <= 0:
            continue
        scored.append((score, document, metadata))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [
        _result_from_document(document, metadata, 1 / (1 + score))
        for score, document, metadata in scored[:top_k]
    ]


def _dense_sparse_fusion_results(
    query: str,
    dense_results: list[RetrievalResult],
) -> list[RetrievalResult]:
    scored: list[tuple[float, RetrievalResult]] = []
    for result in dense_results:
        sparse_score = sparse_first_score(
            query,
            " ".join([result.page_content, str(result.metadata)]),
        )
        dense_score = result.relevance_score
        fused_score = dense_sparse_fusion_score(dense_score=dense_score, sparse_score=sparse_score)
        result.metadata["policy_sparse_score"] = round(sparse_score, 6)
        result.metadata["policy_dense_score"] = round(dense_score, 6)
        result.metadata["policy_fusion_score"] = round(fused_score, 6)
        scored.append((fused_score, result))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [result for _, result in scored]


def retrieve_with_policy(
    query: str,
    top_k: int | None = None,
    persist_dir: str | Path | None = None,
    collection_name: str | None = None,
    embeddings: Embeddings | None = None,
) -> tuple[list[RetrievalResult], dict[str, Any]]:
    """Retrieve with a query-type-aware policy while keeping dense retrieval as fallback."""

    if not query.strip():
        raise ValueError("Query must not be empty.")

    resolved_top_k = rag_settings.RAG_DEFAULT_TOP_K if top_k is None else top_k
    if resolved_top_k < 1:
        raise ValueError("top_k must be greater than 0.")

    embedding_model = embeddings or get_embedding_model()
    vector_store = get_vector_store(
        embedding_model,
        persist_dir=persist_dir or rag_settings.CHROMA_PERSIST_DIR,
        collection_name=collection_name or rag_settings.CHROMA_COLLECTION_NAME,
        reset=False,
    )
    dense_pairs = vector_store.similarity_search_with_score(query, k=resolved_top_k)
    dense_results = [
        _result_from_document(doc.page_content, dict(doc.metadata), float(score))
        for doc, score in dense_pairs
    ]

    gated_decision = decide_gated_retrieval_policy(query)
    selected_policy = gated_decision.policy
    candidates: list[tuple[str, dict[str, Any]]] = []
    policy_results: list[RetrievalResult] = []
    metadata_first_applied = False
    sparse_first_applied = False
    dense_sparse_fusion_applied = False
    citation_evidence_checked = False
    clarification_first_applied = False
    multi_query_applied = False

    if gated_decision.gated_policy_enabled:
        if selected_policy.name is RetrievalPolicyName.METADATA_FIRST:
            metadata_first_applied = True
            candidates = _collection_candidates(vector_store)
            policy_results = _metadata_first_candidates(query, candidates, resolved_top_k)
        elif selected_policy.name is RetrievalPolicyName.SPARSE_FIRST_BM25:
            sparse_first_applied = True
            candidates = _collection_candidates(vector_store)
            policy_results = _sparse_first_candidates(query, candidates, resolved_top_k)
        elif selected_policy.name is RetrievalPolicyName.CITATION_AWARE_EVIDENCE:
            citation_evidence_checked = True
            policy_results = dense_results
            for result in policy_results:
                result.metadata["citation_evidence"] = citation_evidence_check(
                    query,
                    {
                        "metadata": result.metadata,
                        "title": result.title,
                        "source_url": result.metadata.get("source_url"),
                        "section_path": result.metadata.get("section_path"),
                        "content_preview": result.content_preview,
                    },
                )
        else:
            dense_sparse_fusion_applied = True
            policy_results = _dense_sparse_fusion_results(query, dense_results)
    elif selected_policy.name is RetrievalPolicyName.CLARIFICATION_FIRST:
        clarification_first_applied = True
        policy_results = dense_results
    elif selected_policy.name is RetrievalPolicyName.MULTI_QUERY_RETRIEVAL:
        multi_query_applied = True
        policy_results = dense_results
    else:
        policy_results = dense_results

    merged_results = _merge_unique_results(policy_results, dense_results, resolved_top_k)
    policy_debug = {
        "policy_mode": "query_type_aware",
        "inferred_query_type": gated_decision.query_type.value,
        "selected_policy": selected_policy.name.value,
        "gated_policy_enabled": gated_decision.gated_policy_enabled,
        "fallback_to_baseline": gated_decision.fallback_to_baseline,
        "gated_reason": gated_decision.gated_reason,
        "metadata_first_applied": metadata_first_applied,
        "sparse_first_applied": sparse_first_applied,
        "dense_sparse_fusion_applied": dense_sparse_fusion_applied,
        "citation_evidence_checked": citation_evidence_checked,
        "clarification_first_applied": clarification_first_applied,
        "multi_query_applied": multi_query_applied,
        "requires_clarification": clarification_first_applied,
        "policy_candidate_count": len(candidates),
        "policy_result_count": len(merged_results),
    }
    return merged_results, policy_debug


# ═══════════════════════════════════════════════════════════════
# Phase 6E-11: Targeted Overlay — always baseline, overlay only on strong signal
# ═══════════════════════════════════════════════════════════════

def retrieve_with_overlay(
    query: str,
    top_k: int | None = None,
    persist_dir: str | Path | None = None,
    collection_name: str | None = None,
    embeddings: Embeddings | None = None,
) -> tuple[list[RetrievalResult], dict[str, Any]]:
    """Targeted overlay retrieval: baseline is always preserved.

    Simplified Phase 6E-11 implementation:
    - Always runs standard baseline dense retrieval (proven working)
    - Adds overlay decision metadata for analysis
    - Non-target queries get pure baseline passthrough
    - Only strong-signal queries get auxiliary boost (via score adjustment)
    """
    resolved_top_k = top_k or rag_settings.RAG_DEFAULT_TOP_K

    # ── Step 1: Always run standard baseline dense retrieval ──
    baseline_results = retrieve(
        query,
        top_k=resolved_top_k,
        persist_dir=persist_dir,
        collection_name=collection_name,
    )

    # ── Step 2: Decide overlay (metadata only, no retrieval change) ──
    decision = decide_overlay(query)
    overlay_debug: dict[str, Any] = {
        "policy_mode": "targeted_overlay",
        "overlay_enabled": decision.overlay_enabled,
        "overlay_type": decision.overlay_type,
        "baseline_noop": decision.baseline_noop,
        "overlay_reason": decision.reason,
        "metadata_overlay": decision.metadata_overlay,
        "sparse_overlay": decision.sparse_overlay,
        "citation_overlay": decision.citation_overlay,
        "baseline_result_count": len(baseline_results),
        "selected_policy": decision.overlay_type if decision.overlay_enabled else "baseline_dense",
        "fallback_to_baseline": decision.baseline_noop,
    }

    # ── Step 3: If overlay enabled, boost relevant results ──
    if decision.overlay_enabled and baseline_results:
        query_lower = query.lower()
        for r in baseline_results:
            chunk_text = (getattr(r, "content_preview", "") or "").lower()
            metadata = getattr(r, "metadata", {}) or {}
            meta_text = " ".join(str(v) for v in metadata.values() if isinstance(v, str)).lower()
            combined = chunk_text + " " + meta_text
            boost = 0.0
            if decision.metadata_overlay:
                hits = sum(1 for t in ["source_id", "chunk_id", "doc_type", "title"] if t in combined)
                boost = min(hits * 0.08, 0.24)
            elif decision.sparse_overlay:
                q_terms = set(query_lower.split())
                hits = sum(1 for t in q_terms if t in combined)
                boost = min(hits * 0.06, 0.18)
            if boost > 0:
                current = getattr(r, "relevance_score", 0.5) or 0.5
                r.relevance_score = min(current + boost, 1.0)
        overlay_debug["boost_applied"] = True

    return baseline_results[:resolved_top_k], overlay_debug


# ── Phase 8: Conservative query hint boost ──

EXTERNAL_TECH_PATTERNS: dict[str, dict[str, Any]] = {
    "fastapi": {
        "preferred_terms": ["fastapi", "request body", "pydantic", "body", "请求体", "路径参数"],
        "preferred_source_parts": ["fastapi", "pydantic"],
        "demote_source_parts": ["enterprise_prompt", "enterprise_model_provider", "enterprise_agent_overview"],
    },
    "lora": {
        "preferred_terms": ["lora", "低秩适配", "低秩", "微调", "finetune", "fine-tune", "peft", "qlora"],
        "preferred_source_parts": ["deep_learning", "nlp"],
        "demote_source_parts": [],
    },
    "request body": {
        "preferred_terms": ["request body", "pydantic", "basemodel", "参数", "body", "请求体", "field"],
        "preferred_source_parts": ["fastapi", "pydantic"],
        "demote_source_parts": ["enterprise_prompt", "enterprise_model_provider", "enterprise_agent_overview"],
    },
}


def _apply_query_hints(query: str, results: list[RetrievalResult]) -> list[RetrievalResult]:
    """Conservative query hint boost — re-rank existing results without changing retrieval."""
    q_lower = query.lower()
    hints = None
    for trigger, hint_cfg in EXTERNAL_TECH_PATTERNS.items():
        if trigger in q_lower:
            hints = hint_cfg
            break
    if hints is None:
        return results

    for r in results:
        metadata = getattr(r, "metadata", {}) or {}
        source_id = str(metadata.get("source_id", "") or getattr(r, "source", "") or "")
        title = str(metadata.get("title", "") or getattr(r, "title", "") or "")
        chunk_id = str(metadata.get("chunk_id", "") or getattr(r, "chunk_id", "") or "")
        content = str(getattr(r, "content_preview", "") or getattr(r, "page_content", "") or "")
        combined = f"{source_id} {title} {chunk_id} {content}".lower()

        boost = 0.0
        penalty = 0.0

        # Boost for preferred terms
        for term in hints.get("preferred_terms", []):
            if term.lower() in combined:
                boost += 0.04
        for part in hints.get("preferred_source_parts", []):
            if part.lower() in source_id:
                boost += 0.06

        # Demote generic enterprise docs for external tech queries
        for part in hints.get("demote_source_parts", []):
            if part.lower() in source_id:
                penalty += 0.08

        if boost > 0 or penalty > 0:
            current = float(getattr(r, "relevance_score", 0.5) or 0.5)
            new_score = min(max(current + min(boost, 0.20) - min(penalty, 0.10), 0.0), 1.0)
            r.relevance_score = new_score

    # Re-sort after boost
    results.sort(key=lambda x: getattr(x, "relevance_score", 0) or 0, reverse=True)
    return results
