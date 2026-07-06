#!/usr/bin/env python3
"""Phase 5 v1.2 Smoke 3: Grounded Answer â€?mock_extractive with fixture chunks + no-key fallback."""

import json, os, sys, time
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))
REPORTS = Path(__file__).resolve().parent.parent.parent / "reports" / "enterprise_kb_v1"
REPORTS.mkdir(parents=True, exist_ok=True)


MOCK_CHUNKS = [
    {"chunk_id": "mock_001", "source_id": "fastapi_official_request_body", "heading_path": "Request Body", "text_preview": "Import BaseModel from pydantic and create data model class.", "score": 0.95, "corpus": "official_docs", "origin_url": "fastapi.tiangolo.com"},
    {"chunk_id": "mock_002", "source_id": "phase4d_bge_m3_decision", "heading_path": "Phase 4D > Decision", "text_preview": "bge-m3 selected based on HPC A/B: k5=0.9091, GPU=2.99GB.", "score": 0.82, "corpus": "internal_engineering_docs", "origin_url": "phase4d_bge_m3_decision"},
]


def test_mock_extractive_with_fixtures():
    """Test extractive answer with mock chunks."""
    from custom_graph.nodes.answer_generator import _mock_extractive_answer
    from custom_graph.nodes.evidence_verifier import verify_evidence
    from custom_graph.state import GraphState

    answer = _mock_extractive_answer("How to define request body?", MOCK_CHUNKS)
    state = GraphState(query="How to define request body?", citations=answer["citations"], ranked_results=MOCK_CHUNKS)
    verify = verify_evidence(state)

    return {
        "answer_preview": answer["answer_markdown"][:200],
        "citations_count": len(answer["citations"]),
        "all_citations_from_retrieved": verify["all_citations_from_retrieved"],
        "citation_validity": verify["citation_validity"],
        "citation_status": verify.get("citation_trace", {}).get("citation_status", "?"),
        "hallucination_risk": verify["hallucination_risk"],
        "used_sources": answer.get("used_sources", []),
        "pass": len(answer["citations"]) > 0 and verify["citation_validity"],
    }


def test_no_key_fallback():
    saved = {}
    for key in ["QWEN_API_KEY", "DEEPSEEK_API_KEY"]:
        saved[key] = os.environ.pop(key, None)
    try:
        from llm.client import LLMClient
        llm = LLMClient()
        return {"no_key_fallback_to_mock": llm.is_mock, "provider": llm.provider_name}
    except Exception as e:
        return {"no_key_fallback_to_mock": False, "error": str(e)[:200]}
    finally:
        for key, val in saved.items():
            if val is not None:
                os.environ[key] = val


def main():
    print("=== Phase 5 v1.2 Smoke: Grounded Answer ===")
    results = {"smoke": "phase5_grounded_answer", "timestamp": datetime.now(timezone.utc).isoformat()}

    fb = test_no_key_fallback()
    print(f"  No-key fallback: {fb['no_key_fallback_to_mock']}")
    results["no_key_fallback"] = fb

    ext = test_mock_extractive_with_fixtures()
    print(f"  Extractive: citations={ext['citations_count']} from_retrieved={ext['all_citations_from_retrieved']} validity={ext['citation_validity']}")
    results["mock_extractive_fixture_test"] = ext

    results["overall_pass"] = fb["no_key_fallback_to_mock"] and ext["pass"]
    path = REPORTS / "phase5_grounded_answer_smoke.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\nSaved: {path}")
    print(f"Overall: {'PASS' if results['overall_pass'] else 'FAIL'}")


if __name__ == "__main__":
    main()
