"""Phase 6B: RetrievalOrchestrator — 多路检索编排器。

根据 planner 输出的 route_mode、target_corpora 执行对应 channel。
dual 模式同时执行 official + internal channel。
每个 channel 输出 channel、corpus、hits、latency_ms、errors、trace。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Callable

from rag.postprocess import postprocess_pipeline
from rag.search_channels.base import ChannelResult, SearchHit


@dataclass
class OrchestratorResult:
    """编排器输出。"""
    merged_hits: list[SearchHit] = field(default_factory=list)
    citation_candidates: list[SearchHit] = field(default_factory=list)
    channel_results: list[ChannelResult] = field(default_factory=list)
    postprocess_stats: dict[str, Any] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    total_latency_ms: float = 0.0
    route_mode: str = ""
    target_corpora: list[str] = field(default_factory=list)


def _run_channel(channel_fn: Callable, name: str, query: str, **kwargs: Any) -> ChannelResult:
    """安全执行单个 channel，异常不传播。"""
    try:
        return channel_fn(query, **kwargs)
    except Exception as e:
        return ChannelResult(
            channel=name,
            corpus="unknown",
            hits=[],
            latency_ms=0.0,
            errors=[f"{name}: {e}"],
            trace={"exception": str(e)[:200]},
        )


def run_orchestrator(
    query: str,
    route_mode: str = "official_only",
    target_corpora: list[str] | None = None,
    top_k: int = 5,
    rewritten_query: str = "",
    session_id: str = "",
    **kwargs: Any,
) -> OrchestratorResult:
    """执行多路检索编排。

    Args:
        query: 用户查询（或 rewritten_query）。
        route_mode: official_only / internal_only / dual。
        target_corpora: 目标语料库列表。
        top_k: 每个 vector channel 的 top_k。
        rewritten_query: 改写后的查询。
        session_id: 会话 ID。
    """
    t0 = time.perf_counter()
    errors: list[str] = []
    channel_results: list[ChannelResult] = []

    target_corpora = target_corpora or _mode_to_corpora(route_mode)

    # ── Channel definitions ──────────────────────────────────────────

    # 总是执行 keyword_bm25（轻量，fixture-based）
    from rag.search_channels.keyword_bm25 import keyword_bm25_channel
    cr = _run_channel(keyword_bm25_channel, "keyword_bm25", query, top_k=top_k, target_corpora=target_corpora)
    channel_results.append(cr)
    if cr.errors:
        errors.extend(cr.errors)

    # official_vector: 仅在需要时执行
    if route_mode in ("official_only", "dual"):
        from rag.search_channels.official_vector import official_vector_channel
        cr = _run_channel(official_vector_channel, "official_vector", query, top_k=top_k)
        channel_results.append(cr)
        if cr.errors:
            errors.extend(cr.errors)

    # internal_vector: 仅在需要时执行
    if route_mode in ("internal_only", "dual"):
        from rag.search_channels.internal_vector import internal_vector_channel
        cr = _run_channel(internal_vector_channel, "internal_vector", query, top_k=top_k)
        channel_results.append(cr)
        if cr.errors:
            errors.extend(cr.errors)

    # metadata_filter: 基于 vector channel 结果做 metadata 过滤
    all_vector_hits = [
        h for cr in channel_results
        if cr.channel in ("official_vector", "internal_vector")
        for h in cr.hits
    ]
    if all_vector_hits:
        from rag.search_channels.metadata_filter import metadata_filter_channel
        for corpus in target_corpora:
            cr = _run_channel(
                metadata_filter_channel, "metadata_filter",
                query, candidates=all_vector_hits, filter_corpus=corpus, top_k=top_k,
            )
            channel_results.append(cr)

    # history_aware: trace-only
    from rag.search_channels.history_aware import history_aware_channel
    cr = _run_channel(
        history_aware_channel, "history_aware", query,
        rewritten_query=rewritten_query, session_id=session_id, original_query=kwargs.get("original_query", query),
    )
    channel_results.append(cr)

    # ── Merge all hits ──────────────────────────────────────────────

    all_hits: list[SearchHit] = []
    for cr in channel_results:
        all_hits.extend(cr.hits)

    # ── Postprocess ─────────────────────────────────────────────────

    post_result = postprocess_pipeline(all_hits, max_total=10, normalize=True)

    total_latency = round((time.perf_counter() - t0) * 1000, 2)

    return OrchestratorResult(
        merged_hits=post_result["merged_hits"],
        citation_candidates=post_result["citation_candidates"],
        channel_results=channel_results,
        postprocess_stats=post_result["stats"],
        errors=errors,
        total_latency_ms=total_latency,
        route_mode=route_mode,
        target_corpora=target_corpora,
    )


def _mode_to_corpora(mode: str) -> list[str]:
    if mode == "dual":
        return ["official_docs", "internal_engineering_docs"]
    if mode == "internal_only":
        return ["internal_engineering_docs"]
    return ["official_docs"]
