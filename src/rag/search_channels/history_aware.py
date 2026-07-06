"""Phase 6A: history_aware_channel — 接收 rewritten_query/session context，输出 trace。

不做复杂 memory 管理，仅在 trace 中记录上下文信息。
"""

from __future__ import annotations

import time
from typing import Any

from rag.search_channels.base import ChannelResult, SearchHit


def history_aware_channel(
    query: str,
    rewritten_query: str = "",
    session_id: str = "",
    original_query: str = "",
    **kwargs: Any,
) -> ChannelResult:
    """历史感知 channel — trace-only，不执行实际检索。

    未来可在此接入 session memory / conversation history 检索。
    """
    t0 = time.perf_counter()

    trace: dict[str, Any] = {
        "original_query": original_query or query,
        "rewritten_query": rewritten_query,
        "session_id": session_id,
        "history_used": bool(rewritten_query and rewritten_query != query),
        "mode": "trace_only",
        "note": "历史感知检索预留 — 当前仅记录 trace，不执行实际检索。",
    }

    # 如果存在 rewritten_query，记录但不执行额外检索
    # 主检索链路会优先使用 rewritten_query
    if rewritten_query and rewritten_query != query:
        trace["rewrite_effect"] = f"原始: {original_query or query[:80]} -> 改写: {rewritten_query[:80]}"

    latency = round((time.perf_counter() - t0) * 1000, 2)
    return ChannelResult(
        channel="history_aware",
        corpus="unknown",
        hits=[],
        latency_ms=latency,
        errors=[],
        trace=trace,
    )
