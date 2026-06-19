from __future__ import annotations

from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, MessagesState, StateGraph

from agents.enterprise_tools import enterprise_knowledge_retriever_func
from core import get_model, settings
from rag.config import rag_settings
from rag.conversation_memory import contextualize_query_with_memory, get_memory_store
from rag.evidence_verifier import build_safe_fallback_answer, verify_answer_grounding

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
Use the same language as the user's question. If the user question is Chinese, you must answer in Chinese. If the user question is English, answer in English, unless the user explicitly asks for another language. Do not switch to English only because retrieved context contains English titles, file names, or technical terms.

请使用与用户问题相同的语言回答。若用户问题为中文，必须使用中文回答；若用户问题为英文，使用英文回答；除非用户明确要求其他语言。不要因为检索上下文中包含英文标题或英文术语就切换为英文。
回答必须基于检索到的 context。若 context 不足，请用用户问题相同语言说明知识库中没有足够依据。不要编造来源。
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
    memory_debug: dict[str, Any]
    verifier_debug: dict[str, Any]


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


def _contains_cjk(text: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in text)


def _requests_english(query: str) -> bool:
    normalized = query.lower()
    english_requests = {
        "answer in english",
        "respond in english",
        "use english",
        "in english",
        "用英文",
        "使用英文",
        "英文回答",
        "英语回答",
    }
    return any(request in normalized for request in english_requests)


def _should_answer_in_chinese(query: str) -> bool:
    return _contains_cjk(query) and not _requests_english(query)


def _language_instruction(query: str) -> str:
    if _should_answer_in_chinese(query):
        return (
            "The user question is Chinese. You must answer in Chinese. "
            "Keep file names and source IDs unchanged, but all explanatory text must be Chinese."
        )
    return "Use the same language as the user's question unless the user explicitly requested another language."


def _get_top_k(config: RunnableConfig) -> int | str | None:
    configurable = config.get("configurable", {})
    return configurable.get("top_k")


def _get_memory_session_id(config: RunnableConfig) -> str | None:
    configurable = config.get("configurable", {})
    session_id = configurable.get("memory_session_id")
    normalized = str(session_id or "").strip()
    return normalized or None


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


def _fallback_answer(reason: str | None = None, query: str = "") -> str:
    if reason == "empty_query":
        return "请输入一个需要查询的问题。"
    if _should_answer_in_chinese(query):
        if reason == "smalltalk":
            return "我可以回答企业知识库中的问题。请提供需要查询的具体主题。"
        if reason:
            return f"当前知识库没有足够依据可靠回答该问题。fallback 原因：{reason}。"
        return "当前知识库没有足够依据可靠回答该问题。"
    if reason == "smalltalk":
        return (
            "I can answer questions from the enterprise knowledge base. "
            "Please provide a specific topic to query."
        )
    if reason:
        return f"{FALLBACK_PROMPT} Fallback reason: {reason}."
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
    """Normalize the query and optionally contextualize a session-scoped follow-up."""
    query = state.get("query", "")
    rewritten_query = " ".join(query.split())
    session_id = _get_memory_session_id(config)
    store = get_memory_store(
        max_turns=rag_settings.ENTERPRISE_MEMORY_MAX_TURNS,
        max_answer_chars=rag_settings.ENTERPRISE_MEMORY_MAX_ANSWER_CHARS,
    )
    contextual_query, memory_debug = contextualize_query_with_memory(
        query=rewritten_query,
        session_id=session_id,
        memory_mode=rag_settings.memory_mode,
        store=store,
    )
    return {"rewritten_query": contextual_query, "memory_debug": memory_debug}


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
    retrieval_debug["original_query"] = state.get("query", "")
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
            "draft_answer": _fallback_answer(reason, query=state.get("query", "")),
            "model_debug": {
                "provider": "fallback",
                "model": None,
            },
        }

    model_name = config.get("configurable", {}).get("model", settings.DEFAULT_MODEL)
    messages = [
        SystemMessage(content=ANSWER_SYNTHESIS_PROMPT),
        HumanMessage(
            content=(
                f"User question:\n{state.get('query', '')}\n\n"
                f"Retrieval query:\n{state.get('rewritten_query', '')}\n\n"
                f"Retrieved context:\n{context}\n\n"
                f"{_language_instruction(state.get('query', ''))}"
            )
        ),
    ]
    try:
        model = get_model(model_name)
        response = await model.ainvoke(messages, config)
        answer = _message_text(response).strip()
    except Exception as exc:
        answer = _fallback_answer(f"model_error:{type(exc).__name__}", query=state.get("query", ""))
        return {
            "draft_answer": answer,
            "model_debug": {
                "provider": "model_error",
                "model": str(model_name),
                "error": type(exc).__name__,
            },
        }

    if not answer:
        answer = _fallback_answer(query=state.get("query", ""))
    return {
        "draft_answer": answer,
        "model_debug": {
            "provider": "configured",
            "model": str(model_name),
        },
    }


async def verify_evidence(
    state: EnterpriseRagState, config: RunnableConfig
) -> EnterpriseRagState:
    """Attach optional deterministic evidence-grounding diagnostics."""
    mode = rag_settings.evidence_verifier_mode
    if mode == "off":
        return {"verifier_debug": {}}

    retrieval = state.get("retrieval", {})
    retrieval_debug = retrieval.get("retrieval_debug") or {}
    result = verify_answer_grounding(
        query=state.get("query", ""),
        answer=state.get("draft_answer", ""),
        sources=list(retrieval.get("sources") or []),
        query_type=retrieval_debug.get("inferred_query_type"),
        mode=mode,
        safe_fallback_enabled=rag_settings.ENTERPRISE_EVIDENCE_SAFE_FALLBACK,
        min_score=rag_settings.ENTERPRISE_EVIDENCE_MIN_SCORE,
        high_score=rag_settings.ENTERPRISE_EVIDENCE_HIGH_SCORE,
    )
    update: EnterpriseRagState = {"verifier_debug": result.as_debug()}
    if result.safe_fallback_triggered:
        update["draft_answer"] = build_safe_fallback_answer(state.get("query", ""))
    return update


async def fallback_or_finish(
    state: EnterpriseRagState, config: RunnableConfig
) -> EnterpriseRagState:
    """Attach source tracing metadata and return the final message."""
    retrieval = state.get("retrieval", {})
    sources = retrieval.get("sources") or []
    retrieval_debug = retrieval.get("retrieval_debug") or {}
    answer = state.get("draft_answer") or FALLBACK_PROMPT
    memory_debug = dict(state.get("memory_debug") or {})
    session_id = memory_debug.get("session_id")
    if memory_debug.get("memory_enabled") and session_id:
        store = get_memory_store(
            max_turns=rag_settings.ENTERPRISE_MEMORY_MAX_TURNS,
            max_answer_chars=rag_settings.ENTERPRISE_MEMORY_MAX_ANSWER_CHARS,
        )
        store.append_turn(
            session_id=session_id,
            user_query=state.get("query", ""),
            assistant_answer=answer,
            sources=sources,
        )
        memory_debug["memory_turn_count_after"] = store.get_turn_count(session_id)
        memory_debug["memory_written"] = True
    else:
        memory_debug["memory_turn_count_after"] = memory_debug.get(
            "memory_turn_count_before", 0
        )
        memory_debug["memory_written"] = False
    answer_with_sources = answer + _format_source_summary(sources)
    return {
        "messages": [
            AIMessage(
                content=answer_with_sources,
                response_metadata={
                    "answer": answer,
                    "sources": sources,
                    "retrieval_debug": retrieval_debug,
                    "fallback": retrieval.get("fallback") or {},
                    "model_debug": state.get("model_debug") or {},
                    "memory_debug": memory_debug,
                    "verifier_debug": state.get("verifier_debug") or {},
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
agent.add_node("verify_evidence", verify_evidence)
agent.add_node("fallback_or_finish", fallback_or_finish)
agent.set_entry_point("guard_input")
agent.add_edge("guard_input", "route_need_retrieval")
agent.add_edge("route_need_retrieval", "rewrite_query")
agent.add_edge("rewrite_query", "retrieve")
agent.add_edge("retrieve", "answer_synthesis")
agent.add_edge("answer_synthesis", "verify_evidence")
agent.add_edge("verify_evidence", "fallback_or_finish")
agent.add_edge("fallback_or_finish", END)

enterprise_rag_agent = agent.compile()
