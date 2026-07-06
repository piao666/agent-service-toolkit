"""Phase 6: Retriever — orchestrator-aware with multi-channel support.

保留 Phase 5 兼容性：trace 字段不变，现有 smoke 继续通过。
新增 Phase 6 多路检索：通过 RetrievalOrchestrator 编排 5 个 channel。
"""

from __future__ import annotations

import time
from typing import Any

from custom_graph.state import GraphState


def retrieve_chunks(state: GraphState) -> dict[str, Any]:
    """执行检索：优先使用 Phase 6 orchestrator，失败时回退到 Phase 5 逻辑。"""
    t0 = time.perf_counter()

    # ── Query selection (planner priority, 同 Phase 5) ─────────────────
    if state.plan_retrieval_queries:
        selected_query = state.plan_retrieval_queries[0]
        planner_used = True
    elif state.rewritten_query:
        selected_query = state.rewritten_query
        planner_used = False
    else:
        selected_query = state.query
        planner_used = False

    # ── Corpus routing (同 Phase 5) ────────────────────────────────────
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

    # ── Phase 6: Orchestrator path ────────────────────────────────────
    try:
        from rag.retrieval_orchestrator import run_orchestrator

        orch_result = run_orchestrator(
            query=selected_query,
            route_mode=route_mode,
            target_corpora=target_corpora,
            top_k=3 if route_mode == "dual" else 5,
            rewritten_query=state.rewritten_query,
            session_id=state.session_id,
            original_query=state.query,
        )

        # 转换为兼容格式
        results: list[dict[str, Any]] = []
        for hit in orch_result.merged_hits:
            results.append({
                "chunk_id": hit.chunk_id,
                "source_id": hit.source_id,
                "heading_path": hit.heading_path,
                "text_preview": hit.text_preview,
                "score": hit.score,
                "corpus": hit.corpus,
                "origin_url": hit.origin_url,
                "channel": hit.channel,
            })

        # channel 明细
        channel_traces = []
        for cr in orch_result.channel_results:
            channel_traces.append({
                "channel": cr.channel,
                "corpus": cr.corpus,
                "hits": len(cr.hits),
                "latency_ms": cr.latency_ms,
                "errors": cr.errors,
                "trace": cr.trace,
            })

        latency = round((time.perf_counter() - t0) * 1000, 2)

        return {
            "retrieval_results": results[:10],
            "retrieval_trace": {
                "engine": "phase6_orchestrator",
                "planner_used": planner_used,
                "selected_query": selected_query,
                "requested_corpus": state.corpus,
                "recommended_corpus": state.recommended_corpus,
                "routing_source": routing_source,
                "route_mode": route_mode,
                "target_corpora": target_corpora,
                "results_count": len(results),
                "dependency_missing": [],
                "fallback_used": False,
                "routing_warnings": routing_warnings,
                "errors": orch_result.errors,
                "latency_ms": latency,
                "channels": channel_traces,
                "postprocess_stats": orch_result.postprocess_stats,
                "citation_candidates_count": len(orch_result.citation_candidates),
            },
        }

    except ImportError as e:
        # orchestrator 不可用时回退 Phase 5 逻辑
        return _retrieve_legacy(
            state, t0, selected_query, planner_used, route_mode,
            target_corpora, routing_source, routing_warnings,
        )
    except Exception as e:
        return _retrieve_legacy(
            state, t0, selected_query, planner_used, route_mode,
            target_corpora, routing_source, routing_warnings,
            extra_error=str(e)[:200],
        )


def _retrieve_legacy(
    state: GraphState,
    t0: float,
    selected_query: str,
    planner_used: bool,
    route_mode: str,
    target_corpora: list[str],
    routing_source: str,
    routing_warnings: list[str],
    extra_error: str | None = None,
) -> dict[str, Any]:
    """Phase 5 兼容回退路径。"""
    errors: list[str] = []
    dependency_missing: list[str] = []
    fallback_used = False

    if extra_error:
        errors.append(f"orchestrator: {extra_error}")
        dependency_missing.append("orchestrator unavailable, using legacy Phase 5 retriever")
        fallback_used = True

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
            "engine": "phase5_legacy",
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
        return "auto"
    return "official_only"


def _mode_to_corpora(mode: str) -> list[str]:
    if mode == "dual":
        return ["official_docs", "internal_engineering_docs"]
    if mode == "internal_only":
        return ["internal_engineering_docs"]
    return ["official_docs"]
