"""Phase 6A: official_vector_channel — 复用 official_docs bge-m3 检索。"""

from __future__ import annotations

import time
from typing import Any

from rag.search_channels.base import ChannelResult, SearchHit, hit_from_retrieval_result


def official_vector_channel(query: str, top_k: int = 5, **kwargs: Any) -> ChannelResult:
    """官方文档密集向量检索。

    依赖 langchain_core / chromadb。缺失时写入 errors，不崩溃。
    """
    t0 = time.perf_counter()
    errors: list[str] = []
    hits: list[SearchHit] = []
    trace: dict[str, Any] = {"query": query, "top_k": top_k, "embedding": "bge-m3"}

    try:
        from rag.official_docs_retriever import official_docs_retrieve
        result = official_docs_retrieve(query, top_k=top_k)
        for r in result.get("results", []):
            hits.append(hit_from_retrieval_result(r, channel="official_vector", corpus="official_docs"))
        trace["retrieved_count"] = len(hits)
        trace["collection"] = result.get("collection_name", "?")
    except ImportError as e:
        errors.append(f"official_vector channel unavailable: {e}")
        trace["dependency_missing"] = True
    except Exception as e:
        errors.append(f"official_vector error: {e}")
        trace["exception"] = str(e)[:200]

    latency = round((time.perf_counter() - t0) * 1000, 2)
    return ChannelResult(
        channel="official_vector",
        corpus="official_docs",
        hits=hits,
        latency_ms=latency,
        errors=errors,
        trace=trace,
    )
