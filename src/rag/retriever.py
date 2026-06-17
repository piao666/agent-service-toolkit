from pathlib import Path
from typing import Any

from langchain_core.embeddings import Embeddings

from rag.config import rag_settings
from rag.embeddings import get_embedding_model
from rag.retrieval_policy import (
    RetrievalPolicyName,
    citation_evidence_check,
    dense_sparse_fusion_score,
    infer_query_type,
    metadata_first_score,
    select_retrieval_policy,
    sparse_first_score,
    split_multi_hop_query,
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

    inferred_query_type = infer_query_type(query)
    selected_policy = select_retrieval_policy(inferred_query_type)
    candidates = _collection_candidates(vector_store)
    policy_results: list[RetrievalResult] = []
    metadata_first_applied = False
    sparse_first_applied = False
    dense_sparse_fusion_applied = False
    citation_evidence_checked = False
    clarification_first_applied = False
    multi_query_applied = False

    if selected_policy.name is RetrievalPolicyName.METADATA_FIRST:
        metadata_first_applied = True
        policy_results = _metadata_first_candidates(query, candidates, resolved_top_k)
    elif selected_policy.name is RetrievalPolicyName.SPARSE_FIRST_BM25:
        sparse_first_applied = True
        policy_results = _sparse_first_candidates(query, candidates, resolved_top_k)
    elif selected_policy.name is RetrievalPolicyName.CLARIFICATION_FIRST:
        clarification_first_applied = True
        policy_results = dense_results
    elif selected_policy.name is RetrievalPolicyName.MULTI_QUERY_RETRIEVAL:
        multi_query_applied = True
        subqueries = split_multi_hop_query(query)
        policy_results = dense_results
        for subquery in subqueries[:3]:
            for doc, score in vector_store.similarity_search_with_score(subquery, k=resolved_top_k):
                policy_results.append(_result_from_document(doc.page_content, dict(doc.metadata), score))
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

    merged_results = _merge_unique_results(policy_results, dense_results, resolved_top_k)
    policy_debug = {
        "policy_mode": "query_type_aware",
        "inferred_query_type": inferred_query_type.value,
        "selected_policy": selected_policy.name.value,
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
