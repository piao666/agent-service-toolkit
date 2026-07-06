"""Phase 5 v1.1: Retriever — planner-aware with proper error handling."""

import time
from typing import Any

from custom_graph.state import GraphState


def retrieve_chunks(state: GraphState) -> dict[str, Any]:
    t0 = time.perf_counter()
    errors: list[str] = []
    dependency_missing: list[str] = []
    fallback_used = False

    # ── Query selection (planner priority) ──────────────────────────
    if state.plan_retrieval_queries:
        selected_query = state.plan_retrieval_queries[0]
        planner_used = True
    elif state.rewritten_query:
        selected_query = state.rewritten_query
        planner_used = False
    else:
        selected_query = state.query
        planner_used = False

    # ── Corpus routing priority ─────────────────────────────────────
    routing_warnings: list[str] = []
    if state.corpus != "auto":
        route_mode = _corpus_to_mode(state.corpus)
        routing_source = "state.corpus"
    elif state.recommended_corpus:
        mode = _corpus_to_mode(state.recommended_corpus)
        if mode == "auto":
            from rag.corpus_router import detect_route_mode
            route_mode = detect_route_mode(selected_query)
            routing_source = "detect_route_mode"
            routing_warnings.append("recommended_corpus mapped to auto, fell back to detect_route_mode")
        else:
            route_mode = mode
            routing_source = "recommended_corpus"
    else:
        from rag.corpus_router import detect_route_mode
        route_mode = detect_route_mode(selected_query)
        routing_source = "detect_route_mode"

    target_corpora = _mode_to_corpora(route_mode)

    # ── Retrieval ───────────────────────────────────────────────────
    results: list[dict[str, Any]] = []

    if route_mode in ("official_only", "dual"):
        try:
            from rag.official_docs_retriever import official_docs_retrieve
            off = official_docs_retrieve(selected_query, top_k=3 if route_mode == "dual" else 5)
            for r in off.get("results", []):
                r["corpus"] = "official_docs"
                results.append(r)
        except ImportError as e:
            dependency_missing.append("langchain_core/chroma — official_docs_retriever unavailable")
            errors.append(f"official_docs: {e}")
            fallback_used = True
        except Exception as e:
            errors.append(f"official_docs: {e}")
            fallback_used = True

    if route_mode in ("internal_only", "dual"):
        try:
            from rag.internal_engineering_retriever import internal_engineering_retrieve
            int_r = internal_engineering_retrieve(selected_query, top_k=3 if route_mode == "dual" else 5)
            for r in int_r.get("results", []):
                r["corpus"] = "internal_engineering_docs"
                results.append(r)
        except ImportError as e:
            dependency_missing.append("langchain_core/chroma — internal_engineering_retriever unavailable")
            errors.append(f"internal_engineering_docs: {e}")
            fallback_used = True
        except Exception as e:
            errors.append(f"internal_engineering_docs: {e}")
            fallback_used = True

    results.sort(key=lambda x: x.get("score", 0), reverse=True)
    latency = round((time.perf_counter() - t0) * 1000, 2)

    return {
        "retrieval_results": results[:10],
        "retrieval_trace": {
            "planner_used": planner_used,
            "selected_query": selected_query,
            "requested_corpus": state.corpus,
            "recommended_corpus": state.recommended_corpus,
            "routing_source": routing_source,
            "route_mode": route_mode,
            "target_corpora": target_corpora,
            "results_count": len(results),
            "dependency_missing": dependency_missing,
            "fallback_used": fallback_used,
            "routing_warnings": routing_warnings,
            "errors": errors,
            "latency_ms": latency,
        },
    }


def _corpus_to_mode(corpus: str) -> str:
    """Map corpus value to route_mode. Supports dual for bilingual retrieval."""
    if corpus == "official_docs":
        return "official_only"
    if corpus == "internal_engineering_docs":
        return "internal_only"
    if corpus == "dual":
        return "dual"
    if corpus == "auto":
        return "auto"  # caller handles auto → detect_route_mode fallback
    return "official_only"


def _mode_to_corpora(mode: str) -> list[str]:
    if mode == "dual":
        return ["official_docs", "internal_engineering_docs"]
    if mode == "internal_only":
        return ["internal_engineering_docs"]
    return ["official_docs"]
