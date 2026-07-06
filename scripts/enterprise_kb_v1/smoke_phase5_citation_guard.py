#!/usr/bin/env python3
"""Phase 5 v1.2 Smoke: Citation Guard -- positive + negative fixture-based tests.

Does NOT require Chroma or langchain. Injects mock retrieved chunks directly.
"""

import json, sys
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))
REPORTS = Path(__file__).resolve().parent.parent.parent / "reports" / "enterprise_kb_v1"
REPORTS.mkdir(parents=True, exist_ok=True)

from custom_graph.state import GraphState

# -- Mock retrieved chunks (simulating real retrieval) --

MOCK_CHUNKS = [
    {
        "chunk_id": "mock_chunk_001",
        "source_id": "fastapi_official_request_body",
        "heading_path": "Request Body > Import Pydantic BaseModel",
        "text_preview": "First, you need to import BaseModel from pydantic. Then create your data model as a class that inherits from BaseModel. Use standard Python types for attributes.",
        "score": 0.95,
        "corpus": "official_docs",
        "origin_url": "https://fastapi.tiangolo.com/tutorial/body/",
    },
    {
        "chunk_id": "mock_chunk_002",
        "source_id": "fastapi_official_request_body",
        "heading_path": "Request Body > Create your data model",
        "text_preview": "Declare the request body using standard Python types. FastAPI will read the body of the request as JSON and validate the data. If invalid, it returns a clear error.",
        "score": 0.88,
        "corpus": "official_docs",
        "origin_url": "https://fastapi.tiangolo.com/tutorial/body/",
    },
    {
        "chunk_id": "mock_chunk_003",
        "source_id": "phase4d_bge_m3_decision",
        "heading_path": "Phase 4D > Decision",
        "text_preview": "bge-m3 selected as default embedding based on HPC A/B results: k=5 hit_rate 0.9091, GPU 2.99GB. qwen3-embedding-0.6b retained as high_precision_candidate.",
        "score": 0.82,
        "corpus": "internal_engineering_docs",
        "origin_url": "phase4d_bge_m3_decision",
    },
]

MOCK_RETRIEVED_IDS = {"mock_chunk_001", "mock_chunk_002", "mock_chunk_003"}


def test_positive():
    """Positive test: all citations from retrieved chunks -- should pass."""
    from custom_graph.nodes.answer_generator import _mock_extractive_answer
    from custom_graph.nodes.evidence_verifier import verify_evidence

    answer = _mock_extractive_answer("How to define request body in FastAPI?", MOCK_CHUNKS)
    state = GraphState(
        query="How to define request body in FastAPI?",
        citations=answer["citations"],
        ranked_results=MOCK_CHUNKS,
    )

    result = verify_evidence(state)
    return {
        "test": "positive_all_valid",
        "citations_count": len(answer["citations"]),
        "all_citations_from_retrieved": result["all_citations_from_retrieved"],
        "citation_validity": result["citation_validity"],
        "citation_status": result.get("citation_trace", {}).get("citation_status", "?"),
        "hallucination_risk": result["hallucination_risk"],
        "test_pass": result["citation_validity"] and result["all_citations_from_retrieved"],
        "expected_citation_validity": True,
        "actual_citation_validity": result["citation_validity"],
    }


def test_negative_invalid_citation():
    """Negative test: inject a citation with chunk_id NOT in retrieved -- must FAIL."""
    from custom_graph.nodes.evidence_verifier import verify_evidence

    state = GraphState(
        query="test",
        citations=[{
            "citation_id": "cite_fake",
            "chunk_id": "NOT_IN_RETRIEVED_SET",
            "source_id": "fake_source",
            "heading_path": "Fake",
            "quoted_evidence": "fake evidence",
            "support_type": "direct",
        }],
        ranked_results=MOCK_CHUNKS,
    )

    result = verify_evidence(state)
    return {
        "test": "negative_invalid_chunk_id",
        "citations_count": 1,
        "all_citations_from_retrieved": result["all_citations_from_retrieved"],
        "citation_validity": result["citation_validity"],
        "citation_status": result.get("citation_trace", {}).get("citation_status", "?"),
        "hallucination_risk": result["hallucination_risk"],
        "violations": result.get("citation_trace", {}).get("violations", []),
        "test_pass": not result["citation_validity"] and result["hallucination_risk"] == "high",
        "expected_citation_validity": False,
        "actual_citation_validity": result["citation_validity"],
    }


def test_empty_citations():
    """Empty citations test -- must return citation_validity=false, risk=high."""
    from custom_graph.nodes.evidence_verifier import verify_evidence

    state = GraphState(query="test", citations=[], ranked_results=MOCK_CHUNKS)
    result = verify_evidence(state)

    return {
        "test": "empty_citations",
        "citations_count": 0,
        "all_citations_from_retrieved": result["all_citations_from_retrieved"],
        "citation_validity": result["citation_validity"],
        "citation_status": result.get("citation_trace", {}).get("citation_status", "?"),
        "hallucination_risk": result["hallucination_risk"],
        "test_pass": (not result["citation_validity"]) and (result["hallucination_risk"] == "high"),
        "expected_citation_validity": False,
        "actual_citation_validity": result["citation_validity"],
    }


def main():
    print("=== Phase 5 v1.2 Smoke: Citation Guard ===")
    results = {"smoke": "phase5_citation_guard", "timestamp": datetime.now(timezone.utc).isoformat(), "tests": []}

    for test_func in [test_positive, test_negative_invalid_citation, test_empty_citations]:
        r = test_func()
        status = "PASS" if r["test_pass"] else "FAIL"
        print(f"  {r['test']}: citations={r['citations_count']} validity={r['citation_validity']} risk={r['hallucination_risk']} -> {status}")
        results["tests"].append(r)

    results["all_pass"] = all(t["test_pass"] for t in results["tests"])
    path = REPORTS / "phase5_citation_guard_smoke.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\nSaved: {path}")
    print(f"All pass: {results['all_pass']}")

    if not results["all_pass"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
