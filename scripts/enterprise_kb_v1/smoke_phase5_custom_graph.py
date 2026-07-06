#!/usr/bin/env python3
"""Phase 5 v1.2 Smoke 2: Custom Graph — imports + pipeline + mixed routing + explicit corpus."""

import json, os, sys, time
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))
REPORTS = Path(__file__).resolve().parent.parent.parent / "reports" / "enterprise_kb_v1"
REPORTS.mkdir(parents=True, exist_ok=True)


def test_imports():
    modules = [f"custom_graph.{m}" for m in [
        "state", "graph",
        "nodes.query_classifier", "nodes.memory_rewriter", "nodes.planner",
        "nodes.retriever", "nodes.ranker", "nodes.answer_generator",
        "nodes.evidence_verifier", "nodes.final_response",
    ]]
    results = []
    for mod in modules:
        try:
            __import__(mod)
            results.append({"module": mod, "importable": True})
        except Exception as e:
            results.append({"module": mod, "importable": False, "error": str(e)[:200]})
    return results


def test_pipeline():
    from custom_graph.graph import run_custom_graph
    from llm.client import LLMClient
    llm = LLMClient()
    t0 = time.perf_counter()
    resp = run_custom_graph("What is retrieval augmented generation?", corpus="auto", llm=llm)
    lat = round((time.perf_counter() - t0) * 1000, 2)
    keys = ["answer_markdown","citations","used_sources","unsupported_claims","hallucination_risk",
            "intent_trace","rewrite_trace","plan_trace","retrieval_trace","rank_trace","llm_trace","citation_trace","graph_debug"]
    return {"all_keys_present": all(k in resp for k in keys), "latency_ms": lat, "llm_mode": resp.get("llm_mode","?")}


def test_mixed_routing():
    """Query with both internal and official keywords — expect dual routing."""
    from custom_graph.graph import run_custom_graph
    from llm.client import LLMClient
    llm = LLMClient()
    resp = run_custom_graph("本项目 FastAPI 和 phase 评测如何结合？", corpus="auto", llm=llm)
    it = resp.get("intent_trace", {})
    rt = resp.get("retrieval_trace", {})
    return {
        "query": "本项目 FastAPI 和 phase 评测如何结合？",
        "intent": it.get("intent", ""),
        "recommended_corpus": it.get("recommended_corpus", ""),
        "routing_source": rt.get("routing_source", ""),
        "route_mode": rt.get("route_mode", ""),
        "target_corpora": rt.get("target_corpora", []),
        "planner_used": rt.get("planner_used", False),
        "selected_query": rt.get("selected_query", "")[:60],
        "is_dual": rt.get("route_mode") == "dual" and len(rt.get("target_corpora", [])) >= 2,
        "pass": (
            it.get("intent") == "mixed"
            and it.get("recommended_corpus") == "dual"
            and rt.get("routing_source") == "recommended_corpus"
            and rt.get("route_mode") == "dual"
            and "official_docs" in rt.get("target_corpora", [])
            and "internal_engineering_docs" in rt.get("target_corpora", [])
            and rt.get("planner_used") is True
        ),
    }


def test_explicit_corpus(corpus: str, expected_mode: str):
    from custom_graph.graph import run_custom_graph
    from llm.client import LLMClient
    llm = LLMClient()
    resp = run_custom_graph("test query", corpus=corpus, llm=llm)
    rt = resp.get("retrieval_trace", {})
    return {
        "corpus": corpus,
        "route_mode": rt.get("route_mode", ""),
        "routing_source": rt.get("routing_source", ""),
        "pass": rt.get("route_mode") == expected_mode and rt.get("routing_source") == "state.corpus",
    }


def main():
    print("=== Phase 5 v1.2 Smoke: Custom Graph ===")
    results = {"smoke": "phase5_custom_graph", "timestamp": datetime.now(timezone.utc).isoformat()}

    imports = test_imports()
    all_imp = all(i["importable"] for i in imports)
    print(f"  Imports: {sum(1 for i in imports if i['importable'])}/{len(imports)}")
    results["imports"] = {"all_importable": all_imp, "modules": imports}

    if all_imp:
        pipe = test_pipeline()
        print(f"  Pipeline: keys={pipe['all_keys_present']} latency={pipe['latency_ms']}ms")
        results["pipeline"] = pipe

        mixed = test_mixed_routing()
        print(f"  Mixed routing: intent={mixed['intent']} corpus={mixed['recommended_corpus']} route={mixed['route_mode']} dual={mixed['is_dual']} → {'PASS' if mixed['pass'] else 'FAIL'}")
        results["mixed_routing"] = mixed

        corp_tests = []
        for corpus, mode in [("official_docs","official_only"), ("internal_engineering_docs","internal_only")]:
            ct = test_explicit_corpus(corpus, mode)
            print(f"  Explicit corpus={corpus}: route={ct['route_mode']} source={ct['routing_source']} → {'PASS' if ct['pass'] else 'FAIL'}")
            corp_tests.append(ct)
        results["explicit_corpus_tests"] = corp_tests
    else:
        results["pipeline"] = {"error": "imports failed"}

    results["overall_pass"] = all_imp and results.get("pipeline",{}).get("all_keys_present",False) and results.get("mixed_routing",{}).get("pass",False)
    path = REPORTS / "phase5_custom_graph_smoke.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\nSaved: {path}")
    print(f"Overall: {'PASS' if results['overall_pass'] else 'FAIL'}")


if __name__ == "__main__":
    main()
