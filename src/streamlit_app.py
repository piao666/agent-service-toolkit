from __future__ import annotations

import json
import os
import re
import uuid
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

import streamlit as st

APP_TITLE = "企业知识库 Agent 控制台"
DEFAULT_API_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_API_ENDPOINT = "/enterprise/agent/query"
EXAMPLE_QUESTIONS = (
    "RAG 是什么？",
    "它有什么局限？",
    "那它适合什么场景？",
    "FastAPI 的 Request Body 如何定义？",
    "LoRA 有什么作用？",
    "这个系统是如何进行检索的？",
)
MEMORY_DEBUG_FIELDS_CN = {
    "memory_mode": "记忆模式",
    "memory_enabled": "是否启用",
    "session_id": "会话 ID",
    "memory_turn_count_before": "本轮前对话数",
    "memory_turn_count_after": "本轮后对话数",
    "is_follow_up": "是否追问",
    "original_query": "原始问题",
    "contextual_query": "改写后问题",
    "memory_rewrite_strategy": "改写策略",
    "memory_used_for_retrieval": "是否用于检索",
}
SENSITIVE_KEY_PARTS = ("api_key", "authorization", "credential", "password", "secret", "token")
WINDOWS_PATH_PATTERN = re.compile(r"\b[A-Za-z]:[\\/][^\s\"']+")
BEARER_PATTERN = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9_.-]+")
SECRET_PATTERN = re.compile(r"\bsk-[A-Za-z0-9_-]{12,}")


class ApiRequestError(RuntimeError):
    """A user-facing API connection or response error."""


def normalize_base_url(base_url: str) -> str:
    normalized = base_url.strip().rstrip("/")
    parsed = urlparse(normalized)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("API Base URL 必须是有效的 http:// 或 https:// 地址。")
    return normalized


def build_api_url(base_url: str, endpoint: str) -> str:
    normalized_base = normalize_base_url(base_url)
    normalized_endpoint = "/" + endpoint.strip().lstrip("/")
    return urljoin(normalized_base + "/", normalized_endpoint.lstrip("/"))


def _request_json(
    url: str, *, timeout_seconds: float, payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = Request(url, data=data, headers={"Accept": "application/json", "Content-Type": "application/json"}, method="POST" if payload else "GET")
    try:
        with urlopen(req, timeout=timeout_seconds) as resp:
            body = resp.read().decode("utf-8")
    except HTTPError as exc:
        raise ApiRequestError(f"后端返回 HTTP {exc.code}，请检查服务日志。") from exc
    except URLError as exc:
        raise ApiRequestError("未连接到后端服务，请先启动 FastAPI。") from exc
    except TimeoutError as exc:
        raise ApiRequestError("请求超时，请稍后重试。") from exc
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ApiRequestError("后端返回了无效 JSON。") from exc
    if not isinstance(parsed, dict):
        raise ApiRequestError("response schema 不完整。")
    return parsed


def request_agent_api(base_url: str, endpoint: str, payload: dict[str, Any], timeout_seconds: float) -> dict[str, Any]:
    response = _request_json(build_api_url(base_url, endpoint), timeout_seconds=timeout_seconds, payload=payload)
    if not isinstance(response.get("answer"), str):
        raise ApiRequestError("response 缺少 answer 字段。")
    return response


def check_api_health(base_url: str, timeout_seconds: float = 5.0) -> dict[str, Any]:
    return _request_json(build_api_url(base_url, "/health"), timeout_seconds=timeout_seconds)


def redact_for_display(value: Any, key: str = "") -> Any:
    lowered_key = key.lower()
    if any(part in lowered_key for part in SENSITIVE_KEY_PARTS):
        return "<REDACTED>"
    if lowered_key in {"persist_dir", "model_path", "local_path"}:
        return "<LOCAL_PATH>"
    if isinstance(value, dict):
        return {k: redact_for_display(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_for_display(v, key) for v in value]
    if isinstance(value, str):
        value = WINDOWS_PATH_PATTERN.sub("<LOCAL_PATH>", value)
        value = BEARER_PATTERN.sub("Bearer <REDACTED>", value)
        return SECRET_PATTERN.sub("<REDACTED>", value)
    return value


def _source_value(source: dict[str, Any], field: str, default: Any = "-") -> Any:
    metadata = source.get("metadata") if isinstance(source.get("metadata"), dict) else {}
    value = source.get(field)
    if value in (None, "", "unknown"):
        value = metadata.get(field)
    return default if value in (None, "") else value


def _clip_text(text: str | None, limit: int = 800) -> str:
    if not text:
        return ""
    text = str(text).strip()
    return text if len(text) <= limit else text[:limit] + "…"


def render_source_cards(sources: list[dict[str, Any]]) -> None:
    if not sources:
        st.caption("本轮未返回来源依据。")
        return
    for index, raw_source in enumerate(sources, start=1):
        source = redact_for_display(raw_source)
        title = str(_source_value(source, "title", f"来源 {index}"))
        source_id = str(_source_value(source, "source_id"))
        with st.expander(f"{index}. {title} · {source_id}", expanded=False):
            left, right = st.columns(2)
            left.markdown(f"**文档类型:** `{_source_value(source, 'doc_type')}`")
            left.markdown(f"**章节:** `{_source_value(source, 'section_path')}`")
            right.markdown(f"**Chunk ID:** `{_source_value(source, 'chunk_id')}`")
            score = _source_value(source, "relevance_score", _source_value(source, "score"))
            right.markdown(f"**相关度:** `{score}`")
            source_url = str(_source_value(source, "source_url", ""))
            if source_url and urlparse(source_url).scheme in {"http", "https"}:
                st.markdown(f"[打开来源页面]({source_url})")
            preview = _clip_text(str(_source_value(source, "content_preview", "")))
            if preview:
                st.caption("内容预览")
                st.text_area("内容预览", value=preview, height=160, disabled=True, label_visibility="collapsed")


def render_memory_debug(memory_debug: dict[str, Any]) -> None:
    if not memory_debug:
        return
    safe = redact_for_display(memory_debug)
    if not safe.get("memory_enabled"):
        return
    original = str(safe.get("original_query") or "")
    contextual = str(safe.get("contextual_query") or "")
    if safe.get("is_follow_up") and contextual and contextual != original:
        st.info(f"追问改写: {original} → {contextual}")
    rows = [{"字段": MEMORY_DEBUG_FIELDS_CN.get(field, field), "值": safe.get(field)} for field in MEMORY_DEBUG_FIELDS_CN]
    st.dataframe(rows, hide_index=True, use_container_width=True)


def render_verifier_debug(verifier_debug: dict[str, Any]) -> None:
    if not verifier_debug:
        return
    safe = redact_for_display(verifier_debug)
    grounding_status = str(safe.get("grounding_status") or "not_checked")
    if grounding_status == "low":
        st.warning("⚠️ 当前回答缺少充分来源支持，建议补充知识库资料或扩大检索范围。")
    elif grounding_status == "medium":
        st.info("⚠️ 证据支持一般，建议结合来源依据查看。")
    elif grounding_status == "high":
        st.success("✅ 证据支持充分")
    else:
        st.caption("证据验证未启用或未执行。")


def render_verifier_detail(verifier_debug: dict[str, Any]) -> None:
    safe = redact_for_display(verifier_debug or {})
    grounding_score = safe.get("grounding_score", 0.0)
    citation_coverage = bool(safe.get("citation_coverage"))
    safe_fallback_triggered = bool(safe.get("safe_fallback_triggered"))
    left, middle, right = st.columns(3)
    left.metric("证据得分", grounding_score)
    middle.metric("引用覆盖", "是" if citation_coverage else "否")
    right.metric("安全兜底", "已触发" if safe_fallback_triggered else "未触发")
    st.markdown("**已匹配术语**")
    st.write(safe.get("matched_terms") or [])
    st.markdown("**未支持术语**")
    st.write(safe.get("unsupported_terms") or [])


def _new_session_id() -> str:
    return f"demo-{uuid.uuid4().hex[:12]}"


def _initialize_state() -> None:
    st.session_state.setdefault("messages", [])
    st.session_state.setdefault("session_id", _new_session_id())


def _render_sidebar() -> dict[str, Any]:
    with st.sidebar:
        st.title("企业知识库问答")
        st.caption("基于企业知识库的 RAG 问答演示")
        api_base_url = st.text_input("后端服务地址", value=DEFAULT_API_BASE_URL)
        api_endpoint = st.text_input("接口路径", value=DEFAULT_API_ENDPOINT)
        session_id = st.text_input("会话 ID", key="session_id")

        col1, col2 = st.columns(2)
        if col1.button("新建会话", use_container_width=True, help="生成新 session ID"):
            st.session_state.session_id = _new_session_id()
            st.session_state.messages = []
            st.rerun()
        if col2.button("清空对话", use_container_width=True):
            st.session_state.messages = []
            st.rerun()
        st.caption("新建会话会用新的 memory 隔离键；清空对话仅清除前端消息。")

        if st.button("检查后端状态", use_container_width=True):
            try:
                health = check_api_health(api_base_url)
                st.success("后端服务正常")
            except Exception:
                st.error("后端服务不可用，请先启动 FastAPI。")

        st.subheader("示例问题")
        for index, question in enumerate(EXAMPLE_QUESTIONS):
            if st.button(question, key=f"example_{index}", use_container_width=True):
                st.session_state.pending_question = question
                st.rerun()

        st.session_state.show_advanced = st.checkbox("显示高级调试信息", value=False)

    top_k = int(os.getenv("RAG_DEFAULT_TOP_K", "5"))
    try:
        top_k = int(os.getenv("RAG_DEFAULT_TOP_K", "5"))
    except ValueError:
        top_k = 5
    timeout_seconds = 120
    try:
        timeout_seconds = int(os.getenv("STREAMLIT_API_TIMEOUT_SECONDS", "120"))
    except ValueError:
        timeout_seconds = 120

    return {
        "api_base_url": api_base_url,
        "api_endpoint": api_endpoint,
        "session_id": session_id,
        "top_k": top_k,
        "return_sources": True,
        "timeout_seconds": float(timeout_seconds),
    }


def _render_message(message: dict[str, Any], show_advanced: bool) -> None:
    with st.chat_message(message["role"]):
        st.write(message["content"])
        if message["role"] == "assistant" and message.get("response"):
            response = message["response"]
            with st.expander("来源依据", expanded=False):
                render_source_cards(response.get("sources") or [])
            render_verifier_debug(response.get("verifier_debug") or {})
            if show_advanced:
                render_memory_debug(response.get("memory_debug") or {})
                render_verifier_detail(response.get("verifier_debug") or {})
                _render_debug_panel(message.get("payload") or {}, response)


def _render_debug_panel(payload: dict[str, Any], response: dict[str, Any]) -> None:
    st.subheader("高级调试信息")
    with st.expander("检索诊断", expanded=False):
        rd = response.get("retrieval_debug")
        if rd:
            st.json(redact_for_display(rd))
        else:
            st.caption("未返回检索诊断。")
    with st.expander("图执行追踪", expanded=False):
        gd = response.get("graph_debug")
        if gd:
            st.json(redact_for_display(gd))
        else:
            st.caption("未返回图执行追踪（legacy 模式下该字段为空）。")
    with st.expander("会话记忆", expanded=False):
        md = response.get("memory_debug")
        if md:
            render_memory_debug(md)
            st.json(redact_for_display(md))
        else:
            st.caption("未返回会话记忆。")
    with st.expander("请求参数", expanded=False):
        st.json(redact_for_display(payload))
    with st.expander("原始响应", expanded=False):
        st.json(redact_for_display(response))


def main() -> None:
    st.set_page_config(page_title=APP_TITLE, page_icon="▦", layout="wide")
    _initialize_state()
    controls = _render_sidebar()

    st.title(APP_TITLE)
    st.caption("面向企业内部知识资料的 RAG 问答、来源追踪与调试演示。")
    st.caption(f"接口：{controls['api_endpoint']} ｜ 会话：{controls['session_id']}")

    show_advanced = st.session_state.get("show_advanced", False)

    for message in st.session_state.messages:
        _render_message(message, show_advanced)

    question = st.chat_input("输入知识库问题")
    if st.session_state.get("pending_question"):
        question = st.session_state.pending_question
        st.session_state.pending_question = None

    if not question:
        return

    payload = {
        "query": question,
        "session_id": controls["session_id"] or None,
        "top_k": controls["top_k"],
        "return_sources": True,
    }
    st.session_state.messages.append({"role": "user", "content": question})
    with st.chat_message("user"):
        st.write(question)

    with st.chat_message("assistant"):
        try:
            with st.spinner("正在查询知识库…"):
                response = request_agent_api(controls["api_base_url"], controls["api_endpoint"], payload, controls["timeout_seconds"])
            answer = response["answer"] or "后端返回了空回答。"
            st.write(answer)
            with st.expander("来源依据", expanded=False):
                render_source_cards(response.get("sources") or [])
            render_verifier_debug(response.get("verifier_debug") or {})
            if show_advanced:
                render_memory_debug(response.get("memory_debug") or {})
                render_verifier_detail(response.get("verifier_debug") or {})
                _render_debug_panel(payload, response)
            st.session_state.messages.append({"role": "assistant", "content": answer, "payload": payload, "response": response})
        except (ApiRequestError, ValueError) as exc:
            st.error(str(exc))
            st.caption("请确认 FastAPI 已启动、地址正确，并检查服务日志后重试。")
            st.session_state.messages.append({"role": "assistant", "content": f"请求失败：{exc}", "payload": payload})


if __name__ == "__main__":
    main()
