#!/usr/bin/env python3
"""Phase 8 v1.1 Smoke: Memory Admin API — full E2E lifecycle with TestClient.

Flow: query → pending candidate → approve → graph reads approved → disable → graph excludes.
"""

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))
REPORTS = Path(__file__).resolve().parent.parent.parent / "reports" / "enterprise_kb_v1"
REPORTS.mkdir(parents=True, exist_ok=True)

ENDPOINT = "/api/enterprise-kb/graph/answer"
SID = "p8_e2e_test"


def test_full_lifecycle():
    result = {
        "endpoint_registered": False,
        "testclient_available": False,
        "graph_create_candidate_ok": False,
        "has_pending": False,
        "approve_ok": False,
        "active_item_ok": False,
        "graph_reads_approved_memory": False,
        "disable_ok": False,
        "graph_excludes_disabled_memory": False,
        "events_ok": False,
        "skipped": True,
        "skipped_reason": "",
    }

    # Static check
    sp = Path(__file__).resolve().parent.parent.parent / "src" / "service" / "service.py"
    src = sp.read_text(encoding="utf-8")
    result["endpoint_registered"] = all(
        ep in src
        for ep in [
            "/api/enterprise-kb/memory/candidates",
            "/api/enterprise-kb/memory/items",
            "/api/enterprise-kb/memory/events",
        ]
    )

    try:
        from unittest.mock import MagicMock

        from fastapi.testclient import TestClient

        result["testclient_available"] = True

        # Isolate DB
        import long_term_memory.service as ltm_svc_mod
        import long_term_memory.sqlite_store as ltm_mod

        ltm_mod._global_ltm_store = None
        ltm_svc_mod._global_ltm_service = None
        DB_PATH = f"workspace/p8_e2e_{os.getpid()}.sqlite"
        ltm_mod.DEFAULT_DB_PATH = DB_PATH
        for f in Path("workspace").glob("p8_e2e_*"):
            try:
                f.unlink()
            except Exception:
                pass

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

            # A. Query triggers candidate creation
            rA = client.post(
                ENDPOINT,
                json={
                    "query": "本项目必须使用 HPC 执行所有 retrieval eval",
                    "corpus": "auto",
                    "session_id": SID,
                },
            )
            ltmA = rA.json().get("long_term_memory_trace", {})
            result["graph_create_candidate_ok"] = (
                rA.status_code == 200
                and "long_term_memory_trace" in rA.json()
                and ltmA.get("memory_write_status") == "pending_candidate_created"
            )
            # Verify pending NOT in LTM context (step A: before approve)
            ltmA_check = rA.json().get("long_term_memory_trace", {})
            result["pending_candidate_not_in_memory_context"] = (
                not ltmA_check.get("long_term_memory_used", False)
                and ltmA_check.get("approved_memory_count", 0) == 0
            )
            rewrite_A = rA.json().get("rewrite_trace", {})
            result["pending_not_used_for_rewrite"] = not rewrite_A.get(
                "long_term_memory_used_for_rewrite", False
            )
            result["graph_trace_A"] = {
                "write_status": ltmA.get("memory_write_status"),
                "pending_count": ltmA.get("pending_candidate_count"),
                "approved_count": ltmA.get("approved_memory_count"),
            }

            # B. List pending
            rB = client.get("/api/enterprise-kb/memory/candidates?status=pending")
            candidates = rB.json().get("candidates", [])
            candidate_id = candidates[0]["candidate_id"] if candidates else None
            result["has_pending"] = rB.status_code == 200 and len(candidates) >= 1
            result["pending_candidate_id"] = candidate_id

            if not candidate_id:
                result["skipped_reason"] = "No pending candidate found (step B)"
                result["skipped"] = True
                result["pass"] = False
                return result

            # C. Approve
            rC = client.post(f"/api/enterprise-kb/memory/candidates/{candidate_id}/approve")
            result["approve_ok"] = rC.status_code == 200 and rC.json().get("status") == "approved"

            # D. List active items
            rD = client.get("/api/enterprise-kb/memory/items?status=active")
            items = rD.json().get("items", [])
            memory_id = items[0]["memory_id"] if items else None
            result["active_item_ok"] = rD.status_code == 200 and len(items) >= 1
            result["approved_memory_id"] = memory_id

            # E. Second query — reads approved memory
            rE = client.post(
                ENDPOINT,
                json={
                    "query": "当前项目的 embedding 策略是什么？",
                    "corpus": "auto",
                    "session_id": SID,
                },
            )
            unrelated_ltm = rE.json().get("long_term_memory_trace", {})
            result["unrelated_approved_memory_not_applied"] = (
                rE.status_code == 200
                and unrelated_ltm.get("available_approved_memory_count", 0) >= 1
                and not unrelated_ltm.get("long_term_memory_used", False)
            )
            rE = client.post(
                ENDPOINT,
                json={
                    "query": "Where must this project run retrieval eval?",
                    "corpus": "auto",
                    "session_id": SID,
                },
            )
            ltmE = rE.json().get("long_term_memory_trace", {})
            result["graph_reads_approved_memory"] = (
                rE.status_code == 200
                and ltmE.get("long_term_memory_used") is True
                and ltmE.get("approved_memory_count", 0) >= 1
                and len(ltmE.get("approved_memory_ids", [])) >= 1
            )
            # Verify approved memory in context + used for rewrite
            rewrite_E = rE.json().get("rewrite_trace", {})
            ltmE = rE.json().get("long_term_memory_trace", {})
            result["approved_memory_context_attached"] = (
                ltmE.get("long_term_memory_used") is True
                and ltmE.get("approved_memory_count", 0) >= 1
            )
            result["graph_uses_approved_memory_for_answer"] = ltmE.get(
                "used_for_answer", False
            ) and memory_id in ltmE.get("applied_memory_ids", [])
            result["mock_does_not_claim_rewrite"] = not rewrite_E.get(
                "long_term_memory_used_for_rewrite", False
            ) and not rewrite_E.get("approved_memory_ids_used", [])
            result["graph_trace_E"] = {
                "ltm_used": ltmE.get("long_term_memory_used"),
                "approved_count": ltmE.get("approved_memory_count"),
                "approved_ids": ltmE.get("approved_memory_ids"),
                "ltm_used_for_rewrite": rewrite_E.get("long_term_memory_used_for_rewrite"),
                "rewrite_ltm_ids": rewrite_E.get("approved_memory_ids_used", []),
            }

            # F. Disable
            if memory_id:
                rF = client.post(f"/api/enterprise-kb/memory/items/{memory_id}/disable")
                result["disable_ok"] = (
                    rF.status_code == 200 and rF.json().get("status") == "disabled"
                )

            # G. Third query — disabled memory excluded
            rG = client.post(
                ENDPOINT,
                json={
                    "query": "项目 embedding 策略",
                    "corpus": "auto",
                    "session_id": SID,
                },
            )
            ltmG = rG.json().get("long_term_memory_trace", {})
            result["graph_excludes_disabled_memory"] = rG.status_code == 200 and (
                ltmG.get("approved_memory_count", 0) == 0
                or memory_id not in ltmG.get("approved_memory_ids", [])
            )
            # Verify disabled memory NOT in LTM context/rewrite
            ltmG = rG.json().get("long_term_memory_trace", {})
            rewrite_G = rG.json().get("rewrite_trace", {})
            result["disabled_memory_not_in_memory_context"] = memory_id not in ltmG.get(
                "approved_memory_ids", []
            )
            result["disabled_memory_not_used_for_rewrite"] = memory_id not in rewrite_G.get(
                "approved_memory_ids_used", []
            )
            result["graph_trace_G"] = {
                "approved_count": ltmG.get("approved_memory_count"),
                "approved_ids": ltmG.get("approved_memory_ids"),
            }

            # H. Events
            rH = client.get("/api/enterprise-kb/memory/events")
            events = rH.json().get("events", [])
            event_types = [e["event_type"] for e in events]
            result["events_ok"] = rH.status_code == 200 and all(
                t in event_types
                for t in ["candidate_created", "candidate_approved", "memory_disabled"]
            )
            result["event_count"] = len(events)

            result["skipped"] = False

        finally:
            for mod in saved:
                sys.modules.pop(mod, None)
            try:
                for f in Path("workspace").glob("p8_e2e_*"):
                    f.unlink()
            except Exception:
                pass

    except ImportError as e:
        result["skipped_reason"] = f"ImportError: {e}"
    except Exception as e:
        result["skipped_reason"] = str(e)[:200]

    result["pass"] = (
        result["endpoint_registered"]
        and result["testclient_available"]
        and result["graph_create_candidate_ok"]
        and result["has_pending"]
        and result["approve_ok"]
        and result["active_item_ok"]
        and result["graph_reads_approved_memory"]
        and result["disable_ok"]
        and result["graph_excludes_disabled_memory"]
        and result["events_ok"]
        and result.get("pending_candidate_not_in_memory_context", False)
        and result.get("pending_not_used_for_rewrite", False)
        and result.get("approved_memory_context_attached", False)
        and result.get("graph_uses_approved_memory_for_answer", False)
        and result.get("mock_does_not_claim_rewrite", False)
        and result.get("disabled_memory_not_in_memory_context", False)
        and result.get("disabled_memory_not_used_for_rewrite", False)
    )
    return result


def main():
    print("=== Phase 8 v1.1 Smoke: Memory Admin API ===")
    results = {"smoke": "phase8_memory_api_v1.1", "timestamp": datetime.now(UTC).isoformat()}
    api = test_full_lifecycle()
    print(
        f"  create_candidate={api['graph_create_candidate_ok']} pending={api['has_pending']} "
        f"approve={api['approve_ok']} reads_approved={api['graph_reads_approved_memory']} "
        f"disable={api['disable_ok']} excludes={api['graph_excludes_disabled_memory']} events={api['events_ok']}"
    )
    if api["skipped"]:
        print(f"  SKIPPED: {api['skipped_reason'][:120]}")
    results["admin_api"] = api
    results["overall_pass"] = api["pass"]
    path = REPORTS / "phase8_memory_api_smoke.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\nSaved: {path}")
    print(f"Overall: {'PASS' if api['pass'] else 'FAIL'}")
    if not api["pass"]:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
