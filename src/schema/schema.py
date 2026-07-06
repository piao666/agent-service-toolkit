from typing import Any, Literal, NotRequired

from pydantic import BaseModel, Field, SerializeAsAny
from typing_extensions import TypedDict

from schema.models import AllModelEnum, AnthropicModelName, OpenAIModelName


class AgentInfo(BaseModel):
    """Info about an available agent."""

    key: str = Field(
        description="Agent key.",
        examples=["research-assistant"],
    )
    description: str = Field(
        description="Description of the agent.",
        examples=["A research assistant for generating research papers."],
    )


class ServiceMetadata(BaseModel):
    """Metadata about the service including available agents and models."""

    agents: list[AgentInfo] = Field(
        description="List of available agents.",
    )
    models: list[AllModelEnum] = Field(
        description="List of available LLMs.",
    )
    default_agent: str = Field(
        description="Default agent used when none is specified.",
        examples=["research-assistant"],
    )
    default_model: AllModelEnum = Field(
        description="Default model used when none is specified.",
    )


class UserInput(BaseModel):
    """Basic user input for the agent."""

    message: str = Field(
        description="User input to the agent.",
        examples=["What is the weather in Tokyo?"],
    )
    model: SerializeAsAny[AllModelEnum] | None = Field(
        title="Model",
        description="LLM Model to use for the agent. Defaults to the default model set in the settings of the service.",
        default=None,
        examples=[OpenAIModelName.GPT_5_NANO, AnthropicModelName.HAIKU_45],
    )
    thread_id: str | None = Field(
        description="Thread ID to persist and continue a multi-turn conversation.",
        default=None,
        examples=["847c6285-8fc9-4560-a83f-4e6285809254"],
    )
    user_id: str | None = Field(
        description="User ID to persist and continue a conversation across multiple threads.",
        default=None,
        examples=["847c6285-8fc9-4560-a83f-4e6285809254"],
    )
    agent_config: dict[str, Any] = Field(
        description="Additional configuration to pass through to the agent",
        default={},
        examples=[{"spicy_level": 0.8}],
    )


class StreamInput(UserInput):
    """User input for streaming the agent's response."""

    stream_tokens: bool = Field(
        description="Whether to stream LLM tokens to the client.",
        default=True,
    )


class EnterpriseAgentQueryInput(BaseModel):
    """Business-friendly query input for the enterprise RAG agent."""

    query: str = Field(
        description="User question to answer with the enterprise knowledge-base agent.",
        examples=["What is the role of RAG in an enterprise knowledge-base agent?"],
    )
    session_id: str | None = Field(
        description="Business session ID. Mapped to the service thread_id.",
        default=None,
        examples=["phase4-test-001"],
    )
    top_k: int = Field(
        description="Maximum number of retrieved source chunks to use.",
        default=5,
        ge=0,
        le=20,
        examples=[5],
    )
    return_sources: bool = Field(
        description="Whether to include source tracing results in the response.",
        default=True,
    )
    model: SerializeAsAny[AllModelEnum] | None = Field(
        title="Model",
        description="Optional LLM model selection using the service model registry.",
        default=None,
        examples=[OpenAIModelName.GPT_5_NANO, AnthropicModelName.HAIKU_45],
    )


class EnterpriseAgentQueryResponse(BaseModel):
    """Structured response for business-facing enterprise RAG calls."""

    answer: str = Field(description="Final natural-language answer.")
    sources: list[dict[str, Any]] = Field(
        description="Source tracing results. Empty when return_sources is false.",
        default_factory=list,
    )
    retrieval_debug: dict[str, Any] = Field(
        description="Retrieval diagnostics for observability.",
        default_factory=dict,
    )
    latency_ms: float = Field(description="Endpoint processing latency in milliseconds.")
    model_debug: dict[str, Any] = Field(
        description="Model diagnostics for the answer synthesis step.",
        default_factory=dict,
    )
    memory_debug: dict[str, Any] = Field(
        description="Session-scoped conversational memory diagnostics.",
        default_factory=dict,
    )
    planner_debug: dict[str, Any] = Field(
        description="Optional rule-based planning diagnostics.",
        default_factory=dict,
    )
    verifier_debug: dict[str, Any] = Field(
        description="Optional deterministic evidence-grounding diagnostics.",
        default_factory=dict,
    )
    judge_debug: dict[str, Any] = Field(
        description="Optional rule-based answer-judge diagnostics.",
        default_factory=dict,
    )
    graph_debug: dict[str, Any] = Field(
        description="Optional custom LangGraph execution diagnostics.",
        default_factory=dict,
    )
    fallback: dict[str, Any] = Field(
        description="Fallback status and reason, when triggered.",
        default_factory=dict,
    )
    session_id: str | None = Field(
        description="Business session ID used for this request.",
        default=None,
    )


class ToolCall(TypedDict):
    """Represents a request to call a tool."""

    name: str
    """The name of the tool to be called."""
    args: dict[str, Any]
    """The arguments to the tool call."""
    id: str | None
    """An identifier associated with the tool call."""
    type: NotRequired[Literal["tool_call"]]


class ChatMessage(BaseModel):
    """Message in a chat."""

    type: Literal["human", "ai", "tool", "custom"] = Field(
        description="Role of the message.",
        examples=["human", "ai", "tool", "custom"],
    )
    content: str = Field(
        description="Content of the message.",
        examples=["Hello, world!"],
    )
    tool_calls: list[ToolCall] = Field(
        description="Tool calls in the message.",
        default=[],
    )
    tool_call_id: str | None = Field(
        description="Tool call that this message is responding to.",
        default=None,
        examples=["call_Jja7J89XsjrOLA5r!MEOW!SL"],
    )
    run_id: str | None = Field(
        description="Run ID of the message.",
        default=None,
        examples=["847c6285-8fc9-4560-a83f-4e6285809254"],
    )
    response_metadata: dict[str, Any] = Field(
        description="Response metadata. For example: response headers, logprobs, token counts.",
        default={},
    )
    custom_data: dict[str, Any] = Field(
        description="Custom message data.",
        default={},
    )

    def pretty_repr(self) -> str:
        """Get a pretty representation of the message."""
        base_title = self.type.title() + " Message"
        padded = " " + base_title + " "
        sep_len = (80 - len(padded)) // 2
        sep = "=" * sep_len
        second_sep = sep + "=" if len(padded) % 2 else sep
        title = f"{sep}{padded}{second_sep}"
        return f"{title}\n\n{self.content}"

    def pretty_print(self) -> None:
        print(self.pretty_repr())  # noqa: T201


class Feedback(BaseModel):  # type: ignore[no-redef]
    """Feedback for a run, to record to LangSmith."""

    run_id: str = Field(
        description="Run ID to record feedback for.",
        examples=["847c6285-8fc9-4560-a83f-4e6285809254"],
    )
    key: str = Field(
        description="Feedback key.",
        examples=["human-feedback-stars"],
    )
    score: float = Field(
        description="Feedback score.",
        examples=[0.8],
    )
    kwargs: dict[str, Any] = Field(
        description="Additional feedback kwargs, passed to LangSmith.",
        default={},
        examples=[{"comment": "In-line human feedback"}],
    )


class FeedbackResponse(BaseModel):
    status: Literal["success"] = "success"


class ChatHistoryInput(BaseModel):
    """Input for retrieving chat history."""

    thread_id: str = Field(
        description="Thread ID to persist and continue a multi-turn conversation.",
        examples=["847c6285-8fc9-4560-a83f-4e6285809254"],
    )


class ChatHistory(BaseModel):
    messages: list[ChatMessage]


# ── Phase 4E: Runtime Retrieval Verification ─────────────────────────────


class EnterpriseKBRetrievalRequest(BaseModel):
    """Phase 4E/4F: 检索请求 — 支持 official_docs / internal_engineering_docs / auto。"""

    query: str = Field(
        description="检索查询文本。",
        examples=["How to create a Chroma collection?"],
        min_length=1,
    )
    top_k: int = Field(
        description="返回结果数量。",
        default=5,
        ge=1,
        le=20,
    )
    corpus: Literal["official_docs", "internal_engineering_docs", "auto"] = Field(
        default="official_docs",
        description="检索目标语料库。'auto' 由 corpus_router 自动路由。",
        examples=["official_docs", "internal_engineering_docs", "auto"],
    )


class EnterpriseKBRetrievalResponse(BaseModel):
    """Phase 4E: 检索响应 — 含格式化结果 + trace 诊断。"""

    results: list[dict[str, Any]] = Field(
        description="检索到的 chunk 列表，每项含 chunk_id / source_id / score 等。",
        default_factory=list,
    )
    trace: dict[str, Any] = Field(
        description="检索 trace：query / top_k / embedding_model / collection_name / latency_ms 等。",
        default_factory=dict,
    )
    latency_ms: float = Field(
        description="端点处理总延迟（毫秒）。",
    )
    corpus_used: str = Field(
        default="official_docs",
        description="实际使用的语料库。",
    )


# ── Phase 4H: Traceable RAG Answer ──────────────────────────────────────


class EnterpriseKBRagAnswerRequest(BaseModel):
    """Phase 4H: RAG 回答请求 — 带 citation 的受控 demo 端点。"""

    query: str = Field(
        description="问题文本。",
        examples=["本项目为什么选择 bge-m3 作为默认 embedding？"],
        min_length=1,
    )
    top_k: int = Field(
        description="检索结果数量。",
        default=5,
        ge=1,
        le=20,
    )
    corpus: Literal["official_docs", "internal_engineering_docs", "auto"] = Field(
        default="auto",
        description="检索目标语料库。默认 auto 自动路由。",
    )


class EnterpriseKBRagAnswerResponse(BaseModel):
    """Phase 4H: RAG 回答响应 — mock/extractive 模式，带 citation。"""

    answer: str = Field(
        description="带 citation 标记的回答文本（mock extractive mode）。",
    )
    citations: list[dict[str, Any]] = Field(
        description="引用列表，每项含 source_id / heading_path / score / text_preview。",
        default_factory=list,
    )
    trace: dict[str, Any] = Field(
        description="检索 + routing trace。",
        default_factory=dict,
    )
    latency_ms: float = Field(
        description="端点处理总延迟（毫秒）。",
    )
    corpus_used: str = Field(
        description="实际使用的语料库。",
    )
    llm_mode: str = Field(
        default="mock_extractive",
        description="回答生成模式。mock_extractive = 无 LLM，基于检索结果拼接。",
    )
