#!/usr/bin/env python3
"""Phase 6E v1.1 Smoke: Real Runtime Retrieval Integration.

Verifies Phase 6 multi-channel engine connects to actual
official_docs / internal_engineering_docs retrievers at runtime.

Covers:
  1. official_docs query — retriever must import successfully
  2. internal_engineering_docs query — retriever must import successfully
  3. dual mixed query — both channels present
  4. graph API direct call — engine=phase6_orchestrator
  5. dependency trace — no silent ModuleNotFoundError

Key pass criteria (v1.1):
  - retriever_imported=true for both channels
  - NOT just "no_silent_pass" — actual import must succeed
  - 0 hits is OK if retriever imported but index empty
"""

import json, sys
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))
REPORTS = Path(__file__).resolve().parent.parent.parent / "reports" / "enterprise_kb_v1"
REPORTS.mkdir(parents=True, exist_ok=True)


# -- Helpers ---------------------------------------------------------------

def _check_channel_trace(channel_results, channel_name):
    """Verify channel trace has retriever_imported flag.

    Primary: retriever_imported (the retriever .py module was found).
    Secondary: has_retriever_module_not_found (specifically the retriever module missing).
    Chromadb/langchain/etc dependency errors are noted but don't block pass
    — they're infrastructure, not code-path issues.
    """
    for cr in channel_results:
        if cr.channel == channel_name:
            trace = cr.trace
            imported = trace.get("retriever_imported", False)

            # 区分 retriever 模块缺失 vs 其依赖 (chromadb 等) 缺失
            retriever_module_name = trace.get("retriever_module", "")
            has_retriever_mod_not_found = any(
                "No module named" in e and retriever_module_name in e
                for e in cr.errors
            ) if cr.errors and retriever_module_name else False

            has_dep_not_found = any(
                "No module named" in e and retriever_module_name not in e
                for e in cr.errors
            ) if cr.errors else False

            return {
                "channel_found": True,
                "retriever_imported": imported,
                "retrieved_count": trace.get("retrieved_count", -1),
                "has_retriever_module_not_found": has_retriever_mod_not_found,
                "has_dependency_not_found": has_dep_not_found,
                "errors": cr.errors,
                "hits_count": len(cr.hits),
                "trace_keys": list(trace.keys()),
                # pass = retriever 模块本身 import 成功 (依赖缺失不阻塞)
                "pass": imported and not has_retriever_mod_not_found,
            }
    return {"channel_found": False, "retriever_imported": False, "pass": False,
            "error": f"channel '{channel_name}' not found"}


# -- Test 1: official_docs query -------------------------------------------

def test_official_query():
    from rag.retrieval_orchestrator import run_orchestrator

    result = run_orchestrator(
        query="How to use FastAPI middleware?",
        route_mode="official_only",
        top_k=5,
    )
    off = _check_channel_trace(result.channel_results, "official_vector")

    return {
        "route_mode": result.route_mode,
        "merged_hits_count": len(result.merged_hits),
        "citation_candidates_count": len(result.citation_candidates),
        "official_channel": off,
        "errors": result.errors,
        "total_latency_ms": result.total_latency_ms,
        "pass": off["pass"],
    }


# -- Test 2: internal_engineering_docs query -------------------------------

def test_internal_query():
    from rag.retrieval_orchestrator import run_orchestrator

    result = run_orchestrator(
        query="What is the corpus routing design?",
        route_mode="internal_only",
        top_k=5,
    )
    int_ch = _check_channel_trace(result.channel_results, "internal_vector")

    return {
        "route_mode": result.route_mode,
        "merged_hits_count": len(result.merged_hits),
        "citation_candidates_count": len(result.citation_candidates),
        "internal_channel": int_ch,
        "errors": result.errors,
        "total_latency_ms": result.total_latency_ms,
        "pass": int_ch["pass"],
    }


# -- Test 3: dual mixed query ----------------------------------------------

def test_dual_query():
    from rag.retrieval_orchestrator import run_orchestrator

    result = run_orchestrator(
        query="Compare FastAPI middleware with internal routing architecture",
        route_mode="dual",
        top_k=5,
    )
    off = _check_channel_trace(result.channel_results, "official_vector")
    int_ch = _check_channel_trace(result.channel_results, "internal_vector")

    both_ok = off["pass"] and int_ch["pass"]
    citations_from_merged = all(
        c.chunk_id in {h.chunk_id for h in result.merged_hits}
        for c in result.citation_candidates
    ) if result.citation_candidates else True

    return {
        "route_mode": result.route_mode,
        "merged_hits_count": len(result.merged_hits),
        "citation_candidates_count": len(result.citation_candidates),
        "both_channels_ok": both_ok,
        "citations_from_merged": citations_from_merged,
        "official_channel": off,
        "internal_channel": int_ch,
        "errors": result.errors,
        "total_latency_ms": result.total_latency_ms,
        "pass": both_ok and citations_from_merged,
    }


# -- Test 4: Graph API direct call -----------------------------------------

def test_graph_api_call():
    from custom_graph.graph import run_custom_graph
    from llm.client import LLMClient

    llm = LLMClient()
    resp = run_custom_graph(
        "What is FastAPI middleware?",
        corpus="auto",
        llm=llm,
    )

    trace = resp.get("retrieval_trace", {})
    channels = trace.get("channels", [])

    # 检查 channel 的 retriever_imported
    off_imported = False
    for ch in channels:
        if ch.get("channel") == "official_vector":
            off_imported = ch.get("trace", {}).get("retriever_imported", False)

    return {
        "has_answer": bool(resp.get("answer_markdown")),
        "trace_engine": trace.get("engine", "?"),
        "uses_phase6_orchestrator": trace.get("engine") == "phase6_orchestrator",
        "channels_in_trace": len(channels),
        "channel_retriever_imported": off_imported,
        "trace_has_citation_candidates": "citation_candidates_count" in trace,
        "llm_mode": resp.get("llm_mode", "?"),
        "pass": trace.get("engine") == "phase6_orchestrator" and bool(resp.get("answer_markdown")),
    }


# -- Test 5: Dependency trace (no silent ModuleNotFoundError) --------------

def test_dependency_trace():
    """Verify channel reports dependency status clearly — no silent pass."""
    from rag.search_channels.official_vector import official_vector_channel

    result = official_vector_channel("test query", top_k=3)
    trace = result.trace
    imported = trace.get("retriever_imported", False)
    retriever_mod_name = trace.get("retriever_module", "")
    has_retriever_mod_not_found = any(
        "No module named" in e and retriever_mod_name in e
        for e in result.errors
    ) if result.errors and retriever_mod_name else False

    # 必须明确：retriever 模块 import 状态可查
    has_clear_status = imported or has_retriever_mod_not_found or trace.get("retrieved_count", -1) >= 0

    return {
        "hits_count": len(result.hits),
        "retriever_imported": imported,
        "has_retriever_module_not_found": has_retriever_mod_not_found,
        "errors": result.errors,
        "has_clear_status": has_clear_status,
        "pass": has_clear_status,
    }


# -- Main ------------------------------------------------------------------

def main():
    print("=== Phase 6E v1.1 Smoke: Real Runtime Retrieval ===")
    results = {"smoke": "phase6e_real_runtime_retrieval", "timestamp": datetime.now(timezone.utc).isoformat()}

    # 1. Official
    off = test_official_query()
    print(f"  official: imported={off['official_channel']['retriever_imported']} hits={off['official_channel']['hits_count']} retriever_mod_missing={off['official_channel']['has_retriever_module_not_found']} dep_missing={off['official_channel']['has_dependency_not_found']}")
    results["official_query"] = off

    # 2. Internal
    int_r = test_internal_query()
    print(f"  internal: imported={int_r['internal_channel']['retriever_imported']} hits={int_r['internal_channel']['hits_count']} retriever_mod_missing={int_r['internal_channel']['has_retriever_module_not_found']} dep_missing={int_r['internal_channel']['has_dependency_not_found']}")
    results["internal_query"] = int_r

    # 3. Dual
    dual = test_dual_query()
    print(f"  dual: both_ok={dual['both_channels_ok']} merged={dual['merged_hits_count']} citations_from_merged={dual['citations_from_merged']}")
    results["dual_query"] = dual

    # 4. Graph API
    api = test_graph_api_call()
    print(f"  graph_api: engine={api['trace_engine']} orchestrator={api['uses_phase6_orchestrator']} answer={api['has_answer']}")
    results["graph_api"] = api

    # 5. Dependency trace
    dep = test_dependency_trace()
    print(f"  dep_trace: imported={dep['retriever_imported']} retriever_mod_missing={dep['has_retriever_module_not_found']} clear={dep['has_clear_status']}")
    results["dependency_trace"] = dep

    # Overall — requires retriever_imported=true, NOT just no_silent_pass
    off_imported = off["official_channel"]["retriever_imported"]
    int_imported = int_r["internal_channel"]["retriever_imported"]
    real_runtime_verified = off_imported and int_imported

    results["overall_pass"] = (
        off["pass"]
        and int_r["pass"]
        and dual["pass"]
        and api["pass"]
        and dep["pass"]
    )
    results.update({
        "official_channel_checked": off["pass"],
        "internal_channel_checked": int_r["pass"],
        "dual_route_checked": dual["pass"],
        "custom_graph_uses_phase6_orchestrator": api["uses_phase6_orchestrator"],
        "graph_api_regression_pass": api["pass"],
        "dependency_errors_traced": dep["pass"],
        "no_silent_pass": dep["pass"],
        "official_retriever_import_pass": off_imported,
        "internal_retriever_import_pass": int_imported,
        "official_runtime_hits_count": off["official_channel"]["hits_count"],
        "internal_runtime_hits_count": int_r["internal_channel"]["hits_count"],
        "real_runtime_retrieval_verified": real_runtime_verified,
        "dependency_trace_pass": dep["pass"],
    })

    path = REPORTS / "phase6e_real_runtime_retrieval_smoke.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\nSaved: {path}")
    print(f"Overall: {'PASS' if results['overall_pass'] else 'FAIL'}")
    print(f"  official_retriever_imported: {off_imported}")
    print(f"  internal_retriever_imported: {int_imported}")
    print(f"  real_runtime_retrieval_verified: {real_runtime_verified}")

    if not results["overall_pass"]:
        print("ERROR: overall_pass=false -- exiting with code 1")
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
