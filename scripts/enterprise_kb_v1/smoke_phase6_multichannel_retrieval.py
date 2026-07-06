#!/usr/bin/env python3
"""Phase 6 Smoke: Multi-channel Retrieval Engine.

Verifies:
  1. All new modules importable (search_channels, orchestrator, postprocess)
  2. keyword_bm25 channel returns fixture hits
  3. metadata_filter channel filters correctly
  4. history_aware channel produces trace
  5. Vector channels degrade gracefully when Chroma unavailable
  6. Orchestrator dual mode executes both official + internal channels
  7. Postprocess dedup / normalize / balance / citation selection
  8. custom_graph retriever integration (existing smoke compatibility)
"""

import json, sys
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))
REPORTS = Path(__file__).resolve().parent.parent.parent / "reports" / "enterprise_kb_v1"
REPORTS.mkdir(parents=True, exist_ok=True)


# -- Test 1: Module imports ------------------------------------------------

def test_imports():
    modules = [
        "rag.search_channels",
        "rag.search_channels.base",
        "rag.search_channels.official_vector",
        "rag.search_channels.internal_vector",
        "rag.search_channels.keyword_bm25",
        "rag.search_channels.metadata_filter",
        "rag.search_channels.history_aware",
        "rag.retrieval_orchestrator",
        "rag.postprocess",
    ]
    results = {}
    for mod in modules:
        try:
            __import__(mod)
            results[mod] = "ok"
        except Exception as e:
            results[mod] = f"FAIL: {e}"
    return results


# -- Test 2: keyword_bm25 channel ------------------------------------------

def test_keyword_bm25():
    from rag.search_channels.keyword_bm25 import keyword_bm25_channel

    result = keyword_bm25_channel("What is FastAPI middleware?", top_k=5)
    return {
        "channel": result.channel,
        "corpus": result.corpus,
        "hits_count": len(result.hits),
        "has_errors": len(result.errors) > 0,
        "errors": result.errors,
        "fixture_mode": result.trace.get("fixture_mode", False),
        "hit_chunk_ids": [h.chunk_id for h in result.hits],
        "hit_corpora": list(set(h.corpus for h in result.hits)),
        "latency_ms": result.latency_ms,
    }


# -- Test 3: metadata_filter channel ---------------------------------------

def test_metadata_filter():
    from rag.search_channels.base import SearchHit
    from rag.search_channels.metadata_filter import metadata_filter_channel

    candidates = [
        SearchHit(chunk_id="c1", source_id="s1", heading_path="FastAPI > Middleware", text_preview="test", score=0.9, corpus="official_docs", channel="test"),
        SearchHit(chunk_id="c2", source_id="s2", heading_path="Chroma > Metadata Filtering", text_preview="test", score=0.8, corpus="official_docs", channel="test"),
        SearchHit(chunk_id="c3", source_id="s3", heading_path="Internal > Routing Design", text_preview="test", score=0.7, corpus="internal_engineering_docs", channel="test"),
    ]

    # Filter by corpus
    r1 = metadata_filter_channel("test", candidates=candidates, filter_corpus="official_docs", top_k=5)
    r2 = metadata_filter_channel("test", candidates=candidates, filter_heading_keyword="Middleware", top_k=5)
    r3 = metadata_filter_channel("test", candidates=None, filter_corpus="official_docs", top_k=5)

    return {
        "filter_corpus_hits": len(r1.hits),
        "filter_corpus_match": all(h.corpus == "official_docs" for h in r1.hits),
        "filter_heading_hits": len(r2.hits),
        "filter_heading_match": all("Middleware" in h.heading_path for h in r2.hits),
        "empty_candidates_hits": len(r3.hits),
        "empty_candidates_no_error": len(r3.errors) == 0,
    }


# -- Test 4: history_aware channel -----------------------------------------

def test_history_aware():
    from rag.search_channels.history_aware import history_aware_channel

    r1 = history_aware_channel("What is FastAPI?", rewritten_query="Explain FastAPI middleware", session_id="sess_001", original_query="What is FastAPI?")
    r2 = history_aware_channel("test", rewritten_query="", session_id="")

    return {
        "trace_only_mode": r1.trace.get("mode") == "trace_only",
        "history_used_true": r1.trace.get("history_used") is True,
        "history_used_false": r2.trace.get("history_used") is False,
        "hits_zero": len(r1.hits) == 0,
        "session_id_in_trace": r1.trace.get("session_id") == "sess_001",
    }


# -- Test 5: Vector channels (graceful degradation) ------------------------

def test_vector_channels():
    from rag.search_channels.official_vector import official_vector_channel
    from rag.search_channels.internal_vector import internal_vector_channel

    off = official_vector_channel("FastAPI middleware", top_k=5)
    int_r = internal_vector_channel("corpus routing", top_k=5)

    # 依赖可用性: trace 中有 retrieved_count 说明 import 成功
    off_dep_available = off.trace.get("retrieved_count", -1) >= 0 or len(off.hits) > 0
    int_dep_available = int_r.trace.get("retrieved_count", -1) >= 0 or len(int_r.hits) > 0

    # 依赖缺失被明确记录
    off_dep_missing_flagged = off.trace.get("dependency_missing") is True or any(
        "unavailable" in e.lower() for e in off.errors)
    int_dep_missing_flagged = int_r.trace.get("dependency_missing") is True or any(
        "unavailable" in e.lower() for e in int_r.errors)

    # dependency_missing_written: 如果依赖可用 → 无需写(通过); 如果依赖不可用 → 必须写 errors
    off_ok = off_dep_available or off_dep_missing_flagged
    int_ok = int_dep_available or int_dep_missing_flagged

    # silent pass: hits=0 且无 trace/errors 解释
    off_silent = not off_dep_available and not off_dep_missing_flagged
    int_silent = not int_dep_available and not int_dep_missing_flagged

    return {
        "official_channel": off.channel,
        "official_hits": len(off.hits),
        "official_errors": off.errors,
        "official_errors_count": len(off.errors),
        "official_trace_dependency_missing": off.trace.get("dependency_missing", None),
        "official_dep_available": off_dep_available,
        "internal_channel": int_r.channel,
        "internal_hits": len(int_r.hits),
        "internal_errors": int_r.errors,
        "internal_errors_count": len(int_r.errors),
        "internal_trace_dependency_missing": int_r.trace.get("dependency_missing", None),
        "internal_dep_available": int_dep_available,
        "channels_no_crash": True,
        "dependency_missing_written": off_ok and int_ok,
        "no_silent_pass": not off_silent and not int_silent,
    }


# -- Test 6: Orchestrator dual mode ----------------------------------------

def test_orchestrator_dual():
    from rag.retrieval_orchestrator import run_orchestrator

    result = run_orchestrator(
        query="How does FastAPI middleware work and what is the internal routing design?",
        route_mode="dual",
        top_k=5,
        rewritten_query="",
        session_id="test_session",
    )

    channel_names = [cr.channel for cr in result.channel_results]
    dual_channels_present = "official_vector" in channel_names and "internal_vector" in channel_names
    keyword_present = "keyword_bm25" in channel_names
    history_present = "history_aware" in channel_names

    # 检查 channel 结果结构
    channel_structure_ok = all(
        hasattr(cr, "channel") and hasattr(cr, "corpus") and
        hasattr(cr, "hits") and hasattr(cr, "latency_ms") and
        hasattr(cr, "errors") and hasattr(cr, "trace")
        for cr in result.channel_results
    )

    # 检查 citation candidates
    citation_chunk_ids = [c.chunk_id for c in result.citation_candidates]
    merged_chunk_ids = [h.chunk_id for h in result.merged_hits]
    citations_from_merged = all(
        cid in merged_chunk_ids for cid in citation_chunk_ids
    ) if citation_chunk_ids else True

    return {
        "route_mode": result.route_mode,
        "target_corpora": result.target_corpora,
        "channel_count": len(result.channel_results),
        "channel_names": channel_names,
        "dual_channels_present": dual_channels_present,
        "keyword_present": keyword_present,
        "history_present": history_present,
        "channel_structure_ok": channel_structure_ok,
        "merged_hits_count": len(result.merged_hits),
        "citation_candidates_count": len(result.citation_candidates),
        "citations_from_merged": citations_from_merged,
        "has_postprocess_stats": bool(result.postprocess_stats),
        "errors": result.errors,
        "total_latency_ms": result.total_latency_ms,
    }


# -- Test 7: Postprocess pipeline ------------------------------------------

def test_postprocess():
    from rag.search_channels.base import SearchHit
    from rag.postprocess import (
        dedup_by_chunk_id,
        dedup_by_source_id,
        normalize_scores,
        balance_corpora,
        select_citation_candidates,
        postprocess_pipeline,
    )

    # 构造有重复、跨 corpus 的测试数据
    hits = [
        SearchHit(chunk_id="c1", source_id="s1", heading_path="A", text_preview="", score=0.9, corpus="official_docs", channel="t"),
        SearchHit(chunk_id="c1", source_id="s1", heading_path="A", text_preview="", score=0.5, corpus="official_docs", channel="t"),  # dup, lower score
        SearchHit(chunk_id="c2", source_id="s1", heading_path="B", text_preview="", score=0.8, corpus="official_docs", channel="t"),  # same source as c1
        SearchHit(chunk_id="c3", source_id="s2", heading_path="C", text_preview="", score=0.7, corpus="internal_engineering_docs", channel="t"),
        SearchHit(chunk_id="c4", source_id="s3", heading_path="D", text_preview="", score=0.6, corpus="official_docs", channel="t"),
        SearchHit(chunk_id="c5", source_id="s4", heading_path="E", text_preview="", score=0.3, corpus="internal_engineering_docs", channel="t"),
    ]

    # chunk_id 去重
    deduped = dedup_by_chunk_id(hits)
    chunk_dedup_ok = len(deduped) == 5  # c1 重复被去重

    # source_id 去重 (max 1 per source)
    source_deduped = dedup_by_source_id(hits, max_per_source=1)
    source_dedup_ok = len(source_deduped) == 4  # s1 只保留 1 条

    # 归一化
    normalized = normalize_scores(list(hits))
    norm_ok = all(0.0 <= h.score <= 1.0 for h in normalized)

    # corpus 平衡
    balanced = balance_corpora(hits, min_per_corpus=1, total_max=4)
    has_both_corpora = {"official_docs", "internal_engineering_docs"} <= {h.corpus for h in balanced}

    # citation 候选
    citations = select_citation_candidates(hits, max_candidates=3)
    citation_ok = len(citations) <= 3

    # 一站式 pipeline
    pipeline_result = postprocess_pipeline(hits, max_total=6)
    pipeline_ok = (
        "merged_hits" in pipeline_result and
        "citation_candidates" in pipeline_result and
        "stats" in pipeline_result
    )

    return {
        "chunk_dedup_ok": chunk_dedup_ok,
        "source_dedup_ok": source_dedup_ok,
        "normalize_ok": norm_ok,
        "balance_has_both_corpora": has_both_corpora,
        "citation_count_ok": citation_ok,
        "pipeline_ok": pipeline_ok,
        "pipeline_stats": pipeline_result.get("stats", {}),
    }


# -- Test 8: custom_graph retriever integration ----------------------------

def test_custom_graph_retriever():
    """确保 custom_graph retriever 节点仍然可用，trace 字段完整。"""
    try:
        from custom_graph.state import GraphState
        from custom_graph.nodes.retriever import retrieve_chunks
        importable = True
    except ImportError as e:
        return {
            "importable": False,
            "import_error": str(e)[:200],
            "has_results": False,
            "trace_has_route_mode": False,
            "has_citation_candidates": False,
        }

    state = GraphState(
        query="What is FastAPI middleware?",
        corpus="auto",
        session_id="test_session",
    )
    result = retrieve_chunks(state)

    trace = result.get("retrieval_trace", {})
    return {
        "importable": importable,
        "has_results": "retrieval_results" in result,
        "results_count": len(result.get("retrieval_results", [])),
        "trace_has_engine": "engine" in trace,
        "trace_engine": trace.get("engine", "?"),
        "trace_has_route_mode": "route_mode" in trace,
        "trace_has_channel_count": "channels" in trace or "dependency_missing" in trace,
        "has_citation_candidates": "citation_candidates_count" in trace,
        "latency_ms": trace.get("latency_ms", 0),
    }


# -- Main ------------------------------------------------------------------

def main():
    print("=== Phase 6 Smoke: Multi-channel Retrieval Engine ===")
    results = {"smoke": "phase6_multichannel_retrieval", "timestamp": datetime.now(timezone.utc).isoformat()}

    # 1. Imports
    imports = test_imports()
    all_imports_ok = all(v == "ok" for v in imports.values())
    print(f"  Imports: {sum(1 for v in imports.values() if v == 'ok')}/{len(imports)} ok")
    results["imports"] = imports

    # 2. keyword_bm25
    kw = test_keyword_bm25()
    print(f"  keyword_bm25: hits={kw['hits_count']} fixture={kw['fixture_mode']}")
    results["keyword_bm25"] = kw

    # 3. metadata_filter
    mf = test_metadata_filter()
    print(f"  metadata_filter: corpus_filter={mf['filter_corpus_hits']} heading_filter={mf['filter_heading_hits']}")
    results["metadata_filter"] = mf

    # 4. history_aware
    ha = test_history_aware()
    print(f"  history_aware: mode={ha['trace_only_mode']} history_used={ha['history_used_true']}")
    results["history_aware"] = ha

    # 5. Vector channels
    vc = test_vector_channels()
    print(f"  vector_channels: official={vc['official_hits']} hits, internal={vc['internal_hits']} hits, no_crash={vc['channels_no_crash']}")
    results["vector_channels"] = vc

    # 6. Orchestrator dual
    orch = test_orchestrator_dual()
    print(f"  orchestrator: channels={orch['channel_count']} dual={orch['dual_channels_present']} merged={orch['merged_hits_count']} citations={orch['citation_candidates_count']}")
    results["orchestrator"] = orch

    # 7. Postprocess
    pp = test_postprocess()
    print(f"  postprocess: dedup={pp['chunk_dedup_ok']} normalize={pp['normalize_ok']} balance={pp['balance_has_both_corpora']} pipeline={pp['pipeline_ok']}")
    results["postprocess"] = pp

    # 8. custom_graph integration
    cg = test_custom_graph_retriever()
    print(f"  custom_graph_retriever: importable={cg.get('importable','?')} engine={cg.get('trace_engine','?')} results={cg.get('results_count',0)} citations={cg.get('has_citation_candidates','?')}")
    results["custom_graph_retriever"] = cg

    # Overall pass
    results["overall_pass"] = (
        all_imports_ok
        and kw["hits_count"] > 0
        and kw["fixture_mode"] is True
        and mf["filter_corpus_hits"] > 0
        and mf["filter_corpus_match"] is True
        and mf["empty_candidates_no_error"] is True
        and ha["trace_only_mode"] is True
        and vc["channels_no_crash"] is True
        and vc["no_silent_pass"] is True
        and vc["dependency_missing_written"] is True
        and orch["dual_channels_present"] is True
        and orch["keyword_present"] is True
        and orch["channel_structure_ok"] is True
        and orch["citations_from_merged"] is True
        and pp["pipeline_ok"] is True
        and pp["chunk_dedup_ok"] is True
        and pp["normalize_ok"] is True
        and cg.get("importable", False) is True
        and cg.get("has_results", False) is True
        and cg.get("trace_has_route_mode", False) is True
        and cg.get("has_citation_candidates", False) is True
    )

    path = REPORTS / "phase6_multichannel_retrieval_smoke.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\nSaved: {path}")
    print(f"Overall: {'PASS' if results['overall_pass'] else 'FAIL'}")

    if not results["overall_pass"]:
        print("ERROR: overall_pass=false -- exiting with code 1")
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
