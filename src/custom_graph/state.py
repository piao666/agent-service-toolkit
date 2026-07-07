"""Phase 5: Custom Graph state — typed state for the enterprise KB pipeline."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class GraphState:
    """Full state carried through the custom_graph pipeline.

    Nodes: query_classifier → memory_rewriter → planner → retriever →
           ranker → answer_generator → evidence_verifier → final_response
    """
    # Input
    query: str = ""
    session_id: str = ""
    corpus: str = "auto"  # official_docs | internal_engineering_docs | auto

    # Node outputs
    intent: str = ""
    intent_confidence: float = 0.0
    intent_reasoning: str = ""
    recommended_corpus: str = "official_docs"

    rewritten_query: str = ""

    plan_steps: list[str] = field(default_factory=list)
    plan_retrieval_queries: list[str] = field(default_factory=list)

    retrieval_results: list[dict[str, Any]] = field(default_factory=list)
    ranked_results: list[dict[str, Any]] = field(default_factory=list)

    answer_markdown: str = ""
    citations: list[dict[str, Any]] = field(default_factory=list)
    used_sources: list[str] = field(default_factory=list)

    unsupported_claims: list[str] = field(default_factory=list)
    hallucination_risk: str = "none"
    citation_validity: bool = False
    all_citations_from_retrieved: bool = False

    # Trace (per-node)
    intent_trace: dict[str, Any] = field(default_factory=dict)
    rewrite_trace: dict[str, Any] = field(default_factory=dict)
    plan_trace: dict[str, Any] = field(default_factory=dict)
    retrieval_trace: dict[str, Any] = field(default_factory=dict)
    rank_trace: dict[str, Any] = field(default_factory=dict)
    llm_trace: dict[str, Any] = field(default_factory=dict)
    citation_trace: dict[str, Any] = field(default_factory=dict)
    graph_debug: dict[str, Any] = field(default_factory=dict)

    # Phase 7: Memory
    memory_context: str = ""
    memory_trace: dict[str, Any] = field(default_factory=dict)
    memory_candidates: list[dict[str, Any]] = field(default_factory=list)

    # Error tracking
    errors: list[str] = field(default_factory=list)
    final_response: dict[str, Any] = field(default_factory=dict)
