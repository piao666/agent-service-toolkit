"""Phase 5: Ranker node — simple score-based ranking with corpus-aware boost."""

import time
from typing import Any

from custom_graph.state import GraphState


def rank_results(state: GraphState) -> dict[str, Any]:
    """Rank retrieval results by score. Simple passthrough — no reranker."""
    t0 = time.perf_counter()
    results = list(state.retrieval_results)

    # Score-sort (already done in retriever, but ensure consistency)
    results.sort(key=lambda x: x.get("score", 0), reverse=True)

    latency = round((time.perf_counter() - t0) * 1000, 2)
    return {
        "ranked_results": results[:10],
        "rank_trace": {"ranked_count": len(results), "reranker_enabled": False, "strategy": "score_sort", "latency_ms": latency},
    }
