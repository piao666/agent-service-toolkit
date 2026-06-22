from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

os.environ["USE_FAKE_MODEL"] = "true"
os.environ["ENTERPRISE_AGENT_GRAPH_MODE"] = "custom_graph"
os.environ["ENTERPRISE_MEMORY_MODE"] = "buffer"
os.environ["ENTERPRISE_EVIDENCE_VERIFIER_MODE"] = "rule_based"

import httpx  # noqa: E402

import agents.enterprise_rag_graph as graph_module  # noqa: E402
from rag.config import rag_settings  # noqa: E402
from schema import ChatMessage  # noqa: E402
from service.service import app  # noqa: E402

OUTPUT_PATH = (
    REPO_ROOT
    / "data/knowledge_base/evaluation/phase6l_custom_graph_endpoint_smoke.json"
)


def run_subprocess_env_smoke() -> tuple[bool, list[str]]:
    child_code = r'''
import json

from rag.config import rag_settings

print(json.dumps({"resolved_mode": rag_settings.agent_graph_mode}))
'''
    child_env = os.environ.copy()
    child_env.update(
        {
            "PYTHONPATH": str(SRC_DIR),
            "USE_FAKE_MODEL": "true",
            "ENTERPRISE_AGENT_GRAPH_MODE": "custom_graph",
            "ENTERPRISE_MEMORY_MODE": "off",
            "ENTERPRISE_EVIDENCE_VERIFIER_MODE": "off",
        }
    )
    completed = subprocess.run(
        [sys.executable, "-c", child_code],
        cwd=REPO_ROOT,
        env=child_env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    errors: list[str] = []
    if completed.returncode != 0:
        errors.append(f"subprocess_exit_{completed.returncode}")
        return False, errors
    try:
        result = json.loads(completed.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        errors.append("subprocess_invalid_json")
        return False, errors
    mode_ok = result.get("resolved_mode") == "custom_graph"
    return mode_ok, errors


def fake_retriever(query: str, top_k: int | None) -> dict[str, object]:
    sources = [
        {
            "source_id": "rag_overview",
            "title": "RAG Overview",
            "doc_type": "markdown",
            "section_path": "Concepts / RAG",
            "source_url": "https://docs.example.invalid/rag-overview",
            "chunk_id": "rag-overview-001",
            "content_preview": (
                "RAG combines retrieved evidence with answer generation and source tracing."
            ),
            "relevance_score": 0.95,
            "metadata": {"source_id": "rag_overview"},
        }
    ][: max(1, int(top_k or 1))]
    return {
        "context": sources[0]["content_preview"],
        "sources": sources,
        "retrieval_debug": {
            "hit_count": len(sources),
            "embedding_provider": "smoke_stub",
            "vector_store": "none",
        },
        "fallback": {"triggered": False, "reason": None},
    }


async def run_smoke() -> dict[str, object]:
    errors: list[str] = []
    original_graph_mode_env = os.environ.get("ENTERPRISE_AGENT_GRAPH_MODE")
    original_graph_mode = rag_settings.ENTERPRISE_AGENT_GRAPH_MODE
    original_memory_mode = rag_settings.ENTERPRISE_MEMORY_MODE
    original_verifier_mode = rag_settings.ENTERPRISE_EVIDENCE_VERIFIER_MODE
    original_cached_graph = graph_module._enterprise_rag_graph
    try:
        os.environ["ENTERPRISE_AGENT_GRAPH_MODE"] = "custom_graph"
        rag_settings.ENTERPRISE_AGENT_GRAPH_MODE = "custom_graph"
        rag_settings.ENTERPRISE_MEMORY_MODE = "buffer"
        rag_settings.ENTERPRISE_EVIDENCE_VERIFIER_MODE = "rule_based"
        graph_module._enterprise_rag_graph = graph_module.build_enterprise_rag_graph(
            retriever=fake_retriever,
            verifier_mode="rule_based",
        )

        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://phase6l-smoke.local",
        ) as client:
            custom_response = await client.post(
                "/enterprise/agent/query",
                json={
                    "query": "What is RAG?",
                    "session_id": "phase6l-custom-graph-smoke",
                    "top_k": 3,
                    "return_sources": True,
                    "model": "fake",
                },
            )
            custom_payload = custom_response.json()

            with patch(
                "agents.enterprise_rag_graph.get_model",
                side_effect=RuntimeError("smoke model failure"),
            ):
                fallback_response = await client.post(
                    "/enterprise/agent/query",
                    json={
                        "query": "What is RAG?",
                        "session_id": "phase6l-model-fallback-smoke",
                        "top_k": 3,
                        "return_sources": True,
                        "model": "fake",
                    },
                )
            fallback_payload = fallback_response.json()

            os.environ["ENTERPRISE_AGENT_GRAPH_MODE"] = "legacy"
            rag_settings.ENTERPRISE_AGENT_GRAPH_MODE = "legacy"
            legacy_output = ChatMessage(
                type="ai",
                content="Legacy endpoint response.",
                response_metadata={
                    "answer": "Legacy endpoint response.",
                    "sources": [],
                    "retrieval_debug": {"hit_count": 0},
                    "model_debug": {"provider": "fake", "model": "fake"},
                    "memory_debug": {},
                    "verifier_debug": {},
                    "fallback": {"triggered": False, "reason": None},
                },
            )
            with patch(
                "service.service.invoke",
                new=AsyncMock(return_value=legacy_output),
            ):
                legacy_response = await client.post(
                    "/enterprise/agent/query",
                    json={
                        "query": "What is RAG?",
                        "session_id": "phase6l-legacy-smoke",
                        "top_k": 3,
                        "return_sources": True,
                        "model": "fake",
                    },
                )
            legacy_payload = legacy_response.json()

        graph_debug = dict(custom_payload.get("graph_debug") or {})
        required_fields = {
            "answer",
            "sources",
            "retrieval_debug",
            "memory_debug",
            "verifier_debug",
            "graph_debug",
            "model_debug",
            "fallback",
            "session_id",
        }
        custom_graph_status_ok = custom_response.status_code == 200
        custom_graph_response_schema_ok = required_fields.issubset(custom_payload)
        graph_debug_present = bool(graph_debug)
        graph_mode_is_custom = graph_debug.get("graph_mode") == "custom_graph"
        nodes_executed = graph_debug.get("nodes_executed")
        nodes_executed_count = len(nodes_executed) if isinstance(nodes_executed, list) else 0
        nodes_executed_present = nodes_executed_count > 0
        model_provider_is_custom = (
            custom_payload.get("model_debug", {}).get("provider") == "custom_graph"
        )
        calls_real_llm = bool(graph_debug.get("calls_real_llm", False))
        calls_llm = bool(graph_debug.get("calls_llm", False))
        writes_chroma = bool(graph_debug.get("writes_chroma", False))
        model_failure_safe_fallback = bool(
            fallback_response.status_code == 200
            and fallback_payload.get("answer")
            and fallback_payload.get("fallback", {}).get("triggered") is True
            and fallback_payload.get("fallback", {}).get("reason") == "model_error"
        )
        legacy_mode_still_available = bool(
            legacy_response.status_code == 200
            and legacy_payload.get("answer") == "Legacy endpoint response."
            and legacy_payload.get("graph_debug") == {}
        )
    except Exception as exc:
        errors.append(f"{type(exc).__name__}: {exc}")
        custom_graph_status_ok = False
        custom_graph_response_schema_ok = False
        graph_debug_present = False
        graph_mode_is_custom = False
        nodes_executed_present = False
        nodes_executed_count = 0
        model_provider_is_custom = False
        calls_real_llm = False
        calls_llm = False
        writes_chroma = False
        model_failure_safe_fallback = False
        legacy_mode_still_available = False
    finally:
        graph_module._enterprise_rag_graph = original_cached_graph
        rag_settings.ENTERPRISE_AGENT_GRAPH_MODE = original_graph_mode
        rag_settings.ENTERPRISE_MEMORY_MODE = original_memory_mode
        rag_settings.ENTERPRISE_EVIDENCE_VERIFIER_MODE = original_verifier_mode
        if original_graph_mode_env is None:
            os.environ.pop("ENTERPRISE_AGENT_GRAPH_MODE", None)
        else:
            os.environ["ENTERPRISE_AGENT_GRAPH_MODE"] = original_graph_mode_env

    subprocess_mode_ok, subprocess_errors = run_subprocess_env_smoke()
    errors.extend(subprocess_errors)

    summary = {
        "phase": "6L_custom_graph_endpoint_smoke",
        "custom_graph_status_ok": custom_graph_status_ok,
        "custom_graph_response_schema_ok": custom_graph_response_schema_ok,
        "graph_debug_present": graph_debug_present,
        "graph_mode_is_custom": graph_mode_is_custom,
        "nodes_executed_present": nodes_executed_present,
        "nodes_executed_count": nodes_executed_count,
        "model_provider_is_custom": model_provider_is_custom,
        "legacy_mode_still_available": legacy_mode_still_available,
        "model_failure_safe_fallback": model_failure_safe_fallback,
        "env_precedence_ok": subprocess_mode_ok,
        "subprocess_custom_graph_mode_ok": subprocess_mode_ok,
        "calls_llm": calls_llm,
        "calls_real_llm": calls_real_llm,
        "writes_chroma": writes_chroma,
        "starts_long_running_service": False,
        "error_count": len(errors),
        "errors": errors,
    }
    required_checks = (
        "custom_graph_status_ok",
        "custom_graph_response_schema_ok",
        "graph_debug_present",
        "graph_mode_is_custom",
        "nodes_executed_present",
        "model_provider_is_custom",
        "legacy_mode_still_available",
        "model_failure_safe_fallback",
        "env_precedence_ok",
        "subprocess_custom_graph_mode_ok",
    )
    summary["recommended_checkpoint"] = False
    summary["phase6l1_acceptance_passed"] = bool(
        all(summary[key] is True for key in required_checks)
        and summary["calls_llm"] is False
        and summary["calls_real_llm"] is False
        and summary["writes_chroma"] is False
        and summary["error_count"] == 0
    )

    return summary


def main() -> int:
    summary = asyncio.run(run_smoke())
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0 if summary["phase6l1_acceptance_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
