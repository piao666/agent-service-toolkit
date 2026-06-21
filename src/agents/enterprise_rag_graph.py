from __future__ import annotations

import asyncio
import inspect
import re
from collections.abc import Awaitable, Callable
from typing import Any, TypedDict

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph

from agents.enterprise_rag_agent import ANSWER_SYNTHESIS_PROMPT
from core import get_model, settings
from rag.config import rag_settings
from rag.conversation_memory import contextualize_query_with_memory, get_memory_store
from rag.evidence_verifier import build_safe_fallback_answer, verify_answer_grounding
from schema.models import FakeModelName

Retriever = Callable[
    [str, int | None],
    dict[str, Any] | Awaitable[dict[str, Any]],
]
AnswerGenerator = Callable[
    [str, list[dict[str, Any]]],
    str | Awaitable[str],
]

_AMBIGUOUS_QUERIES = {
    "继续",
    "接着说",
    "上面那个",
    "它是什么",
    "它有什么局限",
    "continue",
    "that one",
}
_UNSUPPORTED_TERMS = (
    "天气",
    "股票价格",
    "股价",
    "写情书",
    "彩票开奖",
    "weather",
    "stock price",
    "love letter",
)
_CITATION_TERMS = ("引用", "出处", "来源", "证据", "citation", "source", "reference")
_METADATA_TERMS = (
    "source_id",
    "chunk_id",
    "doc_type",
    "section_path",
    "source_url",
    "normalized_id",
    "metadata",
    "来源编号",
    "文档类型",
)
_CODE_TERMS = ("config", "schema", "endpoint", "环境变量", "配置项", "错误码", "参数", "字段")


class EnterpriseRAGGraphState(TypedDict, total=False):
    query: str
    session_id: str | None
    top_k: int
    return_sources: bool
    model: Any | None
    query_type: str | None
    contextual_query: str | None
    memory_debug: dict[str, Any]
    retrieved_sources: list[dict[str, Any]]
    retrieval_debug: dict[str, Any]
    ranked_sources: list[dict[str, Any]]
    answer: str
    model_debug: dict[str, Any]
    fallback: dict[str, Any]
    citations: list[dict[str, Any]]
    verifier_debug: dict[str, Any]
    graph_debug: dict[str, Any]
    final_response: dict[str, Any]


def _normalized_query(state: EnterpriseRAGGraphState) -> str:
    return " ".join(str(state.get("query") or "").split())


def _append_node(
    state: EnterpriseRAGGraphState,
    node_name: str,
    *,
    route: str | None = None,
) -> dict[str, Any]:
    debug = dict(state.get("graph_debug") or {})
    nodes = list(debug.get("nodes_executed") or [])
    nodes.append(node_name)
    current_route = debug.get("route")
    debug.update(
        {
            "graph_mode": "custom_graph",
            "nodes_executed": nodes,
            "route": route if route is not None else current_route,
            "calls_llm": bool(debug.get("calls_llm", False)),
            "calls_real_llm": bool(debug.get("calls_real_llm", False)),
            "writes_chroma": False,
        }
    )
    return debug


def _is_code_or_api_query(query: str) -> bool:
    lowered = query.casefold()
    return bool(
        any(term in lowered for term in _CODE_TERMS)
        or re.search(r"/[A-Za-z0-9_.{}-]+(?:/[A-Za-z0-9_.{}-]+)+", query)
        or re.search(r"\b(?:GET|POST|PUT|PATCH|DELETE|[1-5][0-9]{2})\b", query)
        or re.search(r"\b[A-Za-z][A-Za-z0-9]*_[A-Za-z0-9_]+\b", query)
        or re.search(r"\b[A-Za-z][A-Za-z0-9]*\(\)", query)
        or re.search(r"\.(?:py|json|ya?ml)\b", query, flags=re.IGNORECASE)
    )


def infer_graph_query_type(query: str, session_id: str | None = None) -> str:
    normalized = " ".join(str(query or "").split())
    lowered = normalized.casefold().rstrip("?？!！。")
    if any(term in lowered for term in _UNSUPPORTED_TERMS):
        return "unsupported_query"
    if session_id and lowered in _AMBIGUOUS_QUERIES:
        return "memory_follow_up"
    if lowered in _AMBIGUOUS_QUERIES or not normalized:
        return "ambiguous_query"
    if any(term in lowered for term in _CITATION_TERMS):
        return "citation_required_query"
    if any(term in lowered for term in _METADATA_TERMS):
        return "exact_metadata_lookup"
    if _is_code_or_api_query(normalized):
        return "code_api_config"
    return "semantic_qa"


async def query_classifier_node(state: EnterpriseRAGGraphState) -> EnterpriseRAGGraphState:
    query_type = infer_graph_query_type(_normalized_query(state), state.get("session_id"))
    route = {
        "ambiguous_query": "clarification",
        "unsupported_query": "safe_response",
    }.get(query_type, "normal")
    return {
        "query_type": query_type,
        "graph_debug": _append_node(state, "query_classifier", route=route),
    }


async def memory_rewriter_node(state: EnterpriseRAGGraphState) -> EnterpriseRAGGraphState:
    store = get_memory_store(
        max_turns=rag_settings.ENTERPRISE_MEMORY_MAX_TURNS,
        max_answer_chars=rag_settings.ENTERPRISE_MEMORY_MAX_ANSWER_CHARS,
    )
    contextual_query, memory_debug = contextualize_query_with_memory(
        query=_normalized_query(state),
        session_id=state.get("session_id"),
        memory_mode=rag_settings.memory_mode,
        store=store,
    )
    return {
        "contextual_query": contextual_query,
        "memory_debug": memory_debug,
        "graph_debug": _append_node(state, "memory_rewriter"),
    }


def _default_retriever(query: str, top_k: int | None) -> dict[str, Any]:
    from agents.enterprise_tools import enterprise_knowledge_retriever_func

    return enterprise_knowledge_retriever_func(query=query, top_k=top_k)


def _source_score(source: dict[str, Any]) -> float:
    for field in ("relevance_score", "score"):
        value = source.get(field)
        if isinstance(value, int | float):
            return float(value)
    distance = source.get("distance")
    if isinstance(distance, int | float):
        return 1.0 - float(distance)
    return 0.0


def _source_value(source: dict[str, Any], field: str) -> str:
    metadata = source.get("metadata") if isinstance(source.get("metadata"), dict) else {}
    value = source.get(field)
    if value in (None, "", "unknown"):
        value = metadata.get(field)
    return str(value or "").strip()


def _default_answer_generator(query: str, sources: list[dict[str, Any]]) -> str:
    if not sources:
        return build_safe_fallback_answer(query)
    source = sources[0]
    preview = _source_value(source, "content_preview") or _source_value(source, "preview")
    title = _source_value(source, "title") or "knowledge-base evidence"
    if any("\u4e00" <= character <= "\u9fff" for character in query):
        return f"根据知识库来源《{title}》，{preview or '已找到与该问题相关的证据。'}"
    return f"According to the knowledge-base source '{title}', {preview or 'relevant evidence was found.'}"


def _build_retriever_node(
    retriever: Retriever,
) -> Callable[[EnterpriseRAGGraphState], Awaitable[EnterpriseRAGGraphState]]:
    async def retriever_node(state: EnterpriseRAGGraphState) -> EnterpriseRAGGraphState:
        query = state.get("contextual_query") or _normalized_query(state)
        if inspect.iscoroutinefunction(retriever):
            payload = await retriever(query, state.get("top_k", 5))
        else:
            payload_result = await asyncio.to_thread(retriever, query, state.get("top_k", 5))
            payload = await payload_result if inspect.isawaitable(payload_result) else payload_result
        sources = list(payload.get("sources") or [])
        debug = dict(payload.get("retrieval_debug") or {})
        debug.update(
            {
                "original_query": _normalized_query(state),
                "rewritten_query": query,
                "hit_count": len(sources),
                "graph_retrieval_adapter": "enterprise_retriever",
            }
        )
        return {
            "retrieved_sources": sources,
            "retrieval_debug": debug,
            "fallback": dict(payload.get("fallback") or {}),
            "graph_debug": _append_node(state, "retriever"),
        }

    return retriever_node


async def retriever_node(state: EnterpriseRAGGraphState) -> EnterpriseRAGGraphState:
    """Run the existing enterprise retriever in the default custom graph."""
    return await _build_retriever_node(_default_retriever)(state)


async def ranker_node(state: EnterpriseRAGGraphState) -> EnterpriseRAGGraphState:
    ranked = sorted(state.get("retrieved_sources") or [], key=_source_score, reverse=True)
    return {
        "ranked_sources": ranked,
        "graph_debug": _append_node(state, "ranker"),
    }


def _build_answer_generator_node(
    answer_generator: AnswerGenerator,
) -> Callable[[EnterpriseRAGGraphState], Awaitable[EnterpriseRAGGraphState]]:
    async def answer_generator_node(state: EnterpriseRAGGraphState) -> EnterpriseRAGGraphState:
        query = state.get("contextual_query") or _normalized_query(state)
        answer_result = answer_generator(query, list(state.get("ranked_sources") or []))
        answer = await answer_result if inspect.isawaitable(answer_result) else answer_result
        graph_debug = _append_node(state, "answer_generator")
        graph_debug["answer_generator"] = "injected"
        return {
            "answer": str(answer or build_safe_fallback_answer(query)),
            "model_debug": {
                "provider": "injected",
                "model": None,
                "answer_generator": "injected",
            },
            "graph_debug": graph_debug,
        }

    return answer_generator_node


def _message_text(message: BaseMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return content
    return "".join(
        str(item.get("text", ""))
        for item in content
        if isinstance(item, dict) and item.get("type") == "text"
    )


def _resolve_model(model_name: Any | None) -> Any:
    selected = model_name or settings.DEFAULT_MODEL
    if selected is None:
        raise ValueError("No model is configured")
    for candidate in settings.AVAILABLE_MODELS:
        if str(candidate) == str(selected):
            return candidate
    return selected


def _is_fake_model(model_name: Any) -> bool:
    return str(model_name) == str(FakeModelName.FAKE)


async def _real_answer_generator(
    query: str,
    sources: list[dict[str, Any]],
    *,
    model_name: Any | None = None,
) -> tuple[str, dict[str, Any], bool]:
    selected_model = _resolve_model(model_name)
    if not sources:
        return (
            build_safe_fallback_answer(query),
            {
                "provider": "fallback",
                "model": str(selected_model),
                "answer_generator": "safe_fallback",
            },
            False,
        )

    context_parts = []
    for source in sources[:5]:
        title = _source_value(source, "title") or "source"
        preview = _source_value(source, "content_preview") or _source_value(source, "preview")
        context_parts.append(f"[{title}] {preview}")
    context = "\n\n".join(context_parts)
    messages = [
        SystemMessage(content=ANSWER_SYNTHESIS_PROMPT),
        HumanMessage(content=f"User question:\n{query}\n\nRetrieved context:\n{context}"),
    ]
    calls_real_llm = False
    try:
        model = get_model(selected_model)
        calls_real_llm = not _is_fake_model(selected_model)
        response = await model.ainvoke(messages)
        answer = _message_text(response).strip()
        if not answer:
            answer = build_safe_fallback_answer(query)
        return (
            answer,
            {
                "provider": "fake" if _is_fake_model(selected_model) else "configured",
                "model": str(selected_model),
                "answer_generator": "model_ainvoke",
            },
            calls_real_llm,
        )
    except Exception as exc:
        return (
            build_safe_fallback_answer(query),
            {
                "provider": "model_error",
                "model": str(selected_model),
                "answer_generator": "safe_fallback",
                "error": type(exc).__name__,
            },
            calls_real_llm,
        )


async def answer_generator_node(state: EnterpriseRAGGraphState) -> EnterpriseRAGGraphState:
    """Generate an answer through the configured model with a stable fallback."""
    query = state.get("contextual_query") or _normalized_query(state)
    answer, model_debug, calls_real_llm = await _real_answer_generator(
        query,
        list(state.get("ranked_sources") or []),
        model_name=state.get("model"),
    )
    graph_debug = _append_node(state, "answer_generator")
    graph_debug.update(
        {
            "answer_generator": model_debug.get("answer_generator"),
            "calls_llm": calls_real_llm,
            "calls_real_llm": calls_real_llm,
        }
    )
    fallback = dict(state.get("fallback") or {})
    if model_debug.get("provider") in {"fallback", "model_error"}:
        fallback = {
            "triggered": True,
            "reason": "no_sources"
            if model_debug.get("provider") == "fallback"
            else "model_error",
        }
    return {
        "answer": answer,
        "model_debug": model_debug,
        "fallback": fallback,
        "graph_debug": graph_debug,
    }


def _build_evidence_verifier_node(
    verifier_mode: str,
) -> Callable[[EnterpriseRAGGraphState], Awaitable[EnterpriseRAGGraphState]]:
    async def evidence_verifier_node(state: EnterpriseRAGGraphState) -> EnterpriseRAGGraphState:
        result = verify_answer_grounding(
            query=_normalized_query(state),
            answer=state.get("answer", ""),
            sources=list(state.get("ranked_sources") or []),
            query_type=state.get("query_type"),
            mode=verifier_mode,
            safe_fallback_enabled=rag_settings.ENTERPRISE_EVIDENCE_SAFE_FALLBACK,
            min_score=rag_settings.ENTERPRISE_EVIDENCE_MIN_SCORE,
            high_score=rag_settings.ENTERPRISE_EVIDENCE_HIGH_SCORE,
        )
        update: EnterpriseRAGGraphState = {
            "verifier_debug": result.as_debug(),
            "graph_debug": _append_node(state, "evidence_verifier"),
        }
        if result.safe_fallback_triggered:
            update["answer"] = build_safe_fallback_answer(_normalized_query(state))
        return update

    return evidence_verifier_node


async def evidence_verifier_node(state: EnterpriseRAGGraphState) -> EnterpriseRAGGraphState:
    """Run the configured Phase 6I verifier for a custom-graph state."""
    return await _build_evidence_verifier_node(rag_settings.evidence_verifier_mode)(state)


async def clarification_response_node(state: EnterpriseRAGGraphState) -> EnterpriseRAGGraphState:
    query = _normalized_query(state)
    if any("\u4e00" <= character <= "\u9fff" for character in query):
        answer = "请补充具体主题或指明你希望继续讨论的内容。"
    else:
        answer = "Please specify the topic or the content you want to continue discussing."
    return {
        "answer": answer,
        "retrieved_sources": [],
        "ranked_sources": [],
        "retrieval_debug": {"hit_count": 0, "skipped_reason": "clarification_required"},
        "verifier_debug": {},
        "fallback": {"triggered": True, "reason": "clarification_required"},
        "graph_debug": _append_node(state, "clarification_response"),
    }


async def safe_response_node(state: EnterpriseRAGGraphState) -> EnterpriseRAGGraphState:
    query = _normalized_query(state)
    if any("\u4e00" <= character <= "\u9fff" for character in query):
        answer = "该问题不在当前知识库问答范围内，请提供与知识库相关的问题。"
    else:
        answer = "This question is outside the current knowledge-base scope."
    return {
        "answer": answer,
        "retrieved_sources": [],
        "ranked_sources": [],
        "retrieval_debug": {"hit_count": 0, "skipped_reason": "unsupported_query"},
        "verifier_debug": {},
        "fallback": {"triggered": True, "reason": "unsupported_query"},
        "graph_debug": _append_node(state, "safe_response"),
    }


async def final_response_node(state: EnterpriseRAGGraphState) -> EnterpriseRAGGraphState:
    sources = list(state.get("ranked_sources") or state.get("retrieved_sources") or [])
    citations = [
        {
            "source_id": _source_value(source, "source_id"),
            "title": _source_value(source, "title"),
            "chunk_id": _source_value(source, "chunk_id"),
            "source_url": _source_value(source, "source_url"),
        }
        for source in sources
    ]
    graph_debug = _append_node(state, "final_response")
    memory_debug = dict(state.get("memory_debug") or {})
    session_id = state.get("session_id")
    if memory_debug.get("memory_enabled") and session_id:
        store = get_memory_store(
            max_turns=rag_settings.ENTERPRISE_MEMORY_MAX_TURNS,
            max_answer_chars=rag_settings.ENTERPRISE_MEMORY_MAX_ANSWER_CHARS,
        )
        store.append_turn(session_id, _normalized_query(state), state.get("answer", ""), sources)
        memory_debug["memory_turn_count_after"] = store.get_turn_count(session_id)
        memory_debug["memory_written"] = True
    else:
        memory_debug["memory_turn_count_after"] = memory_debug.get("memory_turn_count_before", 0)
        memory_debug["memory_written"] = False
    response_sources = sources if state.get("return_sources", True) else []
    final_graph_debug = {
        **graph_debug,
        "nodes_executed": list(graph_debug.get("nodes_executed") or []),
    }
    response = {
        "answer": state.get("answer", ""),
        "sources": response_sources,
        "citations": citations,
        "query_type": state.get("query_type"),
        "memory_debug": memory_debug,
        "retrieval_debug": dict(state.get("retrieval_debug") or {}),
        "verifier_debug": dict(state.get("verifier_debug") or {}),
        "graph_debug": final_graph_debug,
        "model_debug": dict(state.get("model_debug") or {}),
        "fallback": dict(state.get("fallback") or {}),
    }
    return {
        "citations": citations,
        "memory_debug": memory_debug,
        "graph_debug": final_graph_debug,
        "final_response": response,
    }


def route_after_classifier(state: EnterpriseRAGGraphState) -> str:
    query_type = state.get("query_type")
    if query_type == "ambiguous_query":
        return "clarification_response"
    if query_type == "unsupported_query":
        return "safe_response"
    return "memory_rewriter"


def route_after_verifier(state: EnterpriseRAGGraphState) -> str:
    return "final_response"


def build_enterprise_rag_graph(
    *,
    retriever: Retriever | None = None,
    answer_generator: AnswerGenerator | None = None,
    verifier_mode: str | None = None,
) -> Any:
    graph = StateGraph(EnterpriseRAGGraphState)
    graph.add_node("query_classifier", query_classifier_node)
    graph.add_node("memory_rewriter", memory_rewriter_node)
    graph.add_node("retriever", _build_retriever_node(retriever) if retriever else retriever_node)
    graph.add_node("ranker", ranker_node)
    graph.add_node(
        "answer_generator",
        _build_answer_generator_node(answer_generator) if answer_generator else answer_generator_node,
    )
    graph.add_node(
        "evidence_verifier",
        _build_evidence_verifier_node(verifier_mode)
        if verifier_mode
        else evidence_verifier_node,
    )
    graph.add_node("clarification_response", clarification_response_node)
    graph.add_node("safe_response", safe_response_node)
    graph.add_node("final_response", final_response_node)
    graph.set_entry_point("query_classifier")
    graph.add_conditional_edges(
        "query_classifier",
        route_after_classifier,
        {
            "clarification_response": "clarification_response",
            "safe_response": "safe_response",
            "memory_rewriter": "memory_rewriter",
        },
    )
    graph.add_edge("memory_rewriter", "retriever")
    graph.add_edge("retriever", "ranker")
    graph.add_edge("ranker", "answer_generator")
    graph.add_edge("answer_generator", "evidence_verifier")
    graph.add_conditional_edges(
        "evidence_verifier",
        route_after_verifier,
        {"final_response": "final_response"},
    )
    graph.add_edge("clarification_response", "final_response")
    graph.add_edge("safe_response", "final_response")
    graph.add_edge("final_response", END)
    return graph.compile()


_enterprise_rag_graph: Any | None = None


def get_enterprise_rag_graph() -> Any:
    global _enterprise_rag_graph
    if _enterprise_rag_graph is None:
        _enterprise_rag_graph = build_enterprise_rag_graph()
    return _enterprise_rag_graph


async def run_enterprise_rag_graph(
    query: str,
    *,
    session_id: str | None = None,
    top_k: int = 5,
    return_sources: bool = True,
    model: Any | None = None,
    graph: Any | None = None,
) -> dict[str, Any]:
    compiled_graph = graph or get_enterprise_rag_graph()
    result = await compiled_graph.ainvoke(
        {
            "query": query,
            "session_id": session_id,
            "top_k": top_k,
            "return_sources": return_sources,
            "model": model,
            "graph_debug": {
                "graph_mode": "custom_graph",
                "nodes_executed": [],
                "route": None,
                "calls_llm": False,
                "calls_real_llm": False,
                "writes_chroma": False,
            },
        }
    )
    final_response = dict(result.get("final_response") or {})
    graph_debug = dict(final_response.get("graph_debug") or result.get("graph_debug") or {})
    graph_debug["nodes_executed"] = list(graph_debug.get("nodes_executed") or [])
    final_response["graph_debug"] = graph_debug
    return final_response
