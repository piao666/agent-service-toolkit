from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

import streamlit as st

# ── Streamlit 状态 key ──
# advanced_debug_enabled 是持久业务状态，不直接绑定 checkbox widget。
# advanced_debug_toggle_widget 只是前端控件临时 key，非请求状态下同步到业务状态。
_ADVANCED_DEBUG_STATE_KEY = "advanced_debug_enabled"
_ADVANCED_DEBUG_WIDGET_KEY = "advanced_debug_toggle_widget"
_REQUEST_IN_FLIGHT_KEY = "enterprise_request_in_flight"
_PENDING_QUERY_KEY = "pending_enterprise_query"
_PENDING_PAYLOAD_KEY = "pending_enterprise_payload"
_PENDING_EXAMPLE_QUESTION_KEY = "pending_example_question"

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


def _stable_streamlit_key(*parts: object) -> str:
    raw = "::".join(str(p or "") for p in parts)
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
    return f"kb_{digest}"


def _clip_text(text: str | None, limit: int = 800) -> str:
    if not text:
        return ""
    text = str(text).strip()
    return text if len(text) <= limit else text[:limit] + "…"


def render_source_cards(
    sources: list[dict[str, Any]],
    *,
    message_index: int = 0,
    response_index: int = 0,
) -> None:
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
                preview_key = _stable_streamlit_key(
                    "source_preview", message_index, response_index, index,
                    source_id, _source_value(source, "chunk_id", ""),
                    _source_value(source, "doc_type", ""), preview[:32],
                )
                st.text_area("内容预览", value=preview, height=160, disabled=True, label_visibility="collapsed", key=preview_key)


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
        st.warning(
            "⚠️ 当前回答与已检索来源的逐词重合较低，"
            "建议展开来源核对；可能是资料不足、代码示例扩展或校验器保守导致。"
        )
    elif grounding_status == "medium":
        st.info("ℹ️ 当前回答有一定来源支撑，建议结合来源查看。")
    elif grounding_status == "high":
        st.success("✅ 当前回答与来源高度一致。")
    else:
        st.caption("证据验证未启用或未执行。")


def render_verifier_detail(verifier_debug: dict[str, Any]) -> None:
    safe = redact_for_display(verifier_debug or {})
    grounding_score = safe.get("grounding_score", 0.0)
    citation_coverage = bool(safe.get("citation_coverage"))
    safe_fallback_triggered = bool(safe.get("safe_fallback_triggered"))
    corpus_gap = bool(safe.get("corpus_gap_detected"))
    diagnosis = str(safe.get("diagnosis") or "")
    gate = str(safe.get("source_quality_gate") or "none")

    left, middle, right = st.columns(3)
    left.metric("证据得分", grounding_score)
    middle.metric("引用覆盖", "是" if citation_coverage else "否")
    right.metric("安全兜底", "已触发" if safe_fallback_triggered else "未触发")

    if gate != "none":
        st.caption(f"来源质量判定: {gate}")
    if corpus_gap:
        st.warning("⚠️ 检测到语料缺口: 知识库中可能缺少该主题的专题文档。")
    if diagnosis:
        st.caption(f"诊断: {diagnosis}")

    # V2 三级术语（默认折叠）
    critical_terms = safe.get("critical_terms") or []
    support_terms = safe.get("support_terms") or []
    example_terms = safe.get("example_terms") or []
    matched_critical = safe.get("matched_critical_terms") or []
    matched_support = safe.get("matched_support_terms") or []
    matched_example = safe.get("matched_example_terms") or []
    unsupported_critical = safe.get("unsupported_critical_terms") or []
    unsupported_support = safe.get("unsupported_support_terms") or []
    unsupported_example = safe.get("unsupported_example_terms") or []

    # 有 V2 字段时用三级展示
    if critical_terms or support_terms or example_terms:
        col_a, col_b = st.columns(2)
        with col_a:
            with st.expander(f"✅ 已匹配关键词 ({len(matched_critical)} 关键 / {len(matched_support)} 辅助 / {len(matched_example)} 示例)", expanded=False):
                if matched_critical:
                    st.caption("**关键术语**")
                    st.code(json.dumps(matched_critical, ensure_ascii=False, indent=2), language="json")
                if matched_support:
                    st.caption("**辅助术语**")
                    st.code(json.dumps(matched_support[:12], ensure_ascii=False, indent=2), language="json")
                    if len(matched_support) > 12:
                        st.caption(f"已省略 {len(matched_support) - 12} 个辅助术语。")
                if matched_example:
                    st.caption("**示例术语**")
                    st.code(json.dumps(matched_example, ensure_ascii=False, indent=2), language="json")
        with col_b:
            with st.expander(f"❌ 未匹配关键词 ({len(unsupported_critical)} 关键 / {len(unsupported_support)} 辅助 / {len(unsupported_example)} 示例)", expanded=False):
                if unsupported_critical:
                    st.caption("**关键术语**")
                    st.code(json.dumps(unsupported_critical, ensure_ascii=False, indent=2), language="json")
                if unsupported_support:
                    st.caption("**辅助术语**")
                    st.code(json.dumps(unsupported_support[:12], ensure_ascii=False, indent=2), language="json")
                    if len(unsupported_support) > 12:
                        st.caption(f"已省略 {len(unsupported_support) - 12} 个辅助术语。")
                if unsupported_example:
                    st.caption("**示例术语**")
                    st.code(json.dumps(unsupported_example, ensure_ascii=False, indent=2), language="json")
    else:
        # V1 回退（仍默认折叠）
        matched_terms = safe.get("matched_terms") or []
        unsupported_terms = safe.get("unsupported_terms") or []
        col_a, col_b = st.columns(2)
        with col_a:
            with st.expander(f"已匹配术语（{len(matched_terms)}）", expanded=False):
                st.code(json.dumps(matched_terms, ensure_ascii=False, indent=2), language="json")
        with col_b:
            with st.expander(f"未支持术语（{len(unsupported_terms)}）", expanded=False):
                st.code(json.dumps(unsupported_terms, ensure_ascii=False, indent=2), language="json")


def _new_session_id() -> str:
    return f"demo-{uuid.uuid4().hex[:12]}"


def _clear_pending_request_state() -> None:
    """清理 pending-query 状态，防止旧请求残留。"""
    st.session_state[_PENDING_QUERY_KEY] = ""
    st.session_state[_PENDING_PAYLOAD_KEY] = {}
    st.session_state[_REQUEST_IN_FLIGHT_KEY] = False
    st.session_state[_PENDING_EXAMPLE_QUESTION_KEY] = ""


def _start_new_session() -> None:
    """新建会话：重置 session_id、清空 messages 和 pending 状态。
    不重置高级调试开关（用户显示偏好）。"""
    st.session_state["session_id"] = _new_session_id()
    st.session_state["messages"] = []
    _clear_pending_request_state()


def _clear_chat_messages() -> None:
    """清空对话：仅清除前端消息和 pending 状态。"""
    st.session_state["messages"] = []
    _clear_pending_request_state()

def _ensure_advanced_debug_widget_state() -> None:
    """仅在 checkbox 真正渲染前，用持久状态初始化 widget 临时状态。"""
    if _ADVANCED_DEBUG_WIDGET_KEY not in st.session_state:
        st.session_state[_ADVANCED_DEBUG_WIDGET_KEY] = bool(
            st.session_state.get(_ADVANCED_DEBUG_STATE_KEY, False)
        )


def _sync_advanced_debug_from_widget() -> None:
    """用户点击 checkbox 后，将 widget 临时状态同步到持久业务状态。"""
    st.session_state[_ADVANCED_DEBUG_STATE_KEY] = bool(
        st.session_state.get(_ADVANCED_DEBUG_WIDGET_KEY, False)
    )


def _capture_advanced_debug_widget_state() -> None:
    """提交问题前捕获当前 checkbox 状态，防止请求 rerun 期间丢失显示偏好。"""
    if _ADVANCED_DEBUG_WIDGET_KEY in st.session_state:
        st.session_state[_ADVANCED_DEBUG_STATE_KEY] = bool(
            st.session_state.get(_ADVANCED_DEBUG_WIDGET_KEY, False)
        )

def _initialize_state() -> None:
    st.session_state.setdefault("messages", [])
    st.session_state.setdefault("session_id", _new_session_id())
    # 持久业务状态（不随 widget rerun 丢失）
    st.session_state.setdefault(_ADVANCED_DEBUG_STATE_KEY, False)
    st.session_state.setdefault(_REQUEST_IN_FLIGHT_KEY, False)
    st.session_state.setdefault(_PENDING_QUERY_KEY, "")
    st.session_state.setdefault(_PENDING_PAYLOAD_KEY, {})
    st.session_state.setdefault(_PENDING_EXAMPLE_QUESTION_KEY, "")

def _inject_page_styles() -> None:
    """注入页面级样式：隐藏 Streamlit 框架菜单，并优化首页欢迎区。"""
    st.markdown(
        """
        <style>
        /* 尽量隐藏 Streamlit 右上角框架菜单、Deploy、顶部工具栏、页脚 */
        #MainMenu {
            visibility: hidden;
        }

        header[data-testid="stHeader"] {
            display: none;
        }

        div[data-testid="stToolbar"] {
            display: none;
        }

        div[data-testid="stDecoration"] {
            display: none;
        }

        footer {
            visibility: hidden;
        }

        /* 主内容区：保留宽屏，但减少顶部工程感 */
        .block-container {
            padding-top: 3.2rem;
            padding-bottom: 6rem;
            max-width: 1280px;
        }

        /* 首页欢迎语：参考聊天产品的开场提示，不显示工程接口与会话信息 */
        .enterprise-kb-welcome {
            max-width: 880px;
            margin: 5.8rem auto 0 auto;
            display: flex;
            align-items: flex-start;
            gap: 14px;
            color: #F8FAFC;
        }

        .enterprise-kb-welcome-icon {
            width: 38px;
            height: 38px;
            min-width: 38px;
            border-radius: 12px;
            background: linear-gradient(135deg, #F59E0B, #F97316);
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 19px;
            box-shadow: 0 8px 24px rgba(249, 115, 22, 0.22);
        }

        .enterprise-kb-welcome-copy {
            padding-top: 2px;
        }

        .enterprise-kb-welcome-title {
            font-size: 18px;
            font-weight: 700;
            line-height: 1.7;
            letter-spacing: 0.01em;
        }

        .enterprise-kb-welcome-subtitle {
            margin-top: 4px;
            font-size: 13px;
            line-height: 1.7;
            color: rgba(248, 250, 252, 0.62);
        }

        /* 底部输入框宽度与主问答区对齐 */
        div[data-testid="stChatInput"] {
            max-width: 1180px;
            margin-left: auto;
            margin-right: auto;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _render_welcome_message() -> None:
    """渲染首页中文欢迎语。仅在没有历史消息时展示。"""
    st.markdown(
        """
        <div class="enterprise-kb-welcome">
            <div class="enterprise-kb-welcome-icon">🤖</div>
            <div class="enterprise-kb-welcome-copy">
                <div class="enterprise-kb-welcome-title">
                    我是企业知识库问答助手，会基于内部技术资料为你检索答案，并提供可追踪的来源依据。
                </div>
                <div class="enterprise-kb-welcome-subtitle">
                    你可以询问 RAG、FastAPI、LLM、Python、机器学习、深度学习等知识库已收录的技术问题。
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

def _render_sidebar() -> dict[str, Any]:
    request_in_flight = bool(st.session_state.get(_REQUEST_IN_FLIGHT_KEY, False))

    with st.sidebar:
        st.title("企业知识库问答")
        api_base_url = st.text_input("后端服务地址", value=DEFAULT_API_BASE_URL)
        api_endpoint = st.text_input("接口路径", value=DEFAULT_API_ENDPOINT)
        # session_id 使用只读展示，避免 widget key 与业务状态冲突
        session_id = str(st.session_state.get("session_id") or "")
        st.caption("会话 ID")
        st.code(session_id, language=None)

        col1, col2 = st.columns(2)
        if col1.button(
            "新建会话",
            use_container_width=True,
            help="生成新 session ID",
            disabled=request_in_flight,
        ):
            _start_new_session()
            st.rerun()
        if col2.button(
            "清空对话",
            use_container_width=True,
            disabled=request_in_flight,
        ):
            _clear_chat_messages()
            st.rerun()
        st.caption("新建会话会用新的 memory 隔离键；清空对话仅清除前端消息。")

        if st.button(
            "检查后端状态",
            use_container_width=True,
            disabled=request_in_flight,
        ):
            try:
                check_api_health(api_base_url)
                st.success("后端服务正常")
            except Exception:
                st.error("后端服务不可用，请先启动 FastAPI。")

        st.subheader("示例问题")
        for index, question in enumerate(EXAMPLE_QUESTIONS):
            if st.button(
                question,
                key=f"example_{index}",
                use_container_width=True,
                disabled=request_in_flight,
            ):
                st.session_state[_PENDING_EXAMPLE_QUESTION_KEY] = question
                st.rerun()

        # 高级调试显示偏好：
        # 请求中不渲染绑定状态的 checkbox，避免 Streamlit disabled widget 覆盖持久状态。
        if request_in_flight:
            debug_enabled = bool(st.session_state.get(_ADVANCED_DEBUG_STATE_KEY, False))
            st.caption(
                f"显示高级调试信息：{'已开启' if debug_enabled else '已关闭'}（请求中暂不可切换）"
            )
        else:
            _ensure_advanced_debug_widget_state()
            st.checkbox(
                "显示高级调试信息",
                key=_ADVANCED_DEBUG_WIDGET_KEY,
                on_change=_sync_advanced_debug_from_widget,
            )

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


def _render_message(message: dict[str, Any], message_index: int = 0) -> None:
    # 读取持久业务状态（非 widget key），不受 widget rerun 影响
    show_advanced = bool(st.session_state.get(_ADVANCED_DEBUG_STATE_KEY, False))
    with st.chat_message(message["role"]):
        st.write(message["content"])
        if message["role"] == "assistant" and message.get("response"):
            response = message["response"]
            with st.expander("来源依据", expanded=False):
                render_source_cards(response.get("sources") or [], message_index=message_index, response_index=message_index)
            render_verifier_debug(response.get("verifier_debug") or {})
            if show_advanced:
                render_memory_debug(response.get("memory_debug") or {})
                render_verifier_detail(response.get("verifier_debug") or {})
                _render_debug_panel(message.get("payload") or {}, response)

def _compact_debug_table(rows: list[dict[str, Any]]) -> None:
    """以两列表格展示紧凑调试信息。"""
    if not rows:
        st.caption("暂无摘要信息。")
        return
    st.dataframe(rows, hide_index=True, use_container_width=True)


def _join_debug_list(value: Any, limit: int = 6) -> str:
    """将调试字段里的 list 压缩成短文本。"""
    if not isinstance(value, list):
        return str(value or "-")
    clipped = value[:limit]
    suffix = "" if len(value) <= limit else f" … 共 {len(value)} 项"
    return " → ".join(str(item) for item in clipped) + suffix


def _render_retrieval_debug_summary(retrieval_debug: dict[str, Any]) -> None:
    """只展示检索诊断里最关键的字段。"""
    if not retrieval_debug:
        st.caption("未返回检索诊断。")
        return

    safe = redact_for_display(retrieval_debug)

    rows = [
        {"字段": "原始问题", "值": safe.get("original_query", "-")},
        {"字段": "改写后问题", "值": safe.get("rewritten_query", "-")},
        {"字段": "命中数量", "值": f"{safe.get('hit_count', '-')} / top_k={safe.get('top_k', '-')}" },
        {"字段": "向量库", "值": f"{safe.get('vector_store', '-')} · {safe.get('collection', '-')}" },
        {"字段": "Embedding", "值": safe.get("embedding_provider", "-")},
        {"字段": "检索策略", "值": safe.get("selected_policy", safe.get("policy_mode", "-"))},
        {"字段": "Overlay", "值": f"{safe.get('overlay_type', '-')}｜{safe.get('overlay_reason', '-')}" },
        {"字段": "候选池", "值": f"candidate_pool={safe.get('candidate_pool_k', '-')}，baseline={safe.get('baseline_result_count', '-')}" },
    ]
    _compact_debug_table(rows)

    source_ids = safe.get("final_source_id_sequence") or []
    chunk_ids = safe.get("final_chunk_id_sequence") or []
    doc_types = safe.get("final_doc_type_sequence") or []

    source_rows = []
    max_len = max(len(source_ids), len(chunk_ids), len(doc_types))
    for i in range(max_len):
        source_rows.append({
            "序号": i + 1,
            "source_id": source_ids[i] if i < len(source_ids) else "-",
            "chunk_id": chunk_ids[i] if i < len(chunk_ids) else "-",
            "doc_type": doc_types[i] if i < len(doc_types) else "-",
        })

    if source_rows:
        st.caption("最终命中的来源顺序")
        st.dataframe(source_rows, hide_index=True, use_container_width=True)


def _render_graph_debug_summary(graph_debug: dict[str, Any]) -> None:
    """只展示图执行追踪里的主链路信息。"""
    if not graph_debug:
        st.caption("未返回图执行追踪。")
        return

    safe = redact_for_display(graph_debug)
    planner = safe.get("planner") if isinstance(safe.get("planner"), dict) else {}
    judge = safe.get("judge") if isinstance(safe.get("judge"), dict) else {}

    rows = [
        {"字段": "Graph 模式", "值": safe.get("graph_mode", "-")},
        {"字段": "执行路由", "值": safe.get("route", "-")},
        {"字段": "节点链路", "值": _join_debug_list(safe.get("nodes_executed"), limit=10)},
        {"字段": "是否调用真实 LLM", "值": safe.get("calls_real_llm", safe.get("calls_llm", "-"))},
        {"字段": "是否写入 Chroma", "值": safe.get("writes_chroma", "-")},
        {"字段": "Planner 模式", "值": planner.get("planner_mode", "-")},
        {"字段": "Planner 类型", "值": planner.get("planner_type", "-")},
        {"字段": "是否 Multi-hop", "值": planner.get("requires_multi_hop", "-")},
        {"字段": "Judge 结论", "值": judge.get("verdict", "-")},
        {"字段": "Judge 分数", "值": judge.get("score", "-")},
    ]
    _compact_debug_table(rows)


def _render_memory_debug_summary(memory_debug: dict[str, Any]) -> None:
    """只展示会话记忆摘要，不再重复输出完整 JSON。"""
    if not memory_debug:
        st.caption("未返回会话记忆。")
        return

    safe = redact_for_display(memory_debug)
    rows = [
        {"字段": "记忆模式", "值": safe.get("memory_mode", "-")},
        {"字段": "是否追问", "值": safe.get("is_follow_up", "-")},
        {"字段": "原始问题", "值": safe.get("original_query", "-")},
        {"字段": "改写后问题", "值": safe.get("contextual_query", "-")},
        {"字段": "改写策略", "值": safe.get("memory_rewrite_strategy", "-")},
        {"字段": "是否用于检索", "值": safe.get("memory_used_for_retrieval", "-")},
        {"字段": "本轮前对话数", "值": safe.get("memory_turn_count_before", "-")},
        {"字段": "本轮后对话数", "值": safe.get("memory_turn_count_after", "-")},
    ]
    _compact_debug_table(rows)


def _render_request_summary(payload: dict[str, Any]) -> None:
    """只展示最关键请求参数。"""
    safe = redact_for_display(payload or {})
    rows = [
        {"字段": "query", "值": safe.get("query", "-")},
        {"字段": "session_id", "值": safe.get("session_id", "-")},
        {"字段": "top_k", "值": safe.get("top_k", "-")},
        {"字段": "return_sources", "值": safe.get("return_sources", "-")},
    ]
    _compact_debug_table(rows)


def _render_raw_response_summary(response: dict[str, Any]) -> None:
    """原始响应默认只给结构摘要，完整 JSON 放到最后的开发者排错区。"""
    safe = redact_for_display(response or {})
    sources = safe.get("sources") or []
    retrieval_debug = safe.get("retrieval_debug") or {}
    verifier_debug = safe.get("verifier_debug") or {}
    judge_debug = safe.get("judge_debug") or {}
    graph_debug = safe.get("graph_debug") or {}

    rows = [
        {"字段": "answer 字符数", "值": len(str(safe.get("answer") or ""))},
        {"字段": "sources 数量", "值": len(sources) if isinstance(sources, list) else 0},
        {"字段": "latency_ms", "值": safe.get("latency_ms", "-")},
        {"字段": "grounding_status", "值": verifier_debug.get("grounding_status", "-") if isinstance(verifier_debug, dict) else "-"},
        {"字段": "grounding_score", "值": verifier_debug.get("grounding_score", "-") if isinstance(verifier_debug, dict) else "-"},
        {"字段": "source_quality_gate", "值": verifier_debug.get("source_quality_gate", "-") if isinstance(verifier_debug, dict) else "-"},
        {"字段": "corpus_gap", "值": verifier_debug.get("corpus_gap_detected", "-") if isinstance(verifier_debug, dict) else "-"},
        {"字段": "judge_verdict", "值": judge_debug.get("verdict", "-") if isinstance(judge_debug, dict) else "-"},
        {"字段": "graph_mode", "值": graph_debug.get("graph_mode", "-") if isinstance(graph_debug, dict) else "-"},
        {"字段": "retrieval_policy", "值": retrieval_debug.get("selected_policy", "-") if isinstance(retrieval_debug, dict) else "-"},
    ]
    _compact_debug_table(rows)

def _render_debug_panel(payload: dict[str, Any], response: dict[str, Any]) -> None:
    st.subheader("高级调试信息")

    with st.expander("检索摘要", expanded=False):
        _render_retrieval_debug_summary(response.get("retrieval_debug") or {})

    with st.expander("图执行摘要", expanded=False):
        _render_graph_debug_summary(response.get("graph_debug") or {})

    with st.expander("会话记忆摘要", expanded=False):
        _render_memory_debug_summary(response.get("memory_debug") or {})

    with st.expander("请求摘要", expanded=False):
        _render_request_summary(payload)

    with st.expander("响应结构摘要", expanded=False):
        _render_raw_response_summary(response)

    with st.expander("开发者原始 JSON（仅排错使用）", expanded=False):
        st.caption("这里保留完整原始响应，默认折叠。普通演示时不建议展开。")
        st.json(redact_for_display(response))


def main() -> None:
    st.set_page_config(
        page_title=APP_TITLE,
        page_icon="📚",
        layout="wide",
        menu_items={
            "About": "企业知识库问答系统：基于内部技术资料进行 RAG 检索、来源追踪与证据校验。"
        },
    )
    _inject_page_styles()
    _initialize_state()
    controls = _render_sidebar()

    if not st.session_state.messages:
        _render_welcome_message()

    request_in_flight = bool(st.session_state.get(_REQUEST_IN_FLIGHT_KEY, False))

    # ── 渲染已有 messages ──
    for message_index, message in enumerate(st.session_state.messages):
        _render_message(message, message_index=message_index)

    # ── 阶段 B: 如果存在 pending query，执行 API（此时所有控件已 disabled）──
    pending_query = st.session_state.get(_PENDING_QUERY_KEY, "")
    if pending_query and request_in_flight:
        pending_payload = dict(st.session_state.get(_PENDING_PAYLOAD_KEY) or {})
        try:
            with st.spinner("正在检索知识库并生成回答…"):
                response = request_agent_api(
                    controls["api_base_url"],
                    controls["api_endpoint"],
                    pending_payload,
                    controls["timeout_seconds"],
                )
            answer = response.get("answer") or "后端返回了空回答。"
            st.session_state.messages.append({
                "role": "assistant",
                "content": answer,
                "payload": pending_payload,
                "response": response,
            })
        except (ApiRequestError, ValueError) as exc:
            st.session_state.messages.append({
                "role": "assistant",
                "content": f"请求失败：{exc}",
                "payload": pending_payload,
                "response": {"answer": f"请求失败：{exc}", "error": str(exc)},
            })
        finally:
            st.session_state[_PENDING_QUERY_KEY] = ""
            st.session_state[_PENDING_PAYLOAD_KEY] = {}
            st.session_state[_REQUEST_IN_FLIGHT_KEY] = False
            st.rerun()

    # ── 阶段 A: 接受用户输入（请求期间 chat_input disabled）──
    question = st.chat_input(
        "输入知识库问题",
        disabled=request_in_flight,
    )
    if st.session_state.get(_PENDING_EXAMPLE_QUESTION_KEY):
        question = str(st.session_state.get(_PENDING_EXAMPLE_QUESTION_KEY) or "")
        st.session_state[_PENDING_EXAMPLE_QUESTION_KEY] = ""

    if not question:
        return

    # 提交请求前捕获当前高级调试偏好。
    _capture_advanced_debug_widget_state()

    # 保存 payload（此时 controls 已就绪），切换到 pending-query 流程
    payload = {
        "query": question,
        "session_id": controls["session_id"] or None,
        "top_k": controls["top_k"],
        "return_sources": True,
    }

    st.session_state.messages.append({"role": "user", "content": question})
    st.session_state[_PENDING_QUERY_KEY] = question
    st.session_state[_PENDING_PAYLOAD_KEY] = payload
    st.session_state[_REQUEST_IN_FLIGHT_KEY] = True
    st.rerun()


if __name__ == "__main__":
    main()
