import inspect
import json
import logging
import warnings
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from time import perf_counter
from typing import Annotated, Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, FastAPI, HTTPException, status
from fastapi.responses import StreamingResponse
from fastapi.routing import APIRoute
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from langchain_core._api import LangChainBetaWarning
from langchain_core.messages import AIMessage, AIMessageChunk, AnyMessage, HumanMessage, ToolMessage
from langchain_core.runnables import RunnableConfig
from langfuse import Langfuse  # type: ignore[import-untyped]
from langfuse.langchain import (
    CallbackHandler,  # type: ignore[import-untyped]
)
from langgraph.types import Command, Interrupt
from langsmith import Client as LangsmithClient
from langsmith import uuid7

from agents import DEFAULT_AGENT, AgentGraph, get_agent, get_all_agent_info, load_agent
from core import settings
from memory import initialize_database, initialize_store
from rag.config import rag_settings
from schema import (
    ChatHistory,
    ChatHistoryInput,
    ChatMessage,
    EnterpriseAgentQueryInput,
    EnterpriseAgentQueryResponse,
    EnterpriseKBGraphAnswerRequest,
    EnterpriseKBGraphAnswerResponse,
    EnterpriseKBRagAnswerRequest,
    EnterpriseKBRagAnswerResponse,
    EnterpriseKBRetrievalRequest,
    EnterpriseKBRetrievalResponse,
    Feedback,
    FeedbackResponse,
    ServiceMetadata,
    StreamInput,
    UserInput,
)
from service.utils import (
    convert_message_content_to_string,
    langchain_to_chat_message,
    remove_tool_calls,
)

warnings.filterwarnings("ignore", category=LangChainBetaWarning)
logger = logging.getLogger(__name__)


def custom_generate_unique_id(route: APIRoute) -> str:
    """Generate idiomatic operation IDs for OpenAPI client generation."""
    return route.name


def verify_bearer(
    http_auth: Annotated[
        HTTPAuthorizationCredentials | None,
        Depends(HTTPBearer(description="Please provide AUTH_SECRET api key.", auto_error=False)),
    ],
) -> None:
    if not settings.AUTH_SECRET:
        return
    auth_secret = settings.AUTH_SECRET.get_secret_value()
    if not http_auth or http_auth.credentials != auth_secret:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """
    Configurable lifespan that initializes the appropriate database checkpointer, store,
    and agents with async loading - for example for starting up MCP clients.
    """
    try:
        # Initialize both checkpointer (for short-term memory) and store (for long-term memory)
        async with initialize_database() as saver, initialize_store() as store:
            # Set up both components
            if hasattr(saver, "setup"):  # ignore: union-attr
                await saver.setup()
            # Only setup store for Postgres as InMemoryStore doesn't need setup
            if hasattr(store, "setup"):  # ignore: union-attr
                await store.setup()

            # Configure agents with both memory components and async loading
            agents = get_all_agent_info()
            for a in agents:
                try:
                    await load_agent(a.key)
                    logger.info(f"Agent loaded: {a.key}")
                except Exception as e:
                    logger.error(f"Failed to load agent {a.key}: {e}")
                    # Continue with other agents rather than failing startup

                agent = get_agent(a.key)
                # Set checkpointer for thread-scoped memory (conversation history)
                agent.checkpointer = saver
                # Set store for long-term memory (cross-conversation knowledge)
                agent.store = store
            yield
    except Exception as e:
        logger.error(f"Error during database/store/agents initialization: {e}")
        raise


app = FastAPI(lifespan=lifespan, generate_unique_id_function=custom_generate_unique_id)
router = APIRouter(dependencies=[Depends(verify_bearer)])


@router.get("/info")
async def info() -> ServiceMetadata:
    models = list(settings.AVAILABLE_MODELS)
    models.sort()
    return ServiceMetadata(
        agents=get_all_agent_info(),
        models=models,
        default_agent=DEFAULT_AGENT,
        default_model=settings.DEFAULT_MODEL,
    )


async def _handle_input(user_input: UserInput, agent: AgentGraph) -> tuple[dict[str, Any], UUID]:
    """
    Parse user input and handle any required interrupt resumption.
    Returns kwargs for agent invocation and the run_id.
    """
    run_id = uuid7()
    thread_id = user_input.thread_id or str(uuid4())
    user_id = user_input.user_id or str(uuid4())

    configurable = {"thread_id": thread_id, "user_id": user_id}
    if user_input.model is not None:
        configurable["model"] = user_input.model

    callbacks: list[Any] = []
    if settings.LANGFUSE_TRACING:
        # Initialize Langfuse CallbackHandler for Langchain (tracing)
        langfuse_handler = CallbackHandler()

        callbacks.append(langfuse_handler)

    if user_input.agent_config:
        # Check for reserved keys (including 'model' even if not in configurable)
        reserved_keys = {"thread_id", "user_id", "model"}
        if overlap := reserved_keys & user_input.agent_config.keys():
            raise HTTPException(
                status_code=422,
                detail=f"agent_config contains reserved keys: {overlap}",
            )
        configurable.update(user_input.agent_config)

    config = RunnableConfig(
        configurable=configurable,
        run_id=run_id,
        callbacks=callbacks,
    )

    # Check for interrupts that need to be resumed
    state = await agent.aget_state(config=config)
    interrupted_tasks = [
        task for task in state.tasks if hasattr(task, "interrupts") and task.interrupts
    ]

    input: Command | dict[str, Any]
    if interrupted_tasks:
        # assume user input is response to resume agent execution from interrupt
        input = Command(resume=user_input.message)
    else:
        input = {"messages": [HumanMessage(content=user_input.message)]}

    kwargs = {
        "input": input,
        "config": config,
    }

    return kwargs, run_id


@router.post("/{agent_id}/invoke", operation_id="invoke_with_agent_id")
@router.post("/invoke")
async def invoke(user_input: UserInput, agent_id: str = DEFAULT_AGENT) -> ChatMessage:
    """
    Invoke an agent with user input to retrieve a final response.

    If agent_id is not provided, the default agent will be used.
    Use thread_id to persist and continue a multi-turn conversation. run_id kwarg
    is also attached to messages for recording feedback.
    Use user_id to persist and continue a conversation across multiple threads.
    """
    # NOTE: Currently this only returns the last message or interrupt.
    # In the case of an agent outputting multiple AIMessages (such as the background step
    # in interrupt-agent, or a tool step in research-assistant), it's omitted. Arguably,
    # you'd want to include it. You could update the API to return a list of ChatMessages
    # in that case.
    agent: AgentGraph = get_agent(agent_id)
    kwargs, run_id = await _handle_input(user_input, agent)

    try:
        response_events: list[tuple[str, Any]] = await agent.ainvoke(**kwargs, stream_mode=["updates", "values"])  # type: ignore # fmt: skip
        response_type, response = response_events[-1]
        if response_type == "values":
            # Normal response, the agent completed successfully
            output = langchain_to_chat_message(response["messages"][-1])
        elif response_type == "updates" and "__interrupt__" in response:
            # The last thing to occur was an interrupt
            # Return the value of the first interrupt as an AIMessage
            output = langchain_to_chat_message(
                AIMessage(content=response["__interrupt__"][0].value)
            )
        else:
            raise ValueError(f"Unexpected response type: {response_type}")

        output.run_id = str(run_id)
        return output
    except Exception as e:
        logger.error(f"An exception occurred: {e}")
        raise HTTPException(status_code=500, detail="Unexpected error")


def _enterprise_retrieval_debug(
    metadata: dict[str, Any],
    request: EnterpriseAgentQueryInput,
    sources: list[dict[str, Any]],
) -> dict[str, Any]:
    retrieval_debug = dict(metadata.get("retrieval_debug") or {})
    retrieval_debug.setdefault("original_query", request.query)
    retrieval_debug.setdefault("rewritten_query", request.query.strip())
    retrieval_debug.setdefault("top_k", request.top_k)
    retrieval_debug.setdefault("hit_count", len(sources))

    # 如果 query_classifier 已经判定为非知识库问题并短路，则不要补充 Chroma/Embedding 字段，
    # 避免前端误以为本轮仍然执行了向量检索。
    if retrieval_debug.get("retrieval_skipped") or retrieval_debug.get("skipped_reason"):
        retrieval_debug["hit_count"] = 0
        return retrieval_debug

    retrieval_debug.setdefault("embedding_provider", rag_settings.EMBEDDING_PROVIDER)
    retrieval_debug.setdefault("vector_store", "chroma")
    retrieval_debug.setdefault("collection", rag_settings.CHROMA_COLLECTION_NAME)
    retrieval_debug.setdefault("persist_dir", rag_settings.CHROMA_PERSIST_DIR)
    return retrieval_debug


def _enterprise_model_debug(
    metadata: dict[str, Any],
    request: EnterpriseAgentQueryInput,
) -> dict[str, Any]:
    model_debug = dict(metadata.get("model_debug") or {})
    model_debug.setdefault("model", str(request.model or settings.DEFAULT_MODEL))
    model_debug.setdefault("provider", "configured" if request.model or settings.DEFAULT_MODEL else "unknown")
    model_debug.setdefault("agent_graph_mode", rag_settings.agent_graph_mode)
    return model_debug


@router.post("/enterprise/agent/query")
async def enterprise_agent_query(
    request: EnterpriseAgentQueryInput,
) -> EnterpriseAgentQueryResponse:
    """Invoke the enterprise RAG agent through a business-friendly response shape."""
    start_time = perf_counter()
    session_id = request.session_id or str(uuid4())

    if rag_settings.agent_graph_mode == "custom_graph":
        from agents.enterprise_rag_graph import run_enterprise_rag_graph

        try:
            result = await run_enterprise_rag_graph(
                query=request.query,
                session_id=request.session_id,
                top_k=request.top_k,
                return_sources=request.return_sources,
                model=request.model,
            )
        except Exception:
            logger.exception("Enterprise custom graph query failed")
            raise HTTPException(status_code=500, detail="Enterprise custom graph query failed")

        all_sources = list(result.get("sources") or [])
        graph_model_debug = dict(result.get("model_debug") or {})
        model_debug = {
            "provider": "custom_graph",
            "model": str(request.model or settings.DEFAULT_MODEL),
            "graph_mode": "custom_graph",
            "agent_graph_mode": rag_settings.agent_graph_mode,
        }
        if graph_model_debug:
            model_debug["answer_generator"] = graph_model_debug.get("answer_generator")
            model_debug["answer_provider"] = graph_model_debug.get("provider")
            model_debug["answer_synthesis_profile"] = graph_model_debug.get(
                "answer_synthesis_profile"
            )
            model_debug["answer_synthesis_mode"] = graph_model_debug.get(
                "answer_synthesis_mode"
            )
        graph_debug = dict(result.get("graph_debug") or {})
        if graph_debug:
            graph_debug["nodes_executed"] = list(graph_debug.get("nodes_executed") or [])

        return EnterpriseAgentQueryResponse(
            answer=str(result.get("answer") or ""),
            sources=all_sources if request.return_sources else [],
            retrieval_debug=_enterprise_retrieval_debug(result, request, all_sources),
            latency_ms=round((perf_counter() - start_time) * 1000, 2),
            model_debug=model_debug,
            memory_debug=dict(result.get("memory_debug") or {}),
            planner_debug=dict(result.get("planner_debug") or {}),
            verifier_debug=dict(result.get("verifier_debug") or {}),
            judge_debug=dict(result.get("judge_debug") or {}),
            graph_debug=graph_debug,
            fallback=dict(result.get("fallback") or {}),
            session_id=session_id,
        )

    user_input = UserInput(
        message=request.query,
        model=request.model,
        thread_id=session_id,
        agent_config={
            "top_k": request.top_k,
            # Preserve whether the caller supplied a session. The service-generated thread ID
            # must not implicitly enable business conversation memory.
            "memory_session_id": request.session_id,
        },
    )

    try:
        output = await invoke(user_input, agent_id="enterprise-rag-agent")
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Enterprise query failed: {e}")
        raise HTTPException(status_code=500, detail="Enterprise agent query failed")

    metadata = output.response_metadata or {}
    all_sources = list(metadata.get("sources") or [])
    sources = all_sources if request.return_sources else []
    answer = str(metadata.get("answer") or output.content)

    return EnterpriseAgentQueryResponse(
        answer=answer,
        sources=sources,
        retrieval_debug=_enterprise_retrieval_debug(metadata, request, all_sources),
        latency_ms=round((perf_counter() - start_time) * 1000, 2),
        model_debug=_enterprise_model_debug(metadata, request),
        memory_debug=dict(metadata.get("memory_debug") or {}),
        planner_debug={},
        verifier_debug=dict(metadata.get("verifier_debug") or {}),
        judge_debug={},
        graph_debug={},
        fallback=dict(metadata.get("fallback") or {}),
        session_id=session_id,
    )


async def message_generator(
    user_input: StreamInput, agent_id: str = DEFAULT_AGENT
) -> AsyncGenerator[str, None]:
    """
    Generate a stream of messages from the agent.

    This is the workhorse method for the /stream endpoint.
    """
    agent: AgentGraph = get_agent(agent_id)
    kwargs, run_id = await _handle_input(user_input, agent)

    try:
        # Process streamed events from the graph and yield messages over the SSE stream.
        async for stream_event in agent.astream(
            **kwargs, stream_mode=["updates", "messages", "custom"], subgraphs=True
        ):
            if not isinstance(stream_event, tuple):
                continue
            # Handle different stream event structures based on subgraphs
            if len(stream_event) == 3:
                # With subgraphs=True: (node_path, stream_mode, event)
                _, stream_mode, event = stream_event
            else:
                # Without subgraphs: (stream_mode, event)
                stream_mode, event = stream_event
            new_messages = []
            if stream_mode == "updates":
                for node, updates in event.items():
                    # A simple approach to handle agent interrupts.
                    # In a more sophisticated implementation, we could add
                    # some structured ChatMessage type to return the interrupt value.
                    if node == "__interrupt__":
                        interrupt: Interrupt
                        for interrupt in updates:
                            new_messages.append(AIMessage(content=interrupt.value))
                        continue
                    updates = updates or {}
                    update_messages = updates.get("messages", [])
                    # special cases for using langgraph-supervisor library
                    if "supervisor" in node or "sub-agent" in node:
                        # the only tools that come from the actual agent are the handoff and handback tools
                        if isinstance(update_messages[-1], ToolMessage):
                            if "sub-agent" in node and len(update_messages) > 1:
                                # If this is a sub-agent, we want to keep the last 2 messages - the handback tool, and it's result
                                update_messages = update_messages[-2:]
                            else:
                                # If this is a supervisor, we want to keep the last message only - the handoff result. The tool comes from the 'agent' node.
                                update_messages = [update_messages[-1]]
                        else:
                            update_messages = []
                    new_messages.extend(update_messages)

            if stream_mode == "custom":
                new_messages = [event]

            # LangGraph streaming may emit tuples: (field_name, field_value)
            # e.g. ('content', <str>), ('tool_calls', [ToolCall,...]), ('additional_kwargs', {...}), etc.
            # We accumulate only supported fields into `parts` and skip unsupported metadata.
            # More info at: https://langchain-ai.github.io/langgraph/cloud/how-tos/stream_messages/
            processed_messages = []
            current_message: dict[str, Any] = {}
            for message in new_messages:
                if isinstance(message, tuple):
                    key, value = message
                    # Store parts in temporary dict
                    current_message[key] = value
                else:
                    # Add complete message if we have one in progress
                    if current_message:
                        processed_messages.append(_create_ai_message(current_message))
                        current_message = {}
                    processed_messages.append(message)

            # Add any remaining message parts
            if current_message:
                processed_messages.append(_create_ai_message(current_message))

            for message in processed_messages:
                try:
                    chat_message = langchain_to_chat_message(message)
                    chat_message.run_id = str(run_id)
                except Exception as e:
                    logger.error(f"Error parsing message: {e}")
                    yield f"data: {json.dumps({'type': 'error', 'content': 'Unexpected error'})}\n\n"
                    continue
                # LangGraph re-sends the input message, which feels weird, so drop it
                if chat_message.type == "human" and chat_message.content == user_input.message:
                    continue
                yield f"data: {json.dumps({'type': 'message', 'content': chat_message.model_dump()})}\n\n"

            if stream_mode == "messages":
                if not user_input.stream_tokens:
                    continue
                msg, metadata = event
                if "skip_stream" in metadata.get("tags", []):
                    continue
                # For some reason, astream("messages") causes non-LLM nodes to send extra messages.
                # Drop them.
                if not isinstance(msg, AIMessageChunk):
                    continue
                content = remove_tool_calls(msg.content)
                if content:
                    # Empty content in the context of OpenAI usually means
                    # that the model is asking for a tool to be invoked.
                    # So we only print non-empty content.
                    yield f"data: {json.dumps({'type': 'token', 'content': convert_message_content_to_string(content)})}\n\n"
    except Exception as e:
        logger.error(f"Error in message generator: {e}")
        yield f"data: {json.dumps({'type': 'error', 'content': 'Internal server error'})}\n\n"
    finally:
        yield "data: [DONE]\n\n"


def _create_ai_message(parts: dict) -> AIMessage:
    sig = inspect.signature(AIMessage)
    valid_keys = set(sig.parameters)
    filtered = {k: v for k, v in parts.items() if k in valid_keys}
    return AIMessage(**filtered)


def _sse_response_example() -> dict[int | str, Any]:
    return {
        status.HTTP_200_OK: {
            "description": "Server Sent Event Response",
            "content": {
                "text/event-stream": {
                    "example": "data: {'type': 'token', 'content': 'Hello'}\n\ndata: {'type': 'token', 'content': ' World'}\n\ndata: [DONE]\n\n",
                    "schema": {"type": "string"},
                }
            },
        }
    }


@router.post(
    "/{agent_id}/stream",
    response_class=StreamingResponse,
    responses=_sse_response_example(),
    operation_id="stream_with_agent_id",
)
@router.post("/stream", response_class=StreamingResponse, responses=_sse_response_example())
async def stream(user_input: StreamInput, agent_id: str = DEFAULT_AGENT) -> StreamingResponse:
    """
    Stream an agent's response to a user input, including intermediate messages and tokens.

    If agent_id is not provided, the default agent will be used.
    Use thread_id to persist and continue a multi-turn conversation. run_id kwarg
    is also attached to all messages for recording feedback.
    Use user_id to persist and continue a conversation across multiple threads.

    Set `stream_tokens=false` to return intermediate messages but not token-by-token.
    """
    return StreamingResponse(
        message_generator(user_input, agent_id),
        media_type="text/event-stream",
    )


@router.post("/feedback")
async def feedback(feedback: Feedback) -> FeedbackResponse:
    """
    Record feedback for a run to LangSmith.

    This is a simple wrapper for the LangSmith create_feedback API, so the
    credentials can be stored and managed in the service rather than the client.
    See: https://api.smith.langchain.com/redoc#tag/feedback/operation/create_feedback_api_v1_feedback_post
    """
    client = LangsmithClient()
    kwargs = feedback.kwargs or {}
    client.create_feedback(
        run_id=feedback.run_id,
        key=feedback.key,
        score=feedback.score,
        **kwargs,
    )
    return FeedbackResponse()


@router.post("/history")
async def history(input: ChatHistoryInput) -> ChatHistory:
    """
    Get chat history.
    """
    # TODO: Hard-coding DEFAULT_AGENT here is wonky
    agent: AgentGraph = get_agent(DEFAULT_AGENT)
    try:
        state_snapshot = await agent.aget_state(
            config=RunnableConfig(configurable={"thread_id": input.thread_id})
        )
        messages: list[AnyMessage] = state_snapshot.values["messages"]
        chat_messages: list[ChatMessage] = [langchain_to_chat_message(m) for m in messages]
        return ChatHistory(messages=chat_messages)
    except Exception as e:
        logger.error(f"An exception occurred: {e}")
        raise HTTPException(status_code=500, detail="Unexpected error")


@app.get("/health")
async def health_check():
    """Health check endpoint."""

    health_status = {"status": "ok"}

    if settings.LANGFUSE_TRACING:
        try:
            langfuse = Langfuse()
            health_status["langfuse"] = "connected" if langfuse.auth_check() else "disconnected"
        except Exception as e:
            logger.error(f"Langfuse connection error: {e}")
            health_status["langfuse"] = "disconnected"

    return health_status


# ── Phase 4E/4F: Retrieval (dual-corpus) ────────────────────────────────


@app.get("/api/enterprise-kb/retrieval/health")
async def enterprise_kb_retrieval_health():
    """Phase 4F: 双语料库检索索引健康检查（无认证）。"""
    try:
        from rag.vector_store import get_collection_count

        official_count = get_collection_count()
        internal_count = get_collection_count(
            persist_dir=rag_settings.CHROMA_INTERNAL_PERSIST_DIR,
            collection_name=rag_settings.CHROMA_INTERNAL_COLLECTION_NAME,
        )

        return {
            "status": "ok" if (official_count and official_count > 0) else "degraded",
            "corpora": {
                "official_docs": {
                    "collection_name": rag_settings.chroma_collection_name,
                    "persist_dir": rag_settings.CHROMA_PERSIST_DIR,
                    "chunk_count": official_count,
                },
                "internal_engineering_docs": {
                    "collection_name": rag_settings.CHROMA_INTERNAL_COLLECTION_NAME,
                    "persist_dir": rag_settings.CHROMA_INTERNAL_PERSIST_DIR,
                    "chunk_count": internal_count,
                },
            },
            "embedding_model": "bge-m3",
            "reranker_enabled": rag_settings.RERANKER_ENABLED,
        }
    except Exception as e:
        logger.error(f"Retrieval health check failed: {e}")
        return {"status": "error", "detail": str(e)}


@router.post("/api/enterprise-kb/retrieval/search")
async def enterprise_kb_retrieval_search(
    request: EnterpriseKBRetrievalRequest,
) -> EnterpriseKBRetrievalResponse:
    """Phase 4F: 双语料检索（支持 corpus=official_docs/internal_engineering_docs/auto）。"""
    try:
        from rag.corpus_router import route_corpus
        from rag.official_docs_retriever import official_docs_retrieve

        t0 = perf_counter()

        corpus_used = request.corpus
        route_reason = "user_specified"
        if corpus_used == "auto":
            corpus_used = route_corpus(request.query, "auto")
            route_reason = "auto_routed_by_keywords"

        if corpus_used == "internal_engineering_docs":
            from rag.internal_engineering_retriever import internal_engineering_retrieve
            output = internal_engineering_retrieve(request.query, top_k=request.top_k)
        else:
            output = official_docs_retrieve(request.query, top_k=request.top_k)

        latency_ms = round((perf_counter() - t0) * 1000, 2)
        # 注入路由信息到 trace
        output["trace"]["requested_corpus"] = request.corpus
        output["trace"]["corpus_used"] = corpus_used
        output["trace"]["route_reason"] = route_reason

        return EnterpriseKBRetrievalResponse(
            results=output["results"],
            trace=output["trace"],
            latency_ms=latency_ms,
            corpus_used=corpus_used,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Retrieval search failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Phase 4H: Traceable RAG Answer ─────────────────────────────────────


@router.post("/api/enterprise-kb/rag/answer")
async def enterprise_kb_rag_answer(
    request: EnterpriseKBRagAnswerRequest,
) -> EnterpriseKBRagAnswerResponse:
    """Phase 4H: Traceable RAG answer with citations (mock/extractive mode)。

    无 LLM key 时使用 mock extractive answer — 基于检索结果拼接。
    """
    try:
        from rag.traceable_rag_answer import generate_traceable_rag_answer

        t0 = perf_counter()
        output = generate_traceable_rag_answer(
            query=request.query,
            top_k=request.top_k,
            corpus=request.corpus,
        )
        latency_ms = round((perf_counter() - t0) * 1000, 2)

        return EnterpriseKBRagAnswerResponse(
            answer=output["answer"],
            citations=output["citations"],
            trace=output["trace"],
            latency_ms=latency_ms,
            corpus_used=output["corpus_used"],
            llm_mode=output.get("llm_mode", "mock_extractive"),
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"RAG answer failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Phase 5B: Custom Graph Answer ─────────────────────────────────────


@router.post("/api/enterprise-kb/graph/answer")
async def enterprise_kb_graph_answer(
    request: EnterpriseKBGraphAnswerRequest,
) -> EnterpriseKBGraphAnswerResponse:
    """Phase 5B: custom_graph 知识库问答 — 8 节点完整链路。

    无 LLM key 时自动 fallback 到 mock_extractive 模式。
    """
    try:
        from custom_graph.graph import run_custom_graph
        from llm.client import LLMClient

        t0 = perf_counter()
        llm = LLMClient()
        output = run_custom_graph(
            query=request.query,
            corpus=request.corpus,
            session_id=request.session_id,
            llm=llm,
        )
        latency_ms = round((perf_counter() - t0) * 1000, 2)

        return EnterpriseKBGraphAnswerResponse(
            answer_markdown=output.get("answer_markdown", ""),
            citations=output.get("citations", []),
            used_sources=output.get("used_sources", []),
            unsupported_claims=output.get("unsupported_claims", []),
            hallucination_risk=output.get("hallucination_risk", "none"),
            intent_trace=output.get("intent_trace", {}),
            rewrite_trace=output.get("rewrite_trace", {}),
            plan_trace=output.get("plan_trace", {}),
            retrieval_trace=output.get("retrieval_trace", {}),
            rank_trace=output.get("rank_trace", {}),
            llm_trace=output.get("llm_trace", {}),
            citation_trace=output.get("citation_trace", {}),
            graph_debug=output.get("graph_debug", {}),
            memory_trace=output.get("memory_trace", {}),
            long_term_memory_trace=output.get("long_term_memory_trace", {}),
            llm_mode=output.get("llm_mode", "mock_extractive"),
            total_latency_ms=latency_ms,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Graph answer failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ── Phase 8: Memory Admin API ────────────────────────────────────────


@router.get("/api/enterprise-kb/memory/candidates")
async def list_memory_candidates(status: str = "pending"):
    """列出 memory candidates (默认 pending)。"""
    try:
        from long_term_memory.service import get_ltm_service
        svc = get_ltm_service()
        if status == "all":
            candidates = []
            for s in ["pending", "approved", "rejected"]:
                for c in svc.store.list_candidates(status=s):
                    candidates.append(c)
        else:
            candidates = svc.store.list_candidates(status=status)
        return {"candidates": candidates, "count": len(candidates)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/enterprise-kb/memory/candidates/{candidate_id}/approve")
async def approve_memory_candidate(candidate_id: str):
    """批准 candidate → 生成 memory_item。"""
    try:
        from long_term_memory.service import get_ltm_service
        svc = get_ltm_service()
        item = svc.approve(candidate_id)
        if item is None:
            raise HTTPException(status_code=404, detail=f"Candidate {candidate_id} not found or not pending")
        return {"status": "approved", "memory_item": item}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/enterprise-kb/memory/candidates/{candidate_id}/reject")
async def reject_memory_candidate(candidate_id: str):
    """拒绝 candidate。"""
    try:
        from long_term_memory.service import get_ltm_service
        svc = get_ltm_service()
        svc.reject(candidate_id)
        return {"status": "rejected", "candidate_id": candidate_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/enterprise-kb/memory/items")
async def list_memory_items(status: str = "active"):
    """列出 approved memory items。"""
    try:
        from long_term_memory.service import get_ltm_service
        svc = get_ltm_service()
        items = svc.list_all_items(status=status if status != "all" else None)
        return {"items": items, "count": len(items)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/api/enterprise-kb/memory/items/{memory_id}/disable")
async def disable_memory_item(memory_id: str):
    """禁用 memory item。"""
    try:
        from long_term_memory.service import get_ltm_service
        svc = get_ltm_service()
        svc.disable(memory_id)
        return {"status": "disabled", "memory_id": memory_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/api/enterprise-kb/memory/events")
async def list_memory_events(target_type: str = ""):
    """查看 memory events。"""
    try:
        from long_term_memory.service import get_ltm_service
        svc = get_ltm_service()
        events = svc.list_events(target_type=target_type if target_type else None)
        return {"events": events, "count": len(events)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


app.include_router(router)
