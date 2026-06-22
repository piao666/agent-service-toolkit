from __future__ import annotations

import json
import re
import uuid
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

import streamlit as st

APP_TITLE = "Enterprise RAG Console"
DEFAULT_API_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_API_ENDPOINT = "/enterprise/agent/query"
EXAMPLE_QUESTIONS = (
    "RAG 是什么？",
    "它有什么局限？",
    "那它适合什么场景？",
    "FastAPI 的 Request Body 如何定义？",
    "LoRA 有什么作用？",
)
MEMORY_DEBUG_FIELDS = (
    "memory_mode",
    "memory_enabled",
    "session_id",
    "memory_turn_count_before",
    "memory_turn_count_after",
    "is_follow_up",
    "original_query",
    "contextual_query",
    "memory_rewrite_strategy",
    "memory_used_for_retrieval",
    "cross_session_isolated",
)
SENSITIVE_KEY_PARTS = ("api_key", "authorization", "credential", "password", "secret", "token")
WINDOWS_PATH_PATTERN = re.compile(r"\b[A-Za-z]:[\\/][^\s\"']+")
BEARER_PATTERN = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9_.-]+")
SECRET_PATTERN = re.compile(r"\bsk-[A-Za-z0-9_-]{12,}")


class ApiRequestError(RuntimeError):
    """A user-facing API connection or response error."""


def normalize_base_url(base_url: str) -> str:
    """Validate and normalize an HTTP API base URL."""
    normalized = base_url.strip().rstrip("/")
    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("API Base URL 必须是有效的 http:// 或 https:// 地址。")
    return normalized


def build_api_url(base_url: str, endpoint: str) -> str:
    """Build an endpoint URL without accepting non-HTTP schemes."""
    normalized_base = normalize_base_url(base_url)
    normalized_endpoint = "/" + endpoint.strip().lstrip("/")
    return urljoin(normalized_base + "/", normalized_endpoint.lstrip("/"))


def _request_json(
    url: str,
    *,
    timeout_seconds: float,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(
        url,
        data=data,
        headers={"Accept": "application/json", "Content-Type": "application/json"},
        method="GET" if payload is None else "POST",
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:  # noqa: S310
            body = response.read().decode("utf-8")
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise ApiRequestError(f"Agent API 返回 HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise ApiRequestError("未连接到 Agent API，请先启动 FastAPI 服务。") from exc
    except TimeoutError as exc:
        raise ApiRequestError("Agent API 请求超时，请检查服务状态后重试。") from exc

    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ApiRequestError("Agent API 返回了无效 JSON。") from exc
    if not isinstance(parsed, dict):
        raise ApiRequestError("Agent API response schema 不完整：根节点不是对象。")
    return parsed


def request_agent_api(
    base_url: str,
    endpoint: str,
    payload: dict[str, Any],
    timeout_seconds: float,
) -> dict[str, Any]:
    """Call the existing enterprise query endpoint and validate its core response shape."""
    response = _request_json(
        build_api_url(base_url, endpoint),
        timeout_seconds=timeout_seconds,
        payload=payload,
    )
    if not isinstance(response.get("answer"), str):
        raise ApiRequestError("Agent API response schema 不完整：缺少 answer。")
    if not isinstance(response.get("sources", []), list):
        raise ApiRequestError("Agent API response schema 不完整：sources 不是列表。")
    return response


def check_api_health(base_url: str, timeout_seconds: float = 5.0) -> dict[str, Any]:
    """Call the backend health endpoint."""
    return _request_json(
        build_api_url(base_url, "/health"),
        timeout_seconds=timeout_seconds,
    )


def redact_for_display(value: Any, key: str = "") -> Any:
    """Remove credentials and local absolute paths before rendering backend diagnostics."""
    lowered_key = key.lower()
    if any(part in lowered_key for part in SENSITIVE_KEY_PARTS):
        return "<REDACTED>"
    if lowered_key in {"persist_dir", "model_path", "local_path"}:
        return "<LOCAL_PATH>"
    if isinstance(value, dict):
        return {item_key: redact_for_display(item, item_key) for item_key, item in value.items()}
    if isinstance(value, list):
        return [redact_for_display(item, key) for item in value]
    if isinstance(value, str):
        redacted = WINDOWS_PATH_PATTERN.sub("<LOCAL_PATH>", value)
        redacted = BEARER_PATTERN.sub("Bearer <REDACTED>", redacted)
        return SECRET_PATTERN.sub("<REDACTED>", redacted)
    return value


def _source_value(source: dict[str, Any], field: str, default: Any = "-") -> Any:
    metadata = source.get("metadata") if isinstance(source.get("metadata"), dict) else {}
    value = source.get(field)
    if value in (None, "", "unknown"):
        value = metadata.get(field)
    return default if value in (None, "") else value


def render_source_cards(sources: list[dict[str, Any]]) -> None:
    """Render source-tracing metadata without exposing complete retrieved chunks."""
    st.markdown("#### Sources")
    if not sources:
        st.caption("本轮没有返回 sources。")
        return

    for index, raw_source in enumerate(sources, start=1):
        source = redact_for_display(raw_source)
        title = str(_source_value(source, "title", f"Source {index}"))
        source_id = str(_source_value(source, "source_id"))
        with st.expander(f"{index}. {title} · {source_id}", expanded=index == 1):
            left, right = st.columns(2)
            left.markdown(f"**Document type:** `{_source_value(source, 'doc_type')}`")
            left.markdown(f"**Section:** `{_source_value(source, 'section_path')}`")
            right.markdown(f"**Chunk ID:** `{_source_value(source, 'chunk_id')}`")
            score = _source_value(source, "relevance_score", _source_value(source, "score"))
            right.markdown(f"**Relevance:** `{score}`")

            source_url = str(_source_value(source, "source_url", ""))
            if source_url and urlparse(source_url).scheme in {"http", "https"}:
                st.markdown(f"[打开来源页面]({source_url})")

            preview = str(_source_value(source, "content_preview", ""))
            if preview:
                st.caption("Content preview")
                st.write(preview[:500] + ("…" if len(preview) > 500 else ""))


def render_memory_debug(memory_debug: dict[str, Any]) -> None:
    """Render conversational memory diagnostics and follow-up rewriting."""
    st.markdown("#### Memory")
    if not memory_debug:
        st.caption("本轮 response 未返回 memory_debug。")
        return

    safe_debug = redact_for_display(memory_debug)
    if not safe_debug.get("memory_enabled"):
        st.caption("Memory 未启用；本轮按无记忆模式处理。")
    original = str(safe_debug.get("original_query") or "")
    contextual = str(safe_debug.get("contextual_query") or "")
    if safe_debug.get("is_follow_up") and contextual and contextual != original:
        st.info(f"Follow-up rewrite: {original} → {contextual}")

    rows = [{"field": field, "value": safe_debug.get(field)} for field in MEMORY_DEBUG_FIELDS]
    st.dataframe(rows, hide_index=True, use_container_width=True)


def render_verifier_debug(verifier_debug: dict[str, Any]) -> None:
    """Render deterministic evidence-grounding diagnostics."""
    st.markdown("#### Evidence grounding")
    if not verifier_debug:
        st.caption("本轮 response 未返回 verifier_debug。")
        return

    safe_debug = redact_for_display(verifier_debug)
    grounding_status = str(safe_debug.get("grounding_status") or "not_checked")
    grounding_score = safe_debug.get("grounding_score", 0.0)
    citation_coverage = bool(safe_debug.get("citation_coverage"))
    safe_fallback_triggered = bool(safe_debug.get("safe_fallback_triggered"))

    if grounding_status == "low":
        st.error("Evidence grounding: LOW。当前答案缺少充分的来源支持。")
    elif grounding_status == "medium":
        st.warning("Evidence grounding: MEDIUM。建议结合来源人工复核。")
    elif grounding_status == "high":
        st.success("Evidence grounding: HIGH。答案关键术语与返回来源具有较高覆盖。")
    else:
        st.caption("Evidence verifier 未启用或未执行。")

    left, middle, right = st.columns(3)
    left.metric("Grounding score", grounding_score)
    middle.metric("Citation coverage", "yes" if citation_coverage else "no")
    right.metric("Safe fallback", "triggered" if safe_fallback_triggered else "not triggered")
    st.markdown("**Matched terms**")
    st.write(safe_debug.get("matched_terms") or [])
    st.markdown("**Unsupported terms**")
    st.write(safe_debug.get("unsupported_terms") or [])


def render_retrieval_debug(retrieval_debug: dict[str, Any]) -> None:
    """Render retrieval diagnostics in a collapsed section."""
    with st.expander("Retrieval debug", expanded=False):
        if retrieval_debug:
            st.json(redact_for_display(retrieval_debug), expanded=False)
        else:
            st.caption("本轮 response 未返回 retrieval_debug。")


def render_graph_debug(graph_debug: dict[str, Any]) -> None:
    """Render custom graph execution diagnostics in a dedicated section."""
    with st.expander("Graph debug", expanded=False):
        if graph_debug:
            st.json(redact_for_display(graph_debug), expanded=False)
        else:
            st.info(
                "本轮 response 未返回 graph_debug。legacy 模式下该字段可以为空；"
                "custom_graph 模式下应包含 graph_mode、nodes_executed 等信息。"
            )


def render_debug_panel(payload: dict[str, Any], response: dict[str, Any]) -> None:
    """Render request and response diagnostics after display-safe redaction."""
    render_retrieval_debug(response.get("retrieval_debug") or {})
    render_graph_debug(response.get("graph_debug") or {})
    with st.expander("Memory debug JSON", expanded=False):
        st.json(redact_for_display(response.get("memory_debug") or {}), expanded=False)
    with st.expander("Request payload", expanded=False):
        st.json(redact_for_display(payload), expanded=False)
    with st.expander("Raw response JSON", expanded=False):
        st.json(redact_for_display(response), expanded=False)


def _new_session_id() -> str:
    return f"demo-{uuid.uuid4().hex[:12]}"


def _initialize_state() -> None:
    st.session_state.setdefault("messages", [])
    st.session_state.setdefault("session_id", _new_session_id())
    st.session_state.setdefault("pending_question", None)


def _render_sidebar() -> dict[str, Any]:
    with st.sidebar:
        st.header("Demo controls")
        api_base_url = st.text_input("API Base URL", value=DEFAULT_API_BASE_URL)
        api_endpoint = st.text_input("API Endpoint", value=DEFAULT_API_ENDPOINT)
        session_id = st.text_input("Session ID", key="session_id")

        session_col, clear_col = st.columns(2)
        if session_col.button("↻ Session", use_container_width=True, help="生成新的 session ID"):
            st.session_state.session_id = _new_session_id()
            st.session_state.messages = []
            st.rerun()
        if clear_col.button("Clear chat", use_container_width=True):
            st.session_state.messages = []
            st.rerun()
        st.caption("Clear chat 仅清除前端消息；刷新 Session 会使用新的后端 memory 隔离键。")

        memory_mode = st.selectbox("Memory Mode", options=("off", "buffer"), index=0)
        structured_mode = st.selectbox(
            "Structured Retrieval Mode",
            options=("off", "metadata_symbol"),
            index=0,
        )
        st.caption(
            "当前后端模式由服务启动环境变量决定；此处用于展示预期模式，不会修改服务进程配置。"
        )
        top_k = st.number_input("Top K", min_value=1, max_value=10, value=5, step=1)
        return_sources = st.toggle("Return Sources", value=True)
        timeout_seconds = st.number_input(
            "Timeout seconds", min_value=5, max_value=300, value=120, step=5
        )

        if st.button("API Health Check", use_container_width=True):
            try:
                health = check_api_health(api_base_url)
                st.success("Agent API health check 通过。")
                st.json(redact_for_display(health), expanded=False)
            except (ApiRequestError, ValueError) as exc:
                st.error(str(exc))

        st.subheader("Example questions")
        for index, question in enumerate(EXAMPLE_QUESTIONS):
            if st.button(question, key=f"example_{index}", use_container_width=True):
                st.session_state.pending_question = question
                st.rerun()

    return {
        "api_base_url": api_base_url,
        "api_endpoint": api_endpoint,
        "session_id": session_id,
        "memory_mode": memory_mode,
        "structured_mode": structured_mode,
        "top_k": int(top_k),
        "return_sources": bool(return_sources),
        "timeout_seconds": float(timeout_seconds),
    }


def _render_message(message: dict[str, Any]) -> None:
    with st.chat_message(message["role"]):
        st.write(message["content"])
        if message["role"] == "assistant" and message.get("response"):
            response = message["response"]
            render_source_cards(response.get("sources") or [])
            render_memory_debug(response.get("memory_debug") or {})
            render_verifier_debug(response.get("verifier_debug") or {})
            render_debug_panel(message.get("payload") or {}, response)


def main() -> None:
    st.set_page_config(page_title=APP_TITLE, page_icon="▦", layout="wide")
    _initialize_state()
    controls = _render_sidebar()

    st.title(APP_TITLE)
    st.caption("Knowledge-base answers, source tracing, retrieval diagnostics, and session memory.")

    status_col, session_col, mode_col = st.columns(3)
    status_col.metric("API endpoint", controls["api_endpoint"])
    session_col.metric("Session", controls["session_id"])
    mode_col.metric(
        "Requested view",
        f"memory={controls['memory_mode']} · retrieval={controls['structured_mode']}",
    )

    for message in st.session_state.messages:
        _render_message(message)

    question = st.chat_input("输入知识库问题")
    if st.session_state.pending_question:
        question = st.session_state.pending_question
        st.session_state.pending_question = None

    if not question:
        return

    payload = {
        "query": question,
        "session_id": controls["session_id"] or None,
        "top_k": controls["top_k"],
        "return_sources": controls["return_sources"],
    }
    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.write(question)

    with st.chat_message("assistant"):
        try:
            with st.spinner("Agent 正在查询知识库…"):
                response = request_agent_api(
                    controls["api_base_url"],
                    controls["api_endpoint"],
                    payload,
                    controls["timeout_seconds"],
                )
            answer = response["answer"] or "Agent API 返回了空 answer。"
            st.write(answer)
            render_source_cards(response.get("sources") or [])
            render_memory_debug(response.get("memory_debug") or {})
            render_verifier_debug(response.get("verifier_debug") or {})
            render_debug_panel(payload, response)
            st.session_state.messages.append(
                {"role": "assistant", "content": answer, "payload": payload, "response": response}
            )
        except (ApiRequestError, ValueError) as exc:
            st.error(str(exc))
            st.caption("请确认 FastAPI 已启动、地址正确，并检查服务日志后重试。")
            st.session_state.messages.append(
                {"role": "assistant", "content": f"请求失败：{exc}", "payload": payload}
            )


if __name__ == "__main__":
    main()
