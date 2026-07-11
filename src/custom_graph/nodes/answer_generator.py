"""Phase 5/9 answer generator: mock-extractive or grounded LLM."""

from __future__ import annotations

import time
from typing import Any

from custom_graph.state import GraphState
from llm.client import LLMClient
from llm.errors import LLMError
from llm.json_output_parser import parse_grounded_answer
from llm.prompt_registry import build_answer_prompt


def generate_answer(state: GraphState, llm: LLMClient | None = None) -> dict[str, Any]:
    """Generate an answer from ranked retrieval results."""
    llm = llm or LLMClient()
    t0 = time.perf_counter()
    chunks = state.ranked_results or state.retrieval_results
    answer_query = state.rewritten_query or state.query

    if not chunks:
        latency = round((time.perf_counter() - t0) * 1000, 2)
        return {
            "answer_markdown": "Evidence is insufficient, so no grounded answer can be generated.",
            "citations": [],
            "used_sources": [],
            "llm_trace": _build_llm_trace(llm, None, latency, "no retrieval results", True, 0),
        }

    response = None
    if llm.is_mock:
        answer = _mock_extractive_answer(answer_query, chunks)
    else:
        try:
            messages = build_answer_prompt(
                answer_query,
                chunks[:5],
                memory_context=state.long_term_memory_context,
            )
            response = llm.generate(messages)
            if response.provider == "mock":
                answer = _mock_extractive_answer(answer_query, chunks)
            else:
                parsed = parse_grounded_answer(response)
                answer = {
                    "answer_markdown": parsed.get("answer_markdown", "Evidence is insufficient."),
                    "citations": parsed.get("citations", []),
                    "used_sources": parsed.get("used_sources", []),
                    "unsupported_claims": parsed.get("unsupported_claims", []),
                    "hallucination_risk": parsed.get("hallucination_risk", "medium"),
                }
        except LLMError:
            raise
        except Exception:
            answer = _mock_extractive_answer(answer_query, chunks)

    latency = round((time.perf_counter() - t0) * 1000, 2)
    fallback_used = bool(
        llm.is_mock
        or response is None
        and llm.requested_provider_name != "mock"
        or response is not None
        and response.provider == "mock"
        and llm.requested_provider_name != "mock"
    )
    fallback_reason = ""
    if fallback_used:
        fallback_reason = llm.last_fallback_reason or (
            "provider_error_or_missing_key"
            if llm.requested_provider_name != "mock"
            else "mock_provider_selected"
        )

    return {
        "answer_markdown": answer["answer_markdown"],
        "citations": answer.get("citations", []),
        "used_sources": answer.get("used_sources", []),
        "unsupported_claims": answer.get("unsupported_claims", []),
        "hallucination_risk": answer.get("hallucination_risk", "none"),
        "llm_trace": _build_llm_trace(
            llm,
            response,
            latency,
            fallback_reason,
            fallback_used,
            len(answer.get("citations", [])),
        ),
    }


def _build_llm_trace(
    llm: LLMClient,
    response: Any,
    latency_ms: float,
    fallback_reason: str,
    fallback_used: bool,
    citations_count: int,
) -> dict[str, Any]:
    actual_provider = getattr(response, "provider", "mock" if fallback_used else llm.provider_name)
    actual_model = getattr(response, "model", "mock" if fallback_used else llm.model_name)
    return {
        "provider": llm.requested_provider_name,
        "model": llm.requested_model_name,
        "actual_provider": actual_provider,
        "actual_model": actual_model,
        "mode": "mock_extractive" if fallback_used else "grounded_llm",
        "fallback_used": fallback_used,
        "fallback_reason": fallback_reason,
        "citations_count": citations_count,
        "latency_ms": latency_ms,
    }


def _mock_extractive_answer_legacy(query: str, chunks: list[dict]) -> dict[str, Any]:
    """Build an extractive answer from the top chunks without an LLM call."""
    top = chunks[:3]
    parts = ["Based on retrieved evidence (mock_extractive mode):\n"]
    citations = []
    sources = []

    for i, chunk in enumerate(top):
        source_id = chunk.get("source_id", "unknown")
        chunk_id = chunk.get("chunk_id", "unknown")
        heading = chunk.get("heading_path", "")
        preview = chunk.get("text_preview", "")
        score = float(chunk.get("score", 0) or 0)
        corpus = chunk.get("corpus", "official_docs")

        label = f"[source {i + 1}: {source_id}"
        if heading:
            label += f" | {heading}"
        label += "]"
        parts.append(f"{label}\n{preview}\n")
        citations.append(
            {
                "citation_id": f"cite_{i + 1}",
                "corpus": corpus,
                "source_id": source_id,
                "chunk_id": chunk_id,
                "title": heading.split(" > ")[0] if heading else source_id,
                "heading_path": heading,
                "origin_url": chunk.get("origin_url", source_id),
                "quoted_evidence": preview[:300],
                "support_type": "direct"
                if score >= 0.7
                else ("partial" if score >= 0.5 else "weak"),
            }
        )
        if source_id not in sources:
            sources.append(source_id)

    parts.append(
        "\n---\nThis content comes from retrieved evidence and was not generated by a real LLM."
    )
    return {
        "answer_markdown": "\n".join(parts),
        "citations": citations,
        "used_sources": sources,
        "unsupported_claims": [],
        "hallucination_risk": "none",
    }


def _mock_extractive_answer(query: str, chunks: list[dict]) -> dict[str, Any]:
    """Build an extractive answer after deterministic semantic filtering."""
    from custom_graph.grounding import build_mock_extractive_answer

    return build_mock_extractive_answer(query, chunks)
