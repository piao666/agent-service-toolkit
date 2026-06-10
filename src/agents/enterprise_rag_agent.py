from __future__ import annotations

from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, MessagesState, StateGraph

from agents.enterprise_tools import enterprise_knowledge_retriever_func
from core import get_model, settings

INPUT_GUARD_DESCRIPTION = (
    "Check whether the user input is empty or clearly unsuitable for knowledge-base QA."
)

QUERY_REWRITE_PROMPT = """Rewrite the user question into a concise retrieval query.
For now, keep the original intent and do not add facts that the user did not provide.
"""

ANSWER_SYNTHESIS_PROMPT = """You are an enterprise knowledge-base RAG agent.
Answer the user's question only from the retrieved context below.
If the context is insufficient, say that the knowledge base does not contain enough evidence.
Do not invent sources, file names, or facts.
Keep the answer concise and useful.
"""

FALLBACK_PROMPT = (
    "The knowledge base does not contain enough evidence to answer this question reliably."
)


class EnterpriseRagState(MessagesState, total=False):
    query: str
    rewritten_query: str
    should_retrieve: bool
    guard_reason: str | None
    retrieval: dict[str, Any]
    draft_answer: str
    model_debug: dict[str, Any]


def _message_text(message: BaseMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return content
    parts: list[str] = []
    for item in content:
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, dict) and item.get("type") == "text":
            parts.append(str(item.get("text", "")))
    return "".join(parts)


def _latest_user_query(messages: list[BaseMessage]) -> str:
    for message in reversed(messages):
        if isinstance(message, HumanMessage):
            return _message_text(message).strip()
    if messages:
        return _message_text(messages[-1]).strip()
    return ""


def _is_smalltalk(query: str) -> bool:
    normalized = query.strip().lower()
    smalltalk_inputs = {
        "hi",
        "hello",
        "hey",
        "thanks",
        "thank you",
        "你好",
        "您好",
        "谢谢",
        "多谢",
    }
    return normalized in smalltalk_inputs


def _get_top_k(config: RunnableConfig) -> int | str | None:
    configurable = config.get("configurable", {})
    return configurable.get("top_k")


def _format_source_summary(sources: list[dict[str, Any]], limit: int = 5) -> str:
    if not sources:
        return ""

    lines = ["\n\n参考来源："]
    for index, source in enumerate(sources[:limit], start=1):
        source_name = Path(str(source.get("source") or "unknown")).name
        title = source.get("title") or source_name
        chunk_id = source.get("chunk_id") or ""
        relevance_score = source.get("relevance_score")
        score_text = (
            f", relevance_score={relevance_score:.4f}"
            if isinstance(relevance_score, int | float)
            else ""
        )
        lines.append(f"{index}. {title} ({source_name}, chunk_id={chunk_id}{score_text})")
    return "\n".join(lines)


def _fallback_answer(reason: str | None = None) -> str:
    if reason == "empty_query":
        return "请输入一个需要查询的问题。"
    if reason == "smalltalk":
        return "我可以回答企业知识库中的问题。请提供需要查询的具体主题。"
    if reason:
        return f"{FALLBACK_PROMPT} 当前 fallback 原因：{reason}。"
    return FALLBACK_PROMPT


async def guard_input(state: EnterpriseRagState, config: RunnableConfig) -> EnterpriseRagState:
    """Apply lightweight input guard logic before retrieval."""
    query = _latest_user_query(state["messages"])
    if not query:
        return {
            "query": "",
            "should_retrieve": False,
            "guard_reason": "empty_query",
        }
    return {
        "query": query,
        "should_retrieve": True,
        "guard_reason": None,
    }


async def route_need_retrieval(
    state: EnterpriseRagState, config: RunnableConfig
) -> EnterpriseRagState:
    """Route obvious non-knowledge-base inputs away from retrieval."""
    query = state.get("query", "")
    if state.get("guard_reason"):
        return {"should_retrieve": False}
    if _is_smalltalk(query):
        return {
            "should_retrieve": False,
            "guard_reason": "smalltalk",
        }
    return {"should_retrieve": True}


async def rewrite_query(state: EnterpriseRagState, config: RunnableConfig) -> EnterpriseRagState:
    """Keep query rewrite lightweight while preserving a future extension point."""
    query = state.get("query", "")
    rewritten_query = " ".join(query.split())
    return {"rewritten_query": rewritten_query}


async def retrieve(state: EnterpriseRagState, config: RunnableConfig) -> EnterpriseRagState:
    """Call the Phase 2 enterprise retriever tool wrapper."""
    query = state.get("rewritten_query") or state.get("query", "")
    top_k = _get_top_k(config)
    if not state.get("should_retrieve", False):
        reason = state.get("guard_reason") or "retrieval_not_needed"
        retrieval = {
            "context": "",
            "sources": [],
            "retrieval_debug": {
                "original_query": state.get("query", ""),
                "rewritten_query": query,
                "top_k": top_k,
                "hit_count": 0,
                "embedding_provider": "local",
                "vector_store": "chroma",
            },
            "fallback": {
                "triggered": True,
                "reason": reason,
            },
        }
        return {"retrieval": retrieval}

    retrieval = enterprise_knowledge_retriever_func(query=query, top_k=top_k)  # type: ignore[arg-type]
    retrieval_debug = dict(retrieval.get("retrieval_debug") or {})
    retrieval_debug["rewritten_query"] = query
    retrieval["retrieval_debug"] = retrieval_debug
    return {"retrieval": retrieval}


async def answer_synthesis(
    state: EnterpriseRagState, config: RunnableConfig
) -> EnterpriseRagState:
    """Synthesize the final answer from retrieved context."""
    retrieval = state.get("retrieval", {})
    fallback = retrieval.get("fallback") or {}
    sources = retrieval.get("sources") or []
    context = retrieval.get("context") or ""
    if fallback.get("triggered") or not sources or not context:
        reason = fallback.get("reason") or state.get("guard_reason")
        return {
            "draft_answer": _fallback_answer(reason),
            "model_debug": {
                "provider": "fallback",
                "model": None,
            },
        }

    model_name = config.get("configurable", {}).get("model", settings.DEFAULT_MODEL)
    model = get_model(model_name)
    messages = [
        SystemMessage(content=ANSWER_SYNTHESIS_PROMPT),
        HumanMessage(
            content=(
                f"User question:\n{state.get('query', '')}\n\n"
                f"Retrieval query:\n{state.get('rewritten_query', '')}\n\n"
                f"Retrieved context:\n{context}\n\n"
                "Answer in Chinese unless the user asked for another language."
            )
        ),
    ]
    try:
        response = await model.ainvoke(messages, config)
        answer = _message_text(response).strip()
    except Exception as exc:
        answer = f"{FALLBACK_PROMPT} 模型调用失败：{type(exc).__name__}。"
        return {
            "draft_answer": answer,
            "model_debug": {
                "provider": "model_error",
                "model": str(model_name),
                "error": type(exc).__name__,
            },
        }

    if not answer:
        answer = FALLBACK_PROMPT
    return {
        "draft_answer": answer,
        "model_debug": {
            "provider": "configured",
            "model": str(model_name),
        },
    }


async def fallback_or_finish(
    state: EnterpriseRagState, config: RunnableConfig
) -> EnterpriseRagState:
    """Attach source tracing metadata and return the final message."""
    retrieval = state.get("retrieval", {})
    sources = retrieval.get("sources") or []
    retrieval_debug = retrieval.get("retrieval_debug") or {}
    answer = state.get("draft_answer") or FALLBACK_PROMPT
    answer_with_sources = answer + _format_source_summary(sources)
    return {
        "messages": [
            AIMessage(
                content=answer_with_sources,
                response_metadata={
                    "sources": sources,
                    "retrieval_debug": retrieval_debug,
                    "fallback": retrieval.get("fallback") or {},
                    "model_debug": state.get("model_debug") or {},
                },
            )
        ]
    }


agent = StateGraph(EnterpriseRagState)
agent.add_node("guard_input", guard_input)
agent.add_node("route_need_retrieval", route_need_retrieval)
agent.add_node("rewrite_query", rewrite_query)
agent.add_node("retrieve", retrieve)
agent.add_node("answer_synthesis", answer_synthesis)
agent.add_node("fallback_or_finish", fallback_or_finish)
agent.set_entry_point("guard_input")
agent.add_edge("guard_input", "route_need_retrieval")
agent.add_edge("route_need_retrieval", "rewrite_query")
agent.add_edge("rewrite_query", "retrieve")
agent.add_edge("retrieve", "answer_synthesis")
agent.add_edge("answer_synthesis", "fallback_or_finish")
agent.add_edge("fallback_or_finish", END)

enterprise_rag_agent = agent.compile()
