"""Phase 5: Query classifier node — determines intent and recommended corpus."""

import time
from typing import Any

from custom_graph.state import GraphState
from llm.client import LLMClient
from llm.errors import LLMError
from llm.json_output_parser import parse_intent
from llm.prompt_registry import build_classifier_prompt


def classify_query(state: GraphState, llm: LLMClient | None = None) -> dict[str, Any]:
    """Classify the user query and set intent + recommended corpus."""
    llm = llm or LLMClient()
    t0 = time.perf_counter()

    if llm.is_mock:
        # Rule-based fallback
        result = _rule_based_classify(state.query)
    else:
        try:
            messages = build_classifier_prompt(state.query)
            response = llm.generate(messages)
            parsed = parse_intent(response)
            result = {
                "intent": parsed.get("intent", "ambiguous"),
                "confidence": parsed.get("confidence", 0.5),
                "reasoning": parsed.get("reasoning", "LLM classified"),
                "recommended_corpus": parsed.get("recommended_corpus", "official_docs"),
            }
        except LLMError:
            raise
        except Exception:
            result = _rule_based_classify(state.query)

    latency = round((time.perf_counter() - t0) * 1000, 2)
    return {
        "intent": result["intent"],
        "intent_confidence": result["confidence"],
        "intent_reasoning": result["reasoning"],
        "recommended_corpus": result["recommended_corpus"],
        "intent_trace": {
            "query": state.query,
            **result,
            "latency_ms": latency,
            "llm_mode": "mock" if llm.is_mock else "grounded_llm",
        },
    }


def _rule_based_classify(query: str) -> dict[str, Any]:
    """Simple rule-based classification when no LLM available."""
    ql = query.lower()
    internal_keywords = [
        "本项目",
        "phase",
        "hpc",
        "bge-m3",
        "评测",
        "语料",
        "registry",
        "代码摘要",
        "配置项",
        "失败案例",
    ]
    official_keywords = [
        "fastapi",
        "chroma",
        "langgraph",
        "openai",
        "pydantic",
        "httpexception",
        "middleware",
    ]

    int_hits = sum(1 for kw in internal_keywords if kw.lower() in ql)
    off_hits = sum(1 for kw in official_keywords if kw.lower() in ql)

    if int_hits > 0 and off_hits > 0:
        return {
            "intent": "mixed",
            "confidence": 0.7,
            "reasoning": "rule: both internal and official keywords detected",
            "recommended_corpus": "dual",
        }
    if int_hits > 0:
        return {
            "intent": "project_inquiry",
            "confidence": 0.7,
            "reasoning": "rule: internal project keywords detected",
            "recommended_corpus": "internal_engineering_docs",
        }
    if off_hits > 0:
        return {
            "intent": "technical_reference",
            "confidence": 0.7,
            "reasoning": "rule: official docs keywords detected",
            "recommended_corpus": "official_docs",
        }
    return {
        "intent": "ambiguous",
        "confidence": 0.3,
        "reasoning": "rule: no strong signal",
        "recommended_corpus": "official_docs",
    }
