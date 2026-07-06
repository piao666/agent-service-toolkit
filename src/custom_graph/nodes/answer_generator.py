"""Phase 5: Answer generator — mock_extractive or grounded_llm."""

import time
from typing import Any

from custom_graph.state import GraphState
from llm.client import LLMClient
from llm.prompt_registry import build_answer_prompt
from llm.json_output_parser import parse_grounded_answer


def generate_answer(state: GraphState, llm: LLMClient | None = None) -> dict[str, Any]:
    """Generate answer from ranked retrieval results."""
    llm = llm or LLMClient()
    t0 = time.perf_counter()
    chunks = state.ranked_results or state.retrieval_results

    if not chunks:
        latency = round((time.perf_counter() - t0) * 1000, 2)
        return {
            "answer_markdown": "证据不足，无法生成回答。",
            "citations": [],
            "used_sources": [],
            "llm_trace": {"mode": "mock_extractive", "reason": "no retrieval results", "latency_ms": latency},
        }

    if llm.is_mock:
        answer = _mock_extractive_answer(state.query, chunks)
    else:
        try:
            messages = build_answer_prompt(state.query, chunks[:5])
            response = llm.generate(messages)
            parsed = parse_grounded_answer(response)
            answer = {
                "answer_markdown": parsed.get("answer_markdown", "证据不足。"),
                "citations": parsed.get("citations", []),
                "used_sources": parsed.get("used_sources", []),
                "unsupported_claims": parsed.get("unsupported_claims", []),
                "hallucination_risk": parsed.get("hallucination_risk", "medium"),
            }
        except Exception:
            answer = _mock_extractive_answer(state.query, chunks)

    latency = round((time.perf_counter() - t0) * 1000, 2)
    llm_mode = "mock_extractive" if llm.is_mock else "grounded_llm"
    return {
        "answer_markdown": answer["answer_markdown"],
        "citations": answer.get("citations", []),
        "used_sources": answer.get("used_sources", []),
        "unsupported_claims": answer.get("unsupported_claims", []),
        "hallucination_risk": answer.get("hallucination_risk", "none"),
        "llm_trace": {"provider": llm.provider_name, "mode": llm_mode, "citations_count": len(answer.get("citations", [])), "latency_ms": latency},
    }


def _mock_extractive_answer(query: str, chunks: list[dict]) -> dict[str, Any]:
    """Build extractive answer from top-3 chunks without LLM."""
    top = chunks[:3]
    parts = [f"基于检索结果（mock_extractive 模式）：\n"]
    citations = []
    sources = []

    for i, c in enumerate(top):
        sid = c.get("source_id", "unknown")
        cid = c.get("chunk_id", "unknown")
        heading = c.get("heading_path", "")
        preview = c.get("text_preview", "")
        score = c.get("score", 0)
        corpus = c.get("corpus", "official_docs")

        label = f"[来源{i + 1}: {sid}"
        if heading:
            label += f" | {heading}"
        label += "]"

        parts.append(f"{label}\n{preview}\n")
        citations.append({
            "citation_id": f"cite_{i + 1}",
            "corpus": corpus,
            "source_id": sid,
            "chunk_id": cid,
            "title": heading.split(" > ")[0] if heading else sid,
            "heading_path": heading,
            "origin_url": c.get("origin_url", sid),
            "quoted_evidence": preview[:300],
            "support_type": "direct" if score >= 0.7 else ("partial" if score >= 0.5 else "weak"),
        })
        if sid not in sources:
            sources.append(sid)

    parts.append("\n---\n以上内容来自检索结果，未经 LLM 生成。")
    return {
        "answer_markdown": "\n".join(parts),
        "citations": citations,
        "used_sources": sources,
        "unsupported_claims": [],
        "hallucination_risk": "none",
    }
