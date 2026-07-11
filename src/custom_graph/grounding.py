"""Deterministic citation grounding shared by answer and verifier nodes."""

from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any

from custom_graph.state import GraphState

_EN_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "can",
    "does",
    "for",
    "from",
    "how",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "the",
    "this",
    "to",
    "what",
    "when",
    "where",
    "which",
    "why",
    "with",
}


def normalize_text(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]+", text.lower()))


def text_tokens(text: str) -> set[str]:
    tokens = {
        token
        for token in re.findall(r"[a-z0-9]+", text.lower())
        if len(token) > 1 and token not in _EN_STOPWORDS
    }
    for run in re.findall(r"[\u4e00-\u9fff]+", text):
        if len(run) <= 3:
            tokens.add(run)
        tokens.update(run[index : index + 2] for index in range(len(run) - 1))
    return tokens


def semantic_overlap_score(query: str, evidence: str) -> tuple[float, list[str]]:
    query_tokens = text_tokens(query)
    evidence_tokens = text_tokens(evidence)
    if not query_tokens or not evidence_tokens:
        return 0.0, []
    shared = sorted(query_tokens & evidence_tokens)
    score = len(shared) / max(1, len(query_tokens))
    return round(min(score, 1.0), 4), shared


def chunk_semantic_score(query: str, chunk: dict[str, Any]) -> tuple[float, list[str]]:
    evidence = " ".join(
        str(chunk.get(field, "")) for field in ("source_id", "heading_path", "text_preview")
    )
    return semantic_overlap_score(query, evidence)


def quote_integrity_score(quote: str, source_text: str) -> float:
    quote_norm = normalize_text(quote)
    source_norm = normalize_text(source_text)
    if not quote_norm or not source_norm:
        return 0.0
    if quote_norm in source_norm:
        return 1.0
    quote_tokens = text_tokens(quote)
    source_tokens = text_tokens(source_text)
    token_coverage = len(quote_tokens & source_tokens) / max(1, len(quote_tokens))
    sequence_ratio = SequenceMatcher(None, quote_norm, source_norm).ratio()
    return round(max(token_coverage, sequence_ratio), 4)


def is_semantically_supported(score: float, shared_tokens: list[str]) -> bool:
    return score >= 0.2 and (len(shared_tokens) >= 2 or score >= 0.5)


def build_mock_extractive_answer(query: str, chunks: list[dict[str, Any]]) -> dict[str, Any]:
    """Build an answer only from chunks with deterministic query overlap."""
    candidates: list[tuple[float, float, dict[str, Any], list[str]]] = []
    for chunk in chunks:
        semantic_score, shared = chunk_semantic_score(query, chunk)
        if not is_semantically_supported(semantic_score, shared):
            continue
        retrieval_score = float(chunk.get("score", 0) or 0)
        candidates.append((semantic_score, retrieval_score, chunk, shared))

    candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
    top = candidates[:3]
    if not top:
        return {
            "answer_markdown": "Evidence is insufficient, so no grounded answer can be generated.",
            "citations": [],
            "used_sources": [],
            "unsupported_claims": ["no retrieved chunk passed semantic support checks"],
            "hallucination_risk": "high",
        }

    parts = ["Based on the retrieved evidence:\n"]
    citations: list[dict[str, Any]] = []
    sources: list[str] = []
    for index, (semantic_score, retrieval_score, chunk, shared) in enumerate(top, start=1):
        source_id = str(chunk.get("source_id", "unknown"))
        chunk_id = str(chunk.get("chunk_id", "unknown"))
        heading = str(chunk.get("heading_path", ""))
        preview = str(chunk.get("text_preview", ""))
        corpus = str(chunk.get("corpus", "official_docs"))
        label = f"[source {index}: {source_id}"
        if heading:
            label += f" | {heading}"
        parts.append(f"{label}]\n{preview}\n")
        citations.append(
            {
                "citation_id": f"cite_{index}",
                "corpus": corpus,
                "source_id": source_id,
                "chunk_id": chunk_id,
                "title": heading.split(" > ")[0] if heading else source_id,
                "heading_path": heading,
                "origin_url": chunk.get("origin_url", source_id),
                "quoted_evidence": preview[:300],
                "support_type": "direct" if semantic_score >= 0.5 else "partial",
                "semantic_score": semantic_score,
                "shared_query_tokens": shared,
                "retrieval_score": retrieval_score,
            }
        )
        if source_id not in sources:
            sources.append(source_id)

    return {
        "answer_markdown": "\n".join(parts),
        "citations": citations,
        "used_sources": sources,
        "unsupported_claims": [],
        "hallucination_risk": "none",
    }


def verify_semantic_evidence(state: GraphState) -> dict[str, Any]:
    """Validate citation identity, quote integrity, and semantic support."""
    chunks = state.ranked_results or state.retrieval_results
    chunk_by_id = {
        str(chunk.get("chunk_id", "")): chunk for chunk in chunks if chunk.get("chunk_id")
    }
    citations = state.citations
    if not citations:
        return {
            "citation_validity": False,
            "all_citations_from_retrieved": False,
            "unsupported_claims": [*state.unsupported_claims, "no citations generated"],
            "hallucination_risk": "high",
            "citation_trace": {
                "citation_status": "no_citations",
                "total_citations": 0,
                "valid_citations": 0,
                "invalid_citations": 0,
                "citation_id_validity": False,
                "citation_quote_validity": False,
                "citation_semantic_support": False,
                "semantic_support_rate": 0.0,
                "violations": [{"reason": "no citations generated"}],
                "per_citation": [],
                "all_citations_from_retrieved": False,
                "citation_validity": False,
            },
        }

    per_citation: list[dict[str, Any]] = []
    violations: list[dict[str, Any]] = []
    id_valid_count = 0
    quote_valid_count = 0
    semantic_valid_count = 0
    fully_valid_count = 0
    query = state.rewritten_query or state.query

    for citation in citations:
        chunk_id = str(citation.get("chunk_id", ""))
        source_id = str(citation.get("source_id", ""))
        chunk = chunk_by_id.get(chunk_id)
        id_valid = bool(chunk) and source_id == str(chunk.get("source_id", ""))
        if id_valid:
            id_valid_count += 1

        quote = str(citation.get("quoted_evidence", ""))
        source_text = str(chunk.get("text_preview", "")) if chunk else ""
        quote_score = quote_integrity_score(quote, source_text)
        quote_valid = id_valid and quote_score >= 0.9
        if quote_valid:
            quote_valid_count += 1

        semantic_score, shared = chunk_semantic_score(query, chunk or {})
        semantic_valid = id_valid and is_semantically_supported(semantic_score, shared)
        if semantic_valid:
            semantic_valid_count += 1

        fully_valid = id_valid and quote_valid and semantic_valid
        if fully_valid:
            fully_valid_count += 1
        else:
            reasons: list[str] = []
            if not id_valid:
                reasons.append("citation_not_in_retrieved_set_or_source_mismatch")
            if id_valid and not quote_valid:
                reasons.append("quoted_evidence_not_verbatim")
            if id_valid and not semantic_valid:
                reasons.append("citation_not_semantically_related_to_query")
            violations.append(
                {
                    "citation_id": citation.get("citation_id", "?"),
                    "chunk_id": chunk_id,
                    "source_id": source_id,
                    "reasons": reasons,
                }
            )

        per_citation.append(
            {
                "citation_id": citation.get("citation_id", "?"),
                "chunk_id": chunk_id,
                "source_id": source_id,
                "id_valid": id_valid,
                "quote_valid": quote_valid,
                "quote_integrity_score": quote_score,
                "semantic_supported": semantic_valid,
                "semantic_score": semantic_score,
                "shared_query_tokens": shared,
                "fully_valid": fully_valid,
            }
        )

    total = len(citations)
    id_validity = id_valid_count == total
    quote_validity = quote_valid_count == total
    semantic_validity = semantic_valid_count == total
    citation_validity = fully_valid_count == total
    support_rate = round(semantic_valid_count / total, 4)

    unsupported = list(state.unsupported_claims)
    if not citation_validity:
        unsupported.append(f"{total - fully_valid_count} citations failed full grounding checks")
    if semantic_valid_count == 0:
        risk = "high"
        status = "semantic_mismatch" if id_valid_count else "invalid_citation"
    elif not citation_validity:
        risk = "medium"
        status = "partial_support"
    else:
        risk = state.hallucination_risk if state.hallucination_risk in {"none", "low"} else "low"
        status = "valid"

    return {
        "citation_validity": citation_validity,
        "all_citations_from_retrieved": id_validity,
        "unsupported_claims": unsupported,
        "hallucination_risk": risk,
        "citation_trace": {
            "citation_status": status,
            "total_citations": total,
            "valid_citations": fully_valid_count,
            "invalid_citations": total - fully_valid_count,
            "citation_id_validity": id_validity,
            "citation_quote_validity": quote_validity,
            "citation_semantic_support": semantic_validity,
            "semantic_support_rate": support_rate,
            "violations": violations,
            "per_citation": per_citation,
            "all_citations_from_retrieved": id_validity,
            "citation_validity": citation_validity,
        },
    }
