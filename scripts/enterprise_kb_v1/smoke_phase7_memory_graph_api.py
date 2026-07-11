#!/usr/bin/env python3
"""Phase 7 v1.3 Smoke: Memory Graph API — multi-turn + auto session_id propagation.

Covers:
  1. FastAPI endpoint registered + TestClient 200
  2. Multi-turn with explicit session_id
  3. No-session auto id propagation (turn1 gen → turn2 carry)
  4. memory_trace fields complete
  5. graph_debug has memory fields
"""

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))
REPORTS = Path(__file__).resolve().parent.parent.parent / "reports" / "enterprise_kb_v1"
REPORTS.mkdir(parents=True, exist_ok=True)

ENDPOINT_PATH = "/api/enterprise-kb/graph/answer"


def test_endpoint_api_multi_turn():
    """TestClient 两轮对话：turn2 rewrite_used_memory=true。"""
    result = {
        "endpoint_registered": False,
        "testclient_available": False,
        "testclient_status_code": 0,
        "response_has_memory_trace": False,
        "multi_turn_api_memory_pass": False,
        "skipped": True,
        "skipped_reason": "",
    }
    # Static
    sp = Path(__file__).resolve().parent.parent.parent / "src" / "service" / "service.py"
    if sp.exists():
        result["endpoint_registered"] = f'@router.post("{ENDPOINT_PATH}")' in sp.read_text(
            encoding="utf-8"
        )

    try:
        from unittest.mock import MagicMock

        from fastapi.testclient import TestClient

        result["testclient_available"] = True
        saved = {}
        for mod in [
            "agents",
            "agents.agents",
            "agents.github_mcp_agent",
            "agents.github_mcp_agent.github_mcp_agent",
            "langchain_mcp_adapters",
            "langchain_mcp_adapters.client",
            "langchain_mcp_adapters.sessions",
            "mcp.client.streamable_http",
        ]:
            if mod not in sys.modules:
                sys.modules[mod] = MagicMock()
                saved[mod] = True
        try:
            from core.settings import settings
            from service.service import app

            settings.AUTH_SECRET = None
            client = TestClient(app)
            sid = "p7_api_test"
            r1 = client.post(
                ENDPOINT_PATH,
                json={
                    "query": "internal_engineering_docs 是什么？",
                    "corpus": "auto",
                    "session_id": sid,
                },
            )
            result["turn1_status"] = r1.status_code
            r2 = client.post(
                ENDPOINT_PATH,
                json={
                    "query": "它和 official_docs 有什么区别？",
                    "corpus": "auto",
                    "session_id": sid,
                },
            )
            result["turn2_status"] = r2.status_code
            d2 = r2.json()
            mt2 = d2.get("memory_trace", {})
            gd = d2.get("graph_debug", {})
            result["testclient_status_code"] = r2.status_code
            result["response_has_memory_trace"] = "memory_trace" in d2
            result["graph_debug_memory_read"] = "memory_read_used" in gd
            result["graph_debug_memory_write"] = "memory_write_status" in gd
            result["turn2_rewrite_used"] = mt2.get("rewrite_used_memory", False)
            result["turn2_recent_turns"] = mt2.get("recent_turns_count", 0)
            result["has_candidate_not_committed"] = mt2.get("candidate_only_not_committed", False)
            result["multi_turn_api_memory_pass"] = (
                r1.status_code == 200
                and r2.status_code == 200
                and mt2.get("rewrite_used_memory") is True
                and mt2.get("recent_turns_count", 0) >= 1
            )
            result["skipped"] = False
        finally:
            for mod in saved:
                sys.modules.pop(mod, None)
    except ImportError as e:
        result["skipped_reason"] = f"ImportError: {e}"
    except Exception as e:
        result["skipped_reason"] = str(e)[:200]

    result["pass"] = (
        result["endpoint_registered"]
        and result.get("testclient_available", False)
        and result.get("turn1_status") == 200
        and result.get("turn2_status") == 200
        and result.get("response_has_memory_trace", False)
        and result.get("multi_turn_api_memory_pass", False)
        and result.get("graph_debug_memory_read", False)
        and result.get("turn2_rewrite_used", False)
        and result.get("turn2_recent_turns", 0) >= 1
        and result.get("has_candidate_not_committed", False)
    )
    return result


def test_no_session_auto_id_multiturn():
    """v1.3: turn1 无 session_id → auto_xxxxxxxx → turn2 携带 auto id 验证多轮。"""
    result = {
        "no_session_auto_id_multiturn_pass": False,
        "auto_session_id_propagated_to_state": False,
        "turn1_auto_id": "",
        "skipped": True,
        "skipped_reason": "",
    }
    try:
        from unittest.mock import MagicMock

        from fastapi.testclient import TestClient

        saved = {}
        for mod in [
            "agents",
            "agents.agents",
            "agents.github_mcp_agent",
            "agents.github_mcp_agent.github_mcp_agent",
            "langchain_mcp_adapters",
            "langchain_mcp_adapters.client",
            "langchain_mcp_adapters.sessions",
            "mcp.client.streamable_http",
        ]:
            if mod not in sys.modules:
                sys.modules[mod] = MagicMock()
                saved[mod] = True
        try:
            from core.settings import settings
            from service.service import app

            settings.AUTH_SECRET = None
            client = TestClient(app)
            # Turn 1: no session_id
            r1 = client.post(
                ENDPOINT_PATH,
                json={"query": "internal_engineering_docs 是什么？", "corpus": "auto"},
            )
            mt1 = r1.json().get("memory_trace", {})
            auto_sid = mt1.get("session_id", "")
            result["turn1_status"] = r1.status_code
            result["turn1_auto_id"] = auto_sid
            result["turn1_auto_generated"] = mt1.get("auto_generated_session_id", False)
            # Turn 2: carry auto id
            r2 = client.post(
                ENDPOINT_PATH,
                json={
                    "query": "它和 official_docs 有什么区别？",
                    "corpus": "auto",
                    "session_id": auto_sid,
                },
            )
            mt2 = r2.json().get("memory_trace", {})
            rt2 = r2.json().get("rewrite_trace", {})
            rewritten = rt2.get("rewritten_query", "")
            result["turn2_status"] = r2.status_code
            result["turn2_session_id"] = mt2.get("session_id", "")
            result["turn2_recent_turns"] = mt2.get("recent_turns_count", 0)
            result["turn2_rewrite_used"] = mt2.get("rewrite_used_memory", False)
            result["turn2_rewrite_has_internal"] = "internal_engineering_docs" in rewritten
            result["turn2_rewrite_has_official"] = "official_docs" in rewritten
            result["auto_session_id_propagated_to_state"] = (
                auto_sid.startswith("auto_")
                and mt2.get("session_id") == auto_sid
                and mt2.get("recent_turns_count", 0) >= 1
            )
            result["no_session_auto_id_multiturn_pass"] = (
                r1.status_code == 200
                and auto_sid.startswith("auto_")
                and mt1.get("auto_generated_session_id") is True
                and r2.status_code == 200
                and mt2.get("session_id") == auto_sid
                and mt2.get("recent_turns_count", 0) >= 1
                and mt2.get("rewrite_used_memory") is True
                and "internal_engineering_docs" in rewritten
                and "official_docs" in rewritten
            )
            result["skipped"] = False
        finally:
            for mod in saved:
                sys.modules.pop(mod, None)
    except ImportError as e:
        result["skipped_reason"] = f"ImportError: {e}"
    except Exception as e:
        result["skipped_reason"] = str(e)[:200]

    result["pass"] = result["no_session_auto_id_multiturn_pass"]
    return result


def test_direct_call_memory_trace():
    from custom_graph.graph import run_custom_graph
    from llm.client import LLMClient

    llm = LLMClient()
    resp = run_custom_graph("检索 channel 有哪些？", corpus="auto", session_id="p7_direct", llm=llm)
    mt = resp.get("memory_trace", {})
    required = [
        "session_id",
        "memory_read_used",
        "recent_turns_count",
        "active_topic",
        "rewrite_used_memory",
        "memory_context",
        "memory_write_candidate",
        "memory_write_status",
        "candidate_only_not_committed",
        "auto_generated_session_id",
    ]
    missing = [f for f in required if f not in mt]
    gd = resp.get("graph_debug", {})
    return {
        "fields_present": len(missing) == 0,
        "missing": missing,
        "graph_debug_memory": "memory_read_used" in gd,
        "candidate_only_not_committed": mt.get("candidate_only_not_committed", False),
        "pass": len(missing) == 0,
    }


def test_no_session_id_auto():
    from custom_graph.graph import run_custom_graph
    from llm.client import LLMClient

    llm = LLMClient()
    resp = run_custom_graph("What is FastAPI?", corpus="auto", session_id="", llm=llm)
    mt = resp.get("memory_trace", {})
    return {
        "session_id": mt.get("session_id", ""),
        "is_auto": mt.get("session_id", "").startswith("auto_"),
        "auto_generated_session_id": mt.get("auto_generated_session_id", False),
        "pass": mt.get("session_id", "").startswith("auto_")
        and mt.get("auto_generated_session_id") is True,
    }


def main():
    print("=== Phase 7 v1.3 Smoke: Memory Graph API ===")
    results = {"smoke": "phase7_memory_graph_api_v1.3", "timestamp": datetime.now(UTC).isoformat()}

    api = test_endpoint_api_multi_turn()
    print(
        f"  api: endpoint={api['endpoint_registered']} status={api.get('testclient_status_code')} multi_turn={api['multi_turn_api_memory_pass']}"
    )
    results["endpoint_api"] = api

    auto = test_no_session_auto_id_multiturn()
    print(
        f"  auto_id: pass={auto['no_session_auto_id_multiturn_pass']} propagated={auto['auto_session_id_propagated_to_state']} t1={auto.get('turn1_auto_id', '')[:20]}"
    )
    if auto["skipped"]:
        print(f"  auto_id skipped: {auto['skipped_reason'][:100]}")
    results["no_session_auto_id"] = auto

    dc = test_direct_call_memory_trace()
    print(f"  direct: fields={dc['fields_present']} gd_mem={dc['graph_debug_memory']}")
    results["direct_call"] = dc

    ns = test_no_session_id_auto()
    print(f"  no_session: auto={ns['is_auto']} auto_gen={ns['auto_generated_session_id']}")
    results["no_session_id"] = ns

    all_pass = api["pass"] and auto["pass"] and dc["pass"] and ns["pass"]
    results["overall_pass"] = all_pass

    path = REPORTS / "phase7_memory_graph_api_smoke.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\nSaved: {path}")
    print(f"Overall: {'PASS' if all_pass else 'FAIL'}")
    if not all_pass:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
