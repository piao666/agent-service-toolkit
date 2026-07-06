#!/usr/bin/env python3
"""Phase 5B Smoke: Graph API -- import + direct call + runtime endpoint validation.

Verifies:
  1. Schema models importable with all required fields
  2. run_custom_graph direct call returns 14+ trace fields
  3. Mock fallback when no API key
  4. Runtime: FastAPI router has /api/enterprise-kb/graph/answer registered (POST)
  5. Runtime: TestClient POST returns 200 with all 15 response fields
"""

import json, sys
from pathlib import Path
from datetime import datetime, timezone
from unittest.mock import MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))
REPORTS = Path(__file__).resolve().parent.parent.parent / "reports" / "enterprise_kb_v1"
REPORTS.mkdir(parents=True, exist_ok=True)

ENDPOINT_PATH = "/api/enterprise-kb/graph/answer"


# -- Test 1: Schema import -------------------------------------------------

def test_schema_import():
    """Verify new graph schema models importable."""
    try:
        from schema import EnterpriseKBGraphAnswerRequest, EnterpriseKBGraphAnswerResponse
        req_fields = list(EnterpriseKBGraphAnswerRequest.model_fields.keys())
        resp_fields = list(EnterpriseKBGraphAnswerResponse.model_fields.keys())
        return {
            "importable": True,
            "request_fields": req_fields,
            "response_fields": resp_fields,
            "request_has_query": "query" in req_fields,
            "request_has_corpus": "corpus" in req_fields,
            "request_has_session_id": "session_id" in req_fields,
            "response_has_answer_markdown": "answer_markdown" in resp_fields,
            "response_has_citations": "citations" in resp_fields,
            "response_has_all_traces": all(
                t in resp_fields for t in [
                    "intent_trace", "rewrite_trace", "plan_trace",
                    "retrieval_trace", "rank_trace", "llm_trace",
                    "citation_trace", "graph_debug",
                ]
            ),
        }
    except Exception as e:
        return {"importable": False, "error": str(e)[:200]}


# -- Test 2: Direct call ---------------------------------------------------

def test_direct_call():
    """Call run_custom_graph directly (no HTTP server)."""
    from custom_graph.graph import run_custom_graph
    from llm.client import LLMClient

    llm = LLMClient()
    resp = run_custom_graph("What is retrieval augmented generation?", corpus="auto", llm=llm)

    field_checks = {
        "answer_markdown": bool(resp.get("answer_markdown")),
        "citations": isinstance(resp.get("citations"), list),
        "used_sources": isinstance(resp.get("used_sources"), list),
        "unsupported_claims": isinstance(resp.get("unsupported_claims"), list),
        "hallucination_risk": resp.get("hallucination_risk") in ("none", "low", "medium", "high"),
        "intent_trace": bool(resp.get("intent_trace")),
        "rewrite_trace": bool(resp.get("rewrite_trace")),
        "plan_trace": bool(resp.get("plan_trace")),
        "retrieval_trace": bool(resp.get("retrieval_trace")),
        "rank_trace": bool(resp.get("rank_trace")),
        "llm_trace": bool(resp.get("llm_trace")),
        "citation_trace": bool(resp.get("citation_trace")),
        "graph_debug": bool(resp.get("graph_debug")),
        "llm_mode": resp.get("llm_mode") == "mock_extractive",
    }
    all_ok = all(field_checks.values())
    return {"all_fields_present": all_ok, "field_checks": field_checks, "llm_mode": resp.get("llm_mode")}


# -- Test 3: Mock fallback -------------------------------------------------

def test_mock_fallback():
    """Verify no-key fallback works."""
    import os
    saved = {}
    for key in ["QWEN_API_KEY", "DEEPSEEK_API_KEY"]:
        saved[key] = os.environ.pop(key, None)
    try:
        from llm.client import LLMClient
        llm = LLMClient()
        return {"is_mock": llm.is_mock, "provider": llm.provider_name, "pass": llm.is_mock}
    except Exception as e:
        return {"pass": False, "error": str(e)[:200]}
    finally:
        for key, val in saved.items():
            if val is not None:
                os.environ[key] = val


# -- Test 4: Endpoint verification -----------------------------------------

def _static_check_service_py():
    """Read service.py source and statically verify the endpoint code exists.

    Does NOT import the module -- no runtime deps needed.
    """
    service_py = Path(__file__).resolve().parent.parent.parent / "src" / "service" / "service.py"
    source = service_py.read_text(encoding="utf-8")

    checks = {
        "route_decorator_found": f'@router.post("{ENDPOINT_PATH}")' in source,
        "async_def_found": "async def enterprise_kb_graph_answer" in source,
        "import_request_model": "EnterpriseKBGraphAnswerRequest" in source,
        "import_response_model": "EnterpriseKBGraphAnswerResponse" in source,
        "import_run_custom_graph": "from custom_graph.graph import run_custom_graph" in source,
        "import_llm_client": "from llm.client import LLMClient" in source,
    }
    checks["all_static_checks_pass"] = all(checks.values())
    return checks


def test_endpoint_registered():
    """Verify /api/enterprise-kb/graph/answer endpoint exists at runtime.

    Strategy:
      1. Static: scan service.py source for route decorator (no deps).
      2. Runtime (mock): import service with heavy agents mocked, verify route
         is registered on the real FastAPI router.
      3. TestClient: issue a real POST and validate response.

    Heavy agent modules (MCP, langgraph runtime, etc.) are mocked because
    they are irrelevant to the graph answer endpoint and have version
    conflicts in this smoke environment. The endpoint function itself
    (enterprise_kb_graph_answer) runs with real custom_graph + llm modules.
    """
    result = {
        # Static
        "endpoint_static_check_pass": False,
        "static_check": {},
        # Runtime (mock-assisted)
        "endpoint_runtime_registered": False,
        "runtime_route_check": {},
        # TestClient
        "testclient_call_ok": False,
        "testclient_response_fields": [],
        # Misc
        "runtime_check_skipped": False,
        "runtime_skip_reason": None,
    }

    # Step 1: Static source analysis (always runs, zero deps)
    static = _static_check_service_py()
    result["static_check"] = static
    result["endpoint_static_check_pass"] = static.get("all_static_checks_pass", False)

    # Step 2: Runtime route inspection (mock heavy agents, real FastAPI router)
    try:
        # Mock agent modules that are irrelevant to the graph answer endpoint
        _mock_heavy_deps()

        from service.service import app, router

        found = False
        route_methods = []
        for route in router.routes:
            if hasattr(route, "path") and route.path == ENDPOINT_PATH:
                found = True
                route_methods = list(route.methods) if hasattr(route, "methods") else []
                break

        result["endpoint_runtime_registered"] = found
        result["runtime_route_check"] = {
            "route_found_in_router": found,
            "route_methods": route_methods,
            "has_post_method": "POST" in route_methods,
            "app_type": type(app).__name__,
            "router_type": type(router).__name__,
        }

        # Step 3: TestClient call (only if route is registered)
        if found:
            try:
                from fastapi.testclient import TestClient

                client = TestClient(app)
                resp = client.post(ENDPOINT_PATH, json={
                    "query": "What is FastAPI middleware?",
                    "corpus": "auto",
                })

                if resp.status_code == 200:
                    data = resp.json()
                    result["testclient_call_ok"] = True
                    result["testclient_status_code"] = resp.status_code
                    result["testclient_response_fields"] = sorted(data.keys())
                    result["testclient_has_answer_markdown"] = bool(data.get("answer_markdown"))
                    result["testclient_has_citations"] = isinstance(data.get("citations"), list)
                    result["testclient_has_total_latency_ms"] = data.get("total_latency_ms", 0) > 0
                    result["testclient_llm_mode"] = data.get("llm_mode", "?")
                    result["testclient_field_count"] = len(data)
                else:
                    result["testclient_call_ok"] = False
                    result["testclient_status_code"] = resp.status_code
                    result["testclient_error"] = resp.text[:500]
            except Exception as e:
                result["testclient_call_ok"] = False
                result["testclient_error"] = str(e)[:200]

    except ImportError as e:
        result["runtime_check_skipped"] = True
        result["runtime_skip_reason"] = f"Import failed even with mocks: {e}"
    except Exception as e:
        result["runtime_check_skipped"] = True
        result["runtime_skip_reason"] = str(e)[:200]

    finally:
        # Clean up mocked modules so they don't pollute other tests
        _unmock_heavy_deps()

    return result


def _mock_heavy_deps():
    """Pre-register mocks for agent modules irrelevant to graph answer endpoint.

    These modules (MCP agents, langgraph runtime internals) have heavy deps
    and version conflicts. The graph answer endpoint does NOT depend on them --
    it only needs custom_graph + llm modules which are imported at call time.
    """
    import sys
    _saved = {}
    _modules_to_mock = [
        "agents",
        "agents.agents",
        "agents.github_mcp_agent",
        "agents.github_mcp_agent.github_mcp_agent",
        "langchain_mcp_adapters",
        "langchain_mcp_adapters.client",
        "langchain_mcp_adapters.sessions",
        "mcp.client.streamable_http",
    ]
    for mod in _modules_to_mock:
        if mod not in sys.modules:
            sys.modules[mod] = MagicMock()
            _saved[mod] = True  # mark as newly mocked

    # Store for cleanup
    _mock_heavy_deps._saved = _saved
    _mock_heavy_deps._modules = _modules_to_mock


def _unmock_heavy_deps():
    """Remove mock modules to avoid polluting other tests."""
    import sys
    saved = getattr(_mock_heavy_deps, "_saved", {})
    for mod in getattr(_mock_heavy_deps, "_modules", []):
        if saved.get(mod):
            sys.modules.pop(mod, None)


# -- Main ------------------------------------------------------------------

def main():
    print("=== Phase 5B Smoke: Graph API ===")
    results = {"smoke": "phase5b_graph_api", "timestamp": datetime.now(timezone.utc).isoformat()}

    # 1. Schema
    schema = test_schema_import()
    print(f"  Schema: importable={schema['importable']} all_traces={schema.get('response_has_all_traces','?')}")
    results["schema"] = schema

    # 2. Direct call
    call = test_direct_call()
    print(f"  Direct call: all_fields={call['all_fields_present']} mode={call['llm_mode']}")
    results["direct_call"] = call

    # 3. Mock fallback
    fb = test_mock_fallback()
    print(f"  Mock fallback: is_mock={fb.get('is_mock','?')}")
    results["mock_fallback"] = fb

    # 4. Endpoint (static + runtime + TestClient)
    ep = test_endpoint_registered()
    print(f"  Endpoint static: {ep['endpoint_static_check_pass']}")
    print(f"  Endpoint runtime: registered={ep['endpoint_runtime_registered']} methods={ep['runtime_route_check'].get('route_methods',[])}")
    print(f"  TestClient: ok={ep['testclient_call_ok']} fields={len(ep.get('testclient_response_fields',[]))}")
    if ep.get("runtime_check_skipped"):
        print(f"  WARNING: runtime check skipped: {ep.get('runtime_skip_reason','?')[:120]}")
    results["endpoint_check"] = ep

    # Overall pass -- requires RUNTIME route registration + TestClient
    results["overall_pass"] = (
        schema.get("importable", False)
        and schema.get("response_has_all_traces", False)
        and call.get("all_fields_present", False)
        and fb.get("pass", False)
        and ep.get("endpoint_static_check_pass", False)
        and ep.get("endpoint_runtime_registered", False)
        and ep.get("testclient_call_ok", False)
    )

    path = REPORTS / "phase5b_graph_api_smoke.json"
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
