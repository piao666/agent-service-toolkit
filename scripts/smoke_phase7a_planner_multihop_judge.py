from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from agents.enterprise_rag_graph import (  # noqa: E402
    build_enterprise_rag_graph,
    run_enterprise_rag_graph,
)

CASES_PATH = REPO_ROOT / "data/knowledge_base/evaluation/phase7a_prototype_cases.jsonl"
SUMMARY_PATH = REPO_ROOT / "data/knowledge_base/evaluation/phase7a_prototype_summary.json"


def _load_cases() -> list[dict[str, Any]]:
    return [
        json.loads(line)
        for line in CASES_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def fake_retriever(query: str, top_k: int | None) -> dict[str, Any]:
    normalized = query.casefold()
    if "lora" in normalized:
        source_id = "lora_overview"
        title = "LoRA Overview"
        preview = "LoRA is a parameter-efficient fine-tuning method for adapting language models."
    elif "fastapi" in normalized or "request body" in normalized:
        source_id = "fastapi_docs"
        title = "FastAPI Request Body"
        preview = "FastAPI Request Body definitions use typed Pydantic models in endpoint schemas."
    elif "graph_debug" in normalized or "enterprise_agent_graph_mode" in normalized:
        source_id = "custom_graph_endpoint"
        title = "Custom Graph Endpoint Routing"
        preview = "ENTERPRISE_AGENT_GRAPH_MODE selects legacy or custom_graph endpoint routing."
    else:
        source_id = "rag_overview"
        title = "RAG Overview"
        preview = "RAG combines retrieved evidence with generation and source tracing."

    sources = [
        {
            "source_id": source_id,
            "title": title,
            "doc_type": "markdown",
            "section_path": "Phase 7A / Smoke",
            "source_url": "https://docs.example.invalid/phase7a",
            "chunk_id": f"{source_id}-001",
            "content_preview": preview,
            "relevance_score": 0.95,
            "metadata": {"source_id": source_id, "title": title},
        }
    ][: max(1, int(top_k or 1))]
    return {
        "sources": sources,
        "retrieval_debug": {
            "hit_count": len(sources),
            "embedding_provider": "phase7a_stub",
            "vector_store": "none",
        },
        "fallback": {"triggered": False, "reason": None},
    }


def fake_answer_generator(query: str, sources: list[dict[str, Any]]) -> str:
    if not sources:
        return "No evidence was available."
    previews = " ".join(str(source.get("content_preview") or "") for source in sources)
    return f"Answer based on retrieved evidence: {previews}"


def _nodes(response: dict[str, Any]) -> list[str]:
    return list((response.get("graph_debug") or {}).get("nodes_executed") or [])


def _check_case(
    case: dict[str, Any],
    response: dict[str, Any],
    *,
    planner_mode: str,
) -> list[str]:
    errors: list[str] = []
    nodes = _nodes(response)
    planner_debug = response.get("planner_debug") or {}
    judge_debug = response.get("judge_debug") or {}
    graph_debug = response.get("graph_debug") or {}

    if case.get("expected_route") not in {"clarification_response", "safe_response"} and "planner" not in nodes:
        errors.append("planner_node_missing")
    if case.get("expected_route") == "clarification_response":
        if "clarification_response" not in nodes:
            errors.append("clarification_route_missing")
    elif case.get("expected_route") == "safe_response":
        if "safe_response" not in nodes:
            errors.append("safe_response_route_missing")
    else:
        if "judge" not in nodes:
            errors.append("judge_node_missing")
        if judge_debug.get("judge_mode") != "rule_based_fallback":
            errors.append("judge_mode_not_rule_based_fallback")

    expected_planner_type = case.get("expected_planner_type")
    if expected_planner_type and planner_debug.get("planner_type") != expected_planner_type:
        errors.append("planner_type_mismatch")

    expected_multi_hop = case.get("expected_multi_hop")
    requires_multi_hop = planner_debug.get("requires_multi_hop") is True
    if expected_multi_hop is not None and requires_multi_hop is not expected_multi_hop:
        errors.append("requires_multi_hop_mismatch")
    if planner_mode == "active" and expected_multi_hop and "multi_hop_retriever" not in nodes:
        errors.append("multi_hop_retriever_missing")
    if planner_mode == "debug_only" and "multi_hop_retriever" in nodes:
        errors.append("debug_only_unexpected_multi_hop_retriever")
    if (
        planner_mode == "debug_only"
        and planner_debug
        and "planner" in nodes
        and planner_debug.get("side_effects_enabled") is not False
    ):
        errors.append("debug_only_side_effects_not_disabled")
    if (
        planner_mode == "debug_only"
        and expected_multi_hop
        and planner_debug.get("multi_hop_disabled_by_planner_debug_only") is not True
    ):
        errors.append("debug_only_multi_hop_not_marked_disabled")
    if planner_mode == "active" and not expected_multi_hop and "multi_hop_retriever" in nodes:
        errors.append("unexpected_multi_hop_retriever")

    if expected_multi_hop:
        sub_queries = planner_debug.get("sub_queries") or []
        expected_min = int(case.get("expected_sub_query_min") or 2)
        if len(sub_queries) < expected_min:
            errors.append("sub_query_count_too_low")
    if graph_debug.get("writes_chroma") is not False:
        errors.append("writes_chroma_not_false")
    return errors


async def run_mode_smoke(planner_mode: str) -> dict[str, Any]:
    cases = _load_cases()
    graph = build_enterprise_rag_graph(
        retriever=fake_retriever,
        answer_generator=fake_answer_generator,
        verifier_mode="rule_based",
    )
    results = []
    errors: list[dict[str, Any]] = []
    multi_hop_enabled_count = 0
    judge_debug_present_count = 0
    planner_debug_present_count = 0
    multi_hop_retriever_count = 0
    debug_only_disabled_count = 0

    for case in cases:
        response = await run_enterprise_rag_graph(
            case["query"],
            top_k=3,
            return_sources=True,
            graph=graph,
        )
        case_errors = _check_case(case, response, planner_mode=planner_mode)
        planner_debug = response.get("planner_debug") or {}
        judge_debug = response.get("judge_debug") or {}
        nodes = _nodes(response)
        if planner_debug:
            planner_debug_present_count += 1
        if judge_debug:
            judge_debug_present_count += 1
        if planner_debug.get("requires_multi_hop") is True:
            multi_hop_enabled_count += 1
        if "multi_hop_retriever" in nodes:
            multi_hop_retriever_count += 1
        if planner_debug.get("multi_hop_disabled_by_planner_debug_only") is True:
            debug_only_disabled_count += 1
        if case_errors:
            errors.append({"case_id": case["case_id"], "errors": case_errors})
        results.append(
            {
                "case_id": case["case_id"],
                "case_type": case["case_type"],
                "planner_mode": planner_mode,
                "planner_type": planner_debug.get("planner_type"),
                "side_effects_enabled": planner_debug.get("side_effects_enabled"),
                "requires_multi_hop": planner_debug.get("requires_multi_hop"),
                "nodes_executed": nodes,
                "judge_mode": judge_debug.get("judge_mode"),
                "error_count": len(case_errors),
            }
        )

    summary = {
        "phase": "7A_planner_multihop_judge_prototype",
        "planner_mode": planner_mode,
        "planner_side_effects_enabled": planner_mode == "active",
        "case_count": len(cases),
        "planner_debug_present_count": planner_debug_present_count,
        "multi_hop_enabled_count": multi_hop_enabled_count,
        "multi_hop_retriever_count": multi_hop_retriever_count,
        "multi_hop_disabled_by_planner_debug_only": debug_only_disabled_count,
        "judge_debug_present_count": judge_debug_present_count,
        "rule_based_planner": True,
        "rule_based_judge": True,
        "calls_real_llm": False,
        "writes_chroma": False,
        "runs_240_case": False,
        "error_count": len(errors),
        "errors": errors,
        "results": results,
    }
    summary["recommended_checkpoint"] = bool(
        summary["case_count"] >= 8
        and summary["planner_debug_present_count"] == summary["case_count"]
        and summary["multi_hop_enabled_count"] >= 2
        and (
            (
                planner_mode == "active"
                and summary["multi_hop_retriever_count"] >= 2
            )
            or (
                planner_mode == "debug_only"
                and summary["multi_hop_retriever_count"] == 0
                and summary["multi_hop_disabled_by_planner_debug_only"] >= 2
            )
        )
        and summary["judge_debug_present_count"] >= summary["case_count"] - 2
        and summary["calls_real_llm"] is False
        and summary["writes_chroma"] is False
        and summary["runs_240_case"] is False
        and summary["error_count"] == 0
    )
    return summary


async def run_smoke() -> dict[str, Any]:
    previous_mode = os.environ.get("ENTERPRISE_PLANNER_MODE")
    previous_multi_hop_mode = os.environ.get("ENTERPRISE_MULTI_HOP_MODE")
    try:
        os.environ["ENTERPRISE_PLANNER_MODE"] = "active"
        os.environ["ENTERPRISE_MULTI_HOP_MODE"] = "rule_based"
        active_summary = await run_mode_smoke("active")
        os.environ["ENTERPRISE_PLANNER_MODE"] = "debug_only"
        os.environ["ENTERPRISE_MULTI_HOP_MODE"] = "off"
        debug_only_summary = await run_mode_smoke("debug_only")
    finally:
        if previous_mode is None:
            os.environ.pop("ENTERPRISE_PLANNER_MODE", None)
        else:
            os.environ["ENTERPRISE_PLANNER_MODE"] = previous_mode
        if previous_multi_hop_mode is None:
            os.environ.pop("ENTERPRISE_MULTI_HOP_MODE", None)
        else:
            os.environ["ENTERPRISE_MULTI_HOP_MODE"] = previous_multi_hop_mode

    summary = {
        "phase": "7A_planner_multihop_judge_prototype",
        "planner_mode": "active_and_debug_only",
        "active": active_summary,
        "debug_only": debug_only_summary,
        "case_count": active_summary["case_count"],
        "planner_debug_present_count": debug_only_summary["planner_debug_present_count"],
        "multi_hop_enabled_count": active_summary["multi_hop_enabled_count"],
        "judge_debug_present_count": debug_only_summary["judge_debug_present_count"],
        "planner_side_effects_enabled": {
            "active": True,
            "debug_only": False,
        },
        "multi_hop_disabled_by_planner_debug_only": debug_only_summary[
            "multi_hop_disabled_by_planner_debug_only"
        ],
        "calls_real_llm": False,
        "writes_chroma": False,
        "runs_240_case": False,
        "error_count": active_summary["error_count"] + debug_only_summary["error_count"],
        "recommended_checkpoint": active_summary["recommended_checkpoint"]
        and debug_only_summary["recommended_checkpoint"],
    }
    return summary


def main() -> int:
    summary = asyncio.run(run_smoke())
    SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY_PATH.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["recommended_checkpoint"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
