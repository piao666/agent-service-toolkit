from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import RLock
from typing import Any

DEFAULT_MAX_TURNS = 5
DEFAULT_MAX_ANSWER_CHARS = 1000
MAX_CONTEXT_CHARS = 2400

_FOLLOW_UP_PATTERNS = (
    "它",
    "这个",
    "上面",
    "刚才",
    "前面",
    "继续",
    "还有什么",
    "有什么局限",
    "优缺点",
    "原理",
    "怎么用",
    "why",
    "how",
    "it",
    "its",
    "this",
    "that",
    "limitation",
    "limitations",
    "drawback",
    "drawbacks",
)


@dataclass(frozen=True, slots=True)
class ConversationTurn:
    user_query: str
    assistant_answer: str
    sources: tuple[dict[str, str], ...]
    timestamp: str

    @property
    def source_ids(self) -> list[str]:
        return [source["source_id"] for source in self.sources if source.get("source_id")]

    @property
    def titles(self) -> list[str]:
        return [source["title"] for source in self.sources if source.get("title")]


class ConversationMemoryStore:
    """Bounded, process-local conversation memory isolated by session ID."""

    def __init__(
        self,
        max_turns: int = DEFAULT_MAX_TURNS,
        max_answer_chars: int = DEFAULT_MAX_ANSWER_CHARS,
    ) -> None:
        self.max_turns = max(1, int(max_turns))
        self.max_answer_chars = max(1, int(max_answer_chars))
        self._sessions: dict[str, list[ConversationTurn]] = {}
        self._lock = RLock()

    def append_turn(
        self,
        session_id: str | None,
        user_query: str,
        assistant_answer: str,
        sources: list[dict[str, Any]] | None = None,
    ) -> ConversationTurn | None:
        normalized_session = _normalize_session_id(session_id)
        normalized_query = _normalize_text(user_query)
        if not normalized_session or not normalized_query:
            return None

        turn = ConversationTurn(
            user_query=normalized_query,
            assistant_answer=_clip_text(assistant_answer, self.max_answer_chars),
            sources=tuple(_summarize_sources(sources or [])),
            timestamp=datetime.now(UTC).isoformat(),
        )
        with self._lock:
            turns = self._sessions.setdefault(normalized_session, [])
            turns.append(turn)
            if len(turns) > self.max_turns:
                del turns[: len(turns) - self.max_turns]
        return turn

    def get_recent_turns(
        self,
        session_id: str | None,
        limit: int | None = None,
    ) -> list[ConversationTurn]:
        normalized_session = _normalize_session_id(session_id)
        if not normalized_session:
            return []
        with self._lock:
            turns = list(self._sessions.get(normalized_session, []))
        if limit is None:
            return turns
        return turns[-max(0, int(limit)) :] if limit > 0 else []

    def get_recent_context(self, session_id: str | None) -> str:
        blocks: list[str] = []
        for index, turn in enumerate(self.get_recent_turns(session_id), start=1):
            titles = ", ".join(turn.titles[:3])
            block = f"Turn {index}\nUser: {turn.user_query}\nAssistant: {turn.assistant_answer}"
            if titles:
                block += f"\nSource titles: {titles}"
            blocks.append(block)
        return _clip_text("\n\n".join(blocks), MAX_CONTEXT_CHARS)

    def clear_session(self, session_id: str | None) -> bool:
        normalized_session = _normalize_session_id(session_id)
        if not normalized_session:
            return False
        with self._lock:
            return self._sessions.pop(normalized_session, None) is not None

    def get_turn_count(self, session_id: str | None) -> int:
        normalized_session = _normalize_session_id(session_id)
        if not normalized_session:
            return 0
        with self._lock:
            return len(self._sessions.get(normalized_session, []))


def _normalize_session_id(session_id: str | None) -> str:
    return str(session_id or "").strip()


def _normalize_text(text: str) -> str:
    return " ".join(str(text or "").split())


def _clip_text(text: str, limit: int) -> str:
    normalized = _normalize_text(text)
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3] + "..."


def _summarize_sources(sources: list[dict[str, Any]]) -> list[dict[str, str]]:
    summaries: list[dict[str, str]] = []
    for source in sources:
        metadata = source.get("metadata") if isinstance(source.get("metadata"), dict) else {}
        source_id = metadata.get("source_id") or source.get("source_id")
        summaries.append(
            {
                "source_id": _clip_text(str(source_id or ""), 160),
                "title": _clip_text(str(source.get("title") or metadata.get("title") or ""), 240),
                "chunk_id": _clip_text(
                    str(source.get("chunk_id") or metadata.get("chunk_id") or ""), 160
                ),
                "source_url": _clip_text(
                    str(source.get("source_url") or metadata.get("source_url") or ""), 500
                ),
            }
        )
    return summaries


def is_follow_up_query(query: str) -> bool:
    normalized = _normalize_text(query).lower()
    if not normalized:
        return False
    return any(_contains_follow_up_pattern(normalized, pattern) for pattern in _FOLLOW_UP_PATTERNS)


def _contains_follow_up_pattern(query: str, pattern: str) -> bool:
    if pattern.isascii() and pattern.isalpha():
        return re.search(rf"\b{re.escape(pattern)}\b", query, flags=re.IGNORECASE) is not None
    return pattern in query


def _extract_topic(turn: ConversationTurn) -> str:
    query = _normalize_text(turn.user_query).strip(" ?!。？！")
    query = re.sub(r"^(请介绍|请解释|请说明|什么是)\s*", "", query)
    query = re.sub(r"^(what is|explain|describe)\s+", "", query, flags=re.IGNORECASE)
    query = re.sub(r"\s*(是什么|指什么|如何定义)$", "", query)
    query = re.sub(r"\s+(mean|means)$", "", query, flags=re.IGNORECASE)
    if query and len(query) <= 100:
        return query

    if turn.titles:
        return _clip_text(turn.titles[0], 100)

    answer = re.split(r"[。.!?！？;；]", turn.assistant_answer, maxsplit=1)[0]
    return _clip_text(answer, 100)


def _select_topic(recent_turns: list[ConversationTurn]) -> str:
    for turn in reversed(recent_turns):
        if not is_follow_up_query(turn.user_query):
            topic = _extract_topic(turn)
            if topic:
                return topic
    return _extract_topic(recent_turns[-1]) if recent_turns else ""


def _rewrite_with_topic(query: str, topic: str) -> str:
    rewritten = _normalize_text(query)
    rewritten = re.sub(r"^(上面|刚才|前面)(提到的)?", "", rewritten).strip()
    rewritten = re.sub(r"^(它|这个)(?=\s|有|是|的|怎|为|可|能)", topic, rewritten, count=1)
    rewritten = re.sub(
        r"^(it|this|that)\b",
        topic,
        rewritten,
        count=1,
        flags=re.IGNORECASE,
    )
    if rewritten == _normalize_text(query) or topic.lower() not in rewritten.lower():
        rewritten = f"{topic}: {rewritten}"
    return rewritten


def build_contextual_query(
    query: str,
    recent_turns: list[ConversationTurn],
) -> tuple[str, dict[str, Any]]:
    original_query = _normalize_text(query)
    follow_up = is_follow_up_query(original_query)
    debug: dict[str, Any] = {
        "is_follow_up": follow_up,
        "original_query": original_query,
        "contextual_query": original_query,
        "memory_rewrite_strategy": "none",
        "memory_used": False,
    }
    if not follow_up or not recent_turns:
        return original_query, debug

    topic = _select_topic(recent_turns)
    if not topic:
        debug["memory_rewrite_strategy"] = "no_topic_available"
        return original_query, debug

    contextual_query = _rewrite_with_topic(original_query, topic)
    debug.update(
        {
            "contextual_query": contextual_query,
            "memory_rewrite_strategy": "rule_based_last_turn_topic",
            "memory_used": contextual_query != original_query,
            "memory_topic": topic,
        }
    )
    return contextual_query, debug


def contextualize_query_with_memory(
    query: str,
    session_id: str | None,
    memory_mode: str,
    store: ConversationMemoryStore,
) -> tuple[str, dict[str, Any]]:
    original_query = _normalize_text(query)
    normalized_session = _normalize_session_id(session_id) or None
    normalized_mode = str(memory_mode or "off").strip().lower()
    memory_enabled = normalized_mode == "buffer" and normalized_session is not None
    debug: dict[str, Any] = {
        "memory_mode": normalized_mode if normalized_mode in {"off", "buffer"} else "off",
        "memory_enabled": memory_enabled,
        "session_id": normalized_session,
        "memory_turn_count_before": 0,
        "is_follow_up": False,
        "original_query": original_query,
        "contextual_query": original_query,
        "memory_rewrite_strategy": "none",
        "memory_used_for_retrieval": False,
        "cross_session_isolated": True,
    }
    if not memory_enabled:
        return original_query, debug

    recent_turns = store.get_recent_turns(normalized_session)
    contextual_query, rewrite_debug = build_contextual_query(original_query, recent_turns)
    debug.update(rewrite_debug)
    debug.update(
        {
            "memory_turn_count_before": len(recent_turns),
            "memory_used_for_retrieval": bool(rewrite_debug.get("memory_used")),
        }
    )
    return contextual_query, debug


_memory_store: ConversationMemoryStore | None = None
_memory_store_lock = RLock()


def get_memory_store(
    max_turns: int = DEFAULT_MAX_TURNS,
    max_answer_chars: int = DEFAULT_MAX_ANSWER_CHARS,
) -> ConversationMemoryStore:
    global _memory_store
    with _memory_store_lock:
        if _memory_store is None:
            _memory_store = ConversationMemoryStore(
                max_turns=max_turns,
                max_answer_chars=max_answer_chars,
            )
        return _memory_store
