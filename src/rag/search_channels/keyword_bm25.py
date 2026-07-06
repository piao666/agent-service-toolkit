"""Phase 6A: keyword_bm25_channel — 轻量关键词匹配，不引入重依赖。

使用简单的 token overlap scoring + fixture fallback。
当外部依赖不可用时，返回 fixture 数据用于 smoke 验证。
"""

from __future__ import annotations

import re
import time
from typing import Any

from rag.search_channels.base import ChannelResult, SearchHit


# ── Fixture chunks (用于 smoke，无需真实索引) ───────────────────────

_FIXTURE_CHUNKS: list[dict[str, Any]] = [
    {
        "chunk_id": "kw_fixture_fastapi_001",
        "source_id": "fastapi_official_middleware",
        "heading_path": "Middleware > What is middleware",
        "text_preview": "Middleware is a function that works with every request before it is processed by any specific path operation. And also with every response before returning it.",
        "corpus": "official_docs",
        "origin_url": "https://fastapi.tiangolo.com/tutorial/middleware/",
    },
    {
        "chunk_id": "kw_fixture_chroma_001",
        "source_id": "chroma_official_metadata_filtering",
        "heading_path": "Querying > Metadata Filtering",
        "text_preview": "Chroma supports filtering queries by metadata. You can supply a where filter dictionary to the query method.",
        "corpus": "official_docs",
        "origin_url": "https://docs.trychroma.com/docs/querying-collections/metadata-filtering",
    },
    {
        "chunk_id": "kw_fixture_internal_001",
        "source_id": "internal_corpus_routing_design",
        "heading_path": "Corpus Routing > auto routing",
        "text_preview": "The auto routing mode uses keyword-based rules to decide whether a query should be routed to official_docs, internal_engineering_docs, or both (dual mode).",
        "corpus": "internal_engineering_docs",
        "origin_url": "internal_corpus_routing_design",
    },
]


def _tokenize(text: str) -> set[str]:
    """简单分词：英文按空格/标点切分，中文按字符。"""
    # 英文 tokens
    en_tokens = set(re.findall(r"[a-zA-Z0-9_]+", text.lower()))
    # 中文逐字符
    zh_tokens = set(re.findall(r"[一-鿿]", text))
    return en_tokens | zh_tokens


def _score_by_overlap(query_tokens: set[str], doc_text: str) -> float:
    """基于 token overlap 的打分。"""
    doc_tokens = _tokenize(doc_text)
    if not query_tokens or not doc_tokens:
        return 0.0
    overlap = query_tokens & doc_tokens
    return len(overlap) / max(len(query_tokens), 1)


def keyword_bm25_channel(
    query: str,
    top_k: int = 5,
    target_corpora: list[str] | None = None,
    **kwargs: Any,
) -> ChannelResult:
    """轻量关键词匹配 channel。

    - 当依赖不足时使用 fixture chunks。
    - 不引入 heavy NLP 依赖 (sklearn/rank_bm25 等)。
    - token overlap scoring 作为 BM25 的简化替代。
    """
    t0 = time.perf_counter()
    errors: list[str] = []
    hits: list[SearchHit] = []
    trace: dict[str, Any] = {"query": query, "top_k": top_k, "method": "token_overlap"}

    query_tokens = _tokenize(query)
    if not query_tokens:
        trace["warning"] = "empty query tokens"
        return ChannelResult(
            channel="keyword_bm25",
            corpus="dual",
            hits=[],
            latency_ms=round((time.perf_counter() - t0) * 1000, 2),
            errors=errors,
            trace=trace,
        )

    # 使用 fixture chunks 作为语料
    candidates = _FIXTURE_CHUNKS
    if target_corpora:
        candidates = [c for c in candidates if c.get("corpus", "") in target_corpora]

    for chunk in candidates:
        score = _score_by_overlap(query_tokens, chunk.get("text_preview", ""))
        if score > 0:
            hits.append(SearchHit(
                chunk_id=chunk["chunk_id"],
                source_id=chunk["source_id"],
                heading_path=chunk.get("heading_path", ""),
                text_preview=chunk.get("text_preview", "")[:200],
                score=round(score, 4),
                corpus=chunk.get("corpus", ""),
                origin_url=chunk.get("origin_url", ""),
                channel="keyword_bm25",
            ))

    hits.sort(key=lambda h: h.score, reverse=True)
    hits = hits[:top_k]

    trace["candidate_count"] = len(candidates)
    trace["hit_count"] = len(hits)
    trace["fixture_mode"] = True

    latency = round((time.perf_counter() - t0) * 1000, 2)
    return ChannelResult(
        channel="keyword_bm25",
        corpus="dual",
        hits=hits,
        latency_ms=latency,
        errors=errors,
        trace=trace,
    )
