"""Phase 5 v1.1: Evidence verifier — checks citations against retrieved chunks.

Rules:
- citations=[] → citation_validity=false, hallucination_risk=high, status="no_citations"
- citations non-empty AND all chunk_ids IN retrieved → citation_validity=true
- ANY citation chunk_id NOT in retrieved → citation_validity=false, status="invalid_citation"
"""

import time
from typing import Any

from custom_graph.state import GraphState


def _verify_evidence_legacy(state: GraphState) -> dict[str, Any]:
    t0 = time.perf_counter()
    citations = state.citations
    retrieved_ids = {
        r.get("chunk_id", "") for r in (state.ranked_results or state.retrieval_results)
    }

    # ── Case 1: No citations at all ──────────────────────────────────
    if not citations:
        latency = round((time.perf_counter() - t0) * 1000, 2)
        return {
            "citation_validity": False,
            "all_citations_from_retrieved": False,
            "unsupported_claims": ["no citations generated"],
            "hallucination_risk": "high",
            "citation_trace": {
                "citation_status": "no_citations",
                "total_citations": 0,
                "valid_citations": 0,
                "invalid_citations": 0,
                "violations": [
                    {
                        "reason": "no citations generated — evidence_verifier cannot validate empty citations"
                    }
                ],
                "all_citations_from_retrieved": False,
                "citation_validity": False,
                "latency_ms": latency,
            },
        }

    # ── Case 2: Has citations — validate each ────────────────────────
    valid_count = 0
    invalid_count = 0
    violations = []
    for c in citations:
        cid = c.get("chunk_id", "")
        if cid and cid in retrieved_ids:
            valid_count += 1
        else:
            invalid_count += 1
            violations.append(
                {
                    "citation_id": c.get("citation_id", "?"),
                    "chunk_id": cid,
                    "source_id": c.get("source_id", "?"),
                    "in_retrieved": cid in retrieved_ids,
                }
            )

    all_valid = invalid_count == 0 and valid_count > 0

    unsupported = list(state.unsupported_claims)
    h_risk = state.hallucination_risk
    if invalid_count > 0:
        unsupported.append(f"{invalid_count} citations reference chunks not in retrieved set")
        h_risk = "high"
    elif valid_count == 0:
        h_risk = "high"

    latency = round((time.perf_counter() - t0) * 1000, 2)
    return {
        "citation_validity": all_valid,
        "all_citations_from_retrieved": all_valid,
        "unsupported_claims": unsupported,
        "hallucination_risk": h_risk,
        "citation_trace": {
            "citation_status": "valid" if all_valid else "invalid_citation",
            "total_citations": len(citations),
            "valid_citations": valid_count,
            "invalid_citations": invalid_count,
            "violations": violations,
            "all_citations_from_retrieved": all_valid,
            "citation_validity": all_valid,
            "latency_ms": latency,
        },
    }


def verify_evidence(state: GraphState) -> dict[str, Any]:
    """Run the Phase 10 identity, quote, and semantic citation checks."""
    from custom_graph.grounding import verify_semantic_evidence

    return verify_semantic_evidence(state)
