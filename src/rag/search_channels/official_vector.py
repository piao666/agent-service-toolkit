"""Phase 6A/6E: official_vector_channel — 复用 official_docs bge-m3 检索。"""

from __future__ import annotations

import time
from typing import Any

from rag.search_channels.base import ChannelResult, hit_from_retrieval_result


def official_vector_channel(query: str, top_k: int = 5, **kwargs: Any) -> ChannelResult:
    """官方文档密集向量检索。

    依赖 chromadb / langchain_core。缺失时写入 errors + trace，不崩溃。
    trace 区分: retriever_imported=true (成功load) vs false (模块缺失)。
    即使 retriever_imported=true，hits 也可能为 0 (索引为空或无匹配)。
    """
    t0 = time.perf_counter()
    errors: list[str] = []
    hits: list[SearchHit] = []
    from rag.search_channels.base import SearchHit
    trace: dict[str, Any] = {
        "query": query, "top_k": top_k, "embedding": "bge-m3",
        "retriever_imported": False,
    }

    try:
        from rag.official_docs_retriever import official_docs_retrieve
        trace["retriever_imported"] = True
        trace["retriever_module"] = "rag.official_docs_retriever"

        result = official_docs_retrieve(query, top_k=top_k)
        for r in result.get("results", []):
            hits.append(hit_from_retrieval_result(r, channel="official_vector", corpus="official_docs"))
        trace["retrieved_count"] = len(hits)
        trace["collection"] = result.get("collection_name", "?")
    except ImportError as e:
        errors.append(f"official_vector channel unavailable: {e}")
        trace["dependency_missing"] = True
        trace["import_error"] = str(e)[:200]
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
