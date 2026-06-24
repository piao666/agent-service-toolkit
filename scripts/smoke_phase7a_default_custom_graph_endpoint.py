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

os.environ["USE_FAKE_MODEL"] = "true"
os.environ["ENTERPRISE_AGENT_GRAPH_MODE"] = "custom_graph"
os.environ["ENTERPRISE_MEMORY_MODE"] = "buffer"
os.environ["ENTERPRISE_EVIDENCE_VERIFIER_MODE"] = "rule_based"
os.environ["ENTERPRISE_JUDGE_MODE"] = "rule_based_fallback"
os.environ.setdefault("ENTERPRISE_PLANNER_MODE", "debug_only")

import httpx  # noqa: E402

from agents.enterprise_rag_graph import build_answer_synthesis_instruction  # noqa: E402
from rag.config import rag_settings  # noqa: E402
from service.service import app  # noqa: E402

CASES = [
    {
        "case_id": "default_simple",
        "query": "What is RAG?",
        "expect_judge": True,
        "expect_multi_hop": False,
    },
    {
        "case_id": "default_multi_hop",
        "query": "Compare RAG versus LoRA",
        "expect_judge": True,
        "expect_multi_hop": True,
    },
    {
        "case_id": "default_unsupported",
        "query": "What is the weather tomorrow?",
        "expect_judge": False,
        "expect_multi_hop": False,
    },
]


def _nodes(payload: dict[str, Any]) -> list[str]:
    return list((payload.get("graph_debug") or {}).get("nodes_executed") or [])


def _check_answer_synthesis_helper() -> dict[str, Any]:
    sources = [
        {
            "source_id": "fastapi_docs",
            "title": "FastAPI Request Body",
            "doc_type": "html",
            "chunk_id": "fastapi-body-001",
            "content_preview": (
                "FastAPI Request Body definitions use Pydantic models and endpoint schemas."
            ),
        }
    ]
    before_sequence = [source.get("source_id") for source in sources]
    instruction = build_answer_synthesis_instruction(
        "How does FastAPI define Request Body?",
        sources,
    )
    after_sequence = [source.get("source_id") for source in sources]
    return {
        "keyword_coverage_hint_present": "key user/source terms" in instruction,
        "answer_synthesis_profile_present": "keyword_coverage_v1" in instruction,
        "source_id_sequence_unchanged": before_sequence == after_sequence,
        "empty_sources_safe": bool(build_answer_synthesis_instruction("What is RAG?", [])),
    }


def _check_payload(
    *,
    status_code: int,
    payload: dict[str, Any],
    case: dict[str, Any],
) -> list[str]:
    errors: list[str] = []
    graph_debug = payload.get("graph_debug") or {}
    planner_debug = payload.get("planner_debug") or {}
    judge_debug = payload.get("judge_debug") or {}
    model_debug = payload.get("model_debug") or {}
    nodes = _nodes(payload)
    planner_mode = rag_settings.planner_mode

    if status_code != 200:
        errors.append(f"status_code_{status_code}")
    if not payload.get("answer"):
        errors.append("answer_empty")
    if not graph_debug:
        errors.append("graph_debug_missing")
    if graph_debug.get("graph_mode") != "custom_graph":
        errors.append("graph_mode_not_custom_graph")
    if not nodes:
        errors.append("nodes_executed_empty")
    if not planner_debug:
        errors.append("planner_debug_missing")
    if case["expect_judge"] and not judge_debug:
        errors.append("judge_debug_missing")
    if graph_debug.get("writes_chroma") is not False:
        errors.append("writes_chroma_not_false")
    if (
        model_debug.get("answer_synthesis_profile")
        and model_debug.get("answer_synthesis_profile") != "keyword_coverage_v1"
    ):
        errors.append("answer_synthesis_profile_unexpected")
    if "answer_generator" in nodes and not model_debug.get("answer_synthesis_profile"):
        errors.append("answer_synthesis_profile_missing")
    has_multi_hop_node = "multi_hop_retriever" in nodes
    if planner_mode == "active" and case["expect_multi_hop"] and not has_multi_hop_node:
        errors.append("multi_hop_retriever_missing")
    if planner_mode == "debug_only" and has_multi_hop_node:
        errors.append("debug_only_unexpected_multi_hop_retriever")
    if (
        planner_mode == "debug_only"
        and "planner" in nodes
        and planner_debug.get("side_effects_enabled") is not False
    ):
        errors.append("debug_only_side_effects_not_disabled")
    if planner_mode == "active" and not case["expect_multi_hop"] and has_multi_hop_node:
        errors.append("unexpected_multi_hop_retriever")
    return errors


async def run_smoke() -> dict[str, Any]:
    helper_summary = _check_answer_synthesis_helper()
    original_graph_mode = rag_settings.ENTERPRISE_AGENT_GRAPH_MODE
    original_memory_mode = rag_settings.ENTERPRISE_MEMORY_MODE
    original_verifier_mode = rag_settings.ENTERPRISE_EVIDENCE_VERIFIER_MODE
    original_judge_mode = rag_settings.ENTERPRISE_JUDGE_MODE
    original_planner_mode = rag_settings.ENTERPRISE_PLANNER_MODE
    rag_settings.ENTERPRISE_AGENT_GRAPH_MODE = "custom_graph"
    rag_settings.ENTERPRISE_MEMORY_MODE = "buffer"
    rag_settings.ENTERPRISE_EVIDENCE_VERIFIER_MODE = "rule_based"
    rag_settings.ENTERPRISE_JUDGE_MODE = "rule_based_fallback"
    rag_settings.ENTERPRISE_PLANNER_MODE = os.environ.get(
        "ENTERPRISE_PLANNER_MODE",
        "debug_only",
    )

    results: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://phase7a-default-smoke.local",
            timeout=60,
        ) as client:
            for case in CASES:
                response = await client.post(
                    "/enterprise/agent/query",
                    json={
                        "query": case["query"],
                        "session_id": f"phase7a-{case['case_id']}",
                        "top_k": 3,
                        "return_sources": True,
                        "model": "fake",
                    },
                )
                try:
                    payload = response.json()
                except json.JSONDecodeError:
                    payload = {}
                case_errors = _check_payload(
                    status_code=response.status_code,
                    payload=payload,
                    case=case,
                )
                if case_errors:
                    errors.append({"case_id": case["case_id"], "errors": case_errors})
                results.append(
                    {
                        "case_id": case["case_id"],
                        "status_code": response.status_code,
                        "answer_non_empty": bool(payload.get("answer")),
                        "graph_debug_present": bool(payload.get("graph_debug")),
                        "planner_debug_present": bool(payload.get("planner_debug")),
                        "planner_mode": rag_settings.planner_mode,
                        "judge_debug_present": bool(payload.get("judge_debug")),
                        "answer_synthesis_profile": (
                            payload.get("model_debug") or {}
                        ).get("answer_synthesis_profile"),
                        "nodes_executed": _nodes(payload),
                        "writes_chroma": bool(
                            (payload.get("graph_debug") or {}).get("writes_chroma", False)
                        ),
                        "error_count": len(case_errors),
                    }
                )
    finally:
        rag_settings.ENTERPRISE_AGENT_GRAPH_MODE = original_graph_mode
        rag_settings.ENTERPRISE_MEMORY_MODE = original_memory_mode
        rag_settings.ENTERPRISE_EVIDENCE_VERIFIER_MODE = original_verifier_mode
        rag_settings.ENTERPRISE_JUDGE_MODE = original_judge_mode
        rag_settings.ENTERPRISE_PLANNER_MODE = original_planner_mode

    summary = {
        "phase": "7A_default_custom_graph_endpoint_smoke",
        "planner_mode": rag_settings.planner_mode,
        "case_count": len(CASES),
        "status_ok_count": sum(1 for item in results if item["status_code"] == 200),
        "answer_non_empty_count": sum(1 for item in results if item["answer_non_empty"]),
        "graph_debug_present_count": sum(1 for item in results if item["graph_debug_present"]),
        "planner_debug_present_count": sum(1 for item in results if item["planner_debug_present"]),
        "judge_debug_present_count": sum(1 for item in results if item["judge_debug_present"]),
        "calls_real_llm": False,
        "writes_chroma": False,
        "runs_240_case": False,
        **helper_summary,
        "error_count": len(errors),
        "errors": errors,
        "results": results,
    }
    summary["acceptance_passed"] = bool(
        summary["status_ok_count"] == summary["case_count"]
        and summary["answer_non_empty_count"] == summary["case_count"]
        and summary["graph_debug_present_count"] == summary["case_count"]
        and summary["planner_debug_present_count"] == summary["case_count"]
        and summary["judge_debug_present_count"] >= 2
        and summary["writes_chroma"] is False
        and summary["calls_real_llm"] is False
        and summary["runs_240_case"] is False
        and summary["keyword_coverage_hint_present"] is True
        and summary["answer_synthesis_profile_present"] is True
        and summary["source_id_sequence_unchanged"] is True
        and summary["empty_sources_safe"] is True
        and summary["error_count"] == 0
    )
    return summary


def main() -> int:
    summary = asyncio.run(run_smoke())
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["acceptance_passed"] else 1


if __name__ == "__main__":
    exit_code = main()
    sys.stdout.flush()
    os._exit(exit_code)
