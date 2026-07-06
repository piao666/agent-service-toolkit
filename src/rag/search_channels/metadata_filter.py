"""Phase 6A: metadata_filter_channel — 基于 corpus/source_id/heading_path 做轻量过滤。

接收 candidate hits 或 fixture chunks，按 metadata 条件过滤。
不引入额外存储依赖。
"""

from __future__ import annotations

import time
from typing import Any

from rag.search_channels.base import ChannelResult, SearchHit


def metadata_filter_channel(
    query: str,
    candidates: list[SearchHit] | None = None,
    filter_corpus: str | None = None,
    filter_source_id: str | None = None,
    filter_heading_keyword: str | None = None,
    top_k: int = 5,
    **kwargs: Any,
) -> ChannelResult:
    """对候选集做 metadata 过滤。

    Args:
        query: 用于 trace 的原始查询。
        candidates: 待过滤的 SearchHit 列表。如果为 None，返回空。
        filter_corpus: 按 corpus 精确匹配。
        filter_source_id: 按 source_id 精确匹配。
        filter_heading_keyword: heading_path 包含此关键词。
        top_k: 返回前 N 条。
    """
    t0 = time.perf_counter()
    errors: list[str] = []
    hits: list[SearchHit] = []
    trace: dict[str, Any] = {
        "query": query,
        "filters": {
            "corpus": filter_corpus,
            "source_id": filter_source_id,
            "heading_keyword": filter_heading_keyword,
        },
    }

    if candidates is None:
        trace["candidate_count"] = 0
        trace["note"] = "no candidates provided"
        return ChannelResult(
            channel="metadata_filter",
            corpus=filter_corpus or "unknown",
            hits=[],
            latency_ms=round((time.perf_counter() - t0) * 1000, 2),
            errors=errors,
            trace=trace,
        )

    trace["candidate_count"] = len(candidates)

    for hit in candidates:
        if filter_corpus and hit.corpus != filter_corpus:
            continue
        if filter_source_id and hit.source_id != filter_source_id:
            continue
        if filter_heading_keyword and filter_heading_keyword.lower() not in hit.heading_path.lower():
            continue
        hits.append(hit)

    hits = hits[:top_k]
    trace["filtered_count"] = len(hits)

    latency = round((time.perf_counter() - t0) * 1000, 2)
    return ChannelResult(
        channel="metadata_filter",
        corpus=filter_corpus or "unknown",
        hits=hits,
        latency_ms=latency,
        errors=errors,
        trace=trace,
    )
