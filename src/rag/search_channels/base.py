"""Phase 6A: SearchChannel 抽象 — 统一 channel 输出结构。

每个 channel 返回 ChannelResult，包含 hits、errors、trace。
依赖不足时不崩溃，写 errors 即可。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class SearchHit:
    """统一检索命中结构。"""
    chunk_id: str
    source_id: str
    heading_path: str = ""
    text_preview: str = ""
    score: float = 0.0
    corpus: str = ""
    origin_url: str = ""
    channel: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ChannelResult:
    """channel 执行结果。"""
    channel: str
    corpus: str
    hits: list[SearchHit] = field(default_factory=list)
    latency_ms: float = 0.0
    errors: list[str] = field(default_factory=list)
    trace: dict[str, Any] = field(default_factory=dict)


class SearchChannel(Protocol):
    """channel 协议：可调用，接收 query + kwargs，返回 ChannelResult。"""

    def __call__(self, query: str, **kwargs: Any) -> ChannelResult: ...


# ── 工具函数 ──────────────────────────────────────────────────────────

def hit_from_retrieval_result(r: dict[str, Any], channel: str, corpus: str) -> SearchHit:
    """从现有 retriever 返回的 dict 转为 SearchHit。"""
    return SearchHit(
        chunk_id=str(r.get("chunk_id", "")),
        source_id=str(r.get("source_id", "")),
        heading_path=str(r.get("heading_path", "")),
        text_preview=str(r.get("text_preview", ""))[:200],
        score=float(r.get("score", 0.0)),
        corpus=corpus,
        origin_url=str(r.get("origin_url", r.get("local_path", ""))),
        channel=channel,
        metadata={k: v for k, v in r.items() if k not in ("chunk_id", "source_id", "heading_path", "text_preview", "score", "corpus", "origin_url", "local_path")},
    )
