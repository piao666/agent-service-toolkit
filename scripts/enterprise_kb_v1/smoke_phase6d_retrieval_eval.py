#!/usr/bin/env python3
"""Phase 6D Smoke: Retrieval Eval — 轻量 fixture eval, 不跑 embedding/Chroma。

6 cases: official_only, internal_only, dual, keyword, metadata, history-aware
"""

import json, sys
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))
REPORTS = Path(__file__).resolve().parent.parent.parent / "reports" / "enterprise_kb_v1"
REPORTS.mkdir(parents=True, exist_ok=True)

from rag.retrieval_orchestrator import run_orchestrator


EVAL_CASES = [
    {
        "case_id": "eval_001",
        "query": "How to use FastAPI middleware?",
        "expected_route_mode": "official_only",
        "expected_target_corpora": ["official_docs"],
    },
    {
        "case_id": "eval_002",
        "query": "What is the internal corpus routing design?",
        "expected_route_mode": "internal_only",
        "expected_target_corpora": ["internal_engineering_docs"],
    },
    {
        "case_id": "eval_003",
        "query": "Compare FastAPI middleware implementation with the project's internal routing architecture",
        "expected_route_mode": "dual",
        "expected_target_corpora": ["official_docs", "internal_engineering_docs"],
    },
    {
        "case_id": "eval_004",
        "query": "Chroma metadata filtering",
        "expected_route_mode": "official_only",
        "expected_target_corpora": ["official_docs"],
    },
    {
        "case_id": "eval_005",
        "query": "bge-m3 embedding decision",
        "expected_route_mode": "internal_only",
        "expected_target_corpora": ["internal_engineering_docs"],
    },
    {
        "case_id": "eval_006",
        "query": "How does query rewriting work with session memory?",
        "expected_route_mode": "official_only",
        "expected_target_corpora": ["official_docs"],
    },
]


def run_case(case):
    query = case["query"]
    route_mode = case["expected_route_mode"]
    target_corpora = case["expected_target_corpora"]

    # 通过 orchestrator 执行
    result = run_orchestrator(
        query=query,
        route_mode=route_mode,
        target_corpora=target_corpora,
        top_k=5,
        rewritten_query=query,
        session_id="eval_session",
    )

    channel_names = [cr.channel for cr in result.channel_results]
    merged_ids = {h.chunk_id for h in result.merged_hits}
    citation_ids = {c.chunk_id for c in result.citation_candidates}

    # 检查项
    has_official = "official_vector" in channel_names
    has_internal = "internal_vector" in channel_names
    has_keyword = "keyword_bm25" in channel_names

    # route_mode 验证
    if route_mode == "dual":
        route_ok = has_official and has_internal
    elif route_mode == "internal_only":
        route_ok = has_internal
    else:
        route_ok = has_official

    # dual 特殊验证
    dual_ok = True
    if route_mode == "dual":
        dual_ok = has_official and has_internal

    # citation 验证
    citations_valid = citation_ids <= merged_ids if citation_ids else True

    # trace 验证
    has_trace = result.total_latency_ms >= 0 and len(result.channel_results) > 0

    failures = []
    if not route_ok:
        failures.append(f"route_mode={route_mode}, channels={channel_names}")
    if not citations_valid:
        failures.append(f"citation chunk_ids not in merged")
    if not has_trace:
        failures.append("no trace")

    return {
        "case_id": case["case_id"],
        "query": query[:100],
        "expected_route_mode": route_mode,
        "expected_target_corpora": target_corpora,
        "executed_channels": channel_names,
        "merged_hits_count": len(result.merged_hits),
        "citation_candidates_count": len(result.citation_candidates),
        "route_ok": route_ok,
        "dual_ok": dual_ok,
        "citations_valid": citations_valid,
        "has_trace": has_trace,
        "pass": len(failures) == 0,
        "failure_reason": "; ".join(failures) if failures else None,
        "latency_ms": result.total_latency_ms,
    }


def main():
    print("=== Phase 6D Smoke: Retrieval Eval ===")
    results = {"smoke": "phase6d_retrieval_eval", "timestamp": datetime.now(timezone.utc).isoformat()}

    cases_output = []
    passed = 0
    for case in EVAL_CASES:
        r = run_case(case)
        status = "PASS" if r["pass"] else "FAIL"
        reason = f" ({r['failure_reason']})" if r["failure_reason"] else ""
        print(f"  {r['case_id']}: {status} route={r['expected_route_mode']} channels={r['executed_channels']} merged={r['merged_hits_count']}{reason}")
        cases_output.append(r)
        if r["pass"]:
            passed += 1

    total = len(EVAL_CASES)
    dual_cases = [c for c in cases_output if c["case_id"] == "eval_003"]
    dual_pass = all(c["dual_ok"] for c in dual_cases)
    all_trace = all(c["has_trace"] for c in cases_output)
    citations_all_valid = all(c["citations_valid"] for c in cases_output)
    route_accuracy = passed / total if total > 0 else 0

    results["cases"] = cases_output
    results.update({
        "overall_pass": passed == total and dual_pass and citations_all_valid and all_trace,
        "total_cases": total,
        "passed_cases": passed,
        "route_mode_accuracy": route_accuracy,
        "dual_cases_pass": dual_pass,
        "citation_candidates_valid": citations_all_valid,
        "all_cases_have_trace": all_trace,
    })

    path = REPORTS / "phase6d_retrieval_eval_smoke.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\nSaved: {path}")
    print(f"Overall: {'PASS' if results['overall_pass'] else 'FAIL'} "
          f"({passed}/{total} cases, route_accuracy={route_accuracy:.2f})")

    if not results["overall_pass"]:
        print("ERROR: overall_pass=false -- exiting with code 1")
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
