"""Project-scoped conversational memory with deterministic focus rewriting."""

from __future__ import annotations

import re
import time
import uuid
from typing import Any

from session_memory.policy import MemoryPolicy
from session_memory.schema import MemoryTrace, MemoryTurn, SessionMemory
from session_memory.store import MemoryStore, get_memory_store

_KNOWN_ENTITIES = (
    "FastAPI",
    "Pydantic",
    "LangGraph",
    "Chroma",
    "bge-m3",
    "custom_graph",
    "retrieval_orchestrator",
    "memory_rewriter",
    "enterprise_kb_v1",
    "Phase 6F",
)
_FOLLOWUP_RE = re.compile(
    r"\b(it|this|that|these|those|continue|previous)\b|它|这个|那个|上述|继续|刚才|前面",
    re.IGNORECASE,
)
_QUESTION_STOPWORDS = {
    "a",
    "an",
    "are",
    "can",
    "define",
    "describe",
    "does",
    "explain",
    "how",
    "is",
    "please",
    "the",
    "to",
    "what",
    "why",
}


class ScopedSessionMemoryManager:
    """Keep the public session ID while isolating storage by project."""

    def __init__(
        self,
        session_id: str = "",
        project_id: str = "enterprise_kb_v1",
        store: MemoryStore | None = None,
    ) -> None:
        self.session_id = session_id or f"auto_{uuid.uuid4().hex[:8]}"
        self.project_id = project_id
        self.store = store or get_memory_store()
        self.auto_generated = not bool(session_id)

    @property
    def storage_session_id(self) -> str:
        return f"{self.project_id}:{self.session_id}"

    def get_or_create(self) -> SessionMemory:
        return self.store.get_or_create(self.storage_session_id)

    def _extract_entities(self, text: str) -> list[str]:
        lowered = text.lower()
        return [entity for entity in _KNOWN_ENTITIES if entity.lower() in lowered]

    def _extract_focus(self, text: str) -> str:
        entities = self._extract_entities(text)
        words = re.findall(r"[A-Za-z][A-Za-z0-9_.-]*", text)
        meaningful = [
            word
            for word in words
            if word.lower() not in _QUESTION_STOPWORDS and not _FOLLOWUP_RE.fullmatch(word)
        ]
        if entities:
            anchor = entities[0]
            anchor_index = next(
                (index for index, word in enumerate(meaningful) if word.lower() == anchor.lower()),
                -1,
            )
            if anchor_index >= 0:
                return " ".join(meaningful[anchor_index : anchor_index + 4])[:120]
            return anchor
        if meaningful and not _FOLLOWUP_RE.search(text):
            return " ".join(meaningful[:5])[:120]
        return ""

    def rewrite_coreference(self, query: str) -> tuple[str, dict[str, Any]]:
        memory = self.get_or_create()
        recent = memory.recent_queries(3)
        entities = self._extract_entities(query)
        is_followup = bool(_FOLLOWUP_RE.search(query))
        trace: dict[str, Any] = {
            "original_query": query,
            "previously_asked": recent,
            "rewrite_used_memory": False,
            "memory_sources": [],
            "entities": entities,
            "last_entities": memory.last_entities,
            "last_focus": memory.last_focus,
            "rewrite_reason": "no_rewrite_needed",
        }

        if not recent:
            if is_followup:
                trace["rewrite_reason"] = "followup_but_no_history"
            else:
                memory.last_focus = self._extract_focus(query)
            if entities:
                memory.last_entities = entities
            return query, trace

        if not is_followup and len(query.strip()) >= 5:
            focus = self._extract_focus(query)
            if focus:
                memory.last_focus = focus
            if entities:
                memory.last_entities = list(dict.fromkeys(memory.last_entities[-5:] + entities))
            return query, trace

        replacement = memory.last_focus
        if not replacement and memory.last_entities:
            replacement = " ".join(memory.last_entities[:3])
        if not replacement:
            replacement = recent[-1][:120]

        rewritten, replacements = _FOLLOWUP_RE.subn(replacement, query)
        if replacements == 0:
            rewritten = f"{replacement}: {query}"
        rewritten = re.sub(r"\s+", " ", rewritten).strip()
        trace.update(
            {
                "rewritten_query": rewritten,
                "rewrite_used_memory": True,
                "memory_sources": ["recent_turn", "last_focus"],
                "rewrite_reason": "coreference_resolution_with_focus",
            }
        )
        if entities:
            memory.last_entities = list(dict.fromkeys(memory.last_entities[-5:] + entities))
        return rewritten, trace

    def detect_topic(self, query: str) -> str:
        lowered = query.lower()
        topic_keywords = {
            "retrieval": ("retrieval", "recall", "hit@", "mrr", "检索"),
            "embedding": ("embedding", "bge-m3", "dense", "向量"),
            "routing": ("routing", "corpus", "dual", "路由"),
            "evaluation": ("eval", "evaluation", "评测"),
            "memory": ("memory", "session", "记忆", "多轮"),
        }
        for topic, keywords in topic_keywords.items():
            if any(keyword in lowered for keyword in keywords):
                return topic
        return "general"

    def update_active_topic(self, topic: str) -> None:
        self.store.update_active_topic(self.storage_session_id, topic)

    def build_context(self) -> str:
        memory = self.get_or_create()
        parts: list[str] = []
        if memory.active_topic:
            parts.append(f"Active topic: {memory.active_topic}")
        if memory.last_focus:
            parts.append(f"Conversation focus: {memory.last_focus}")
        recent = memory.recent_queries(3)
        if recent:
            parts.append("Recent questions: " + " | ".join(recent))
        if memory.last_entities:
            parts.append("Recent entities: " + ", ".join(memory.last_entities[:5]))
        return "\n".join(parts)

    def add_turn(
        self,
        query: str,
        rewritten_query: str = "",
        response: str = "",
        intent: str = "",
        sources: list[str] | None = None,
    ) -> None:
        memory = self.get_or_create()
        focus = self._extract_focus(rewritten_query or query)
        if focus and not _FOLLOWUP_RE.search(query):
            memory.last_focus = focus
        entities = self._extract_entities(rewritten_query or query)
        if entities:
            memory.last_entities = list(dict.fromkeys(memory.last_entities[-5:] + entities))
        self.store.add_turn(
            self.storage_session_id,
            MemoryTurn(
                query=query,
                response=response,
                rewritten_query=rewritten_query,
                intent=intent,
                topic=self.detect_topic(query),
                sources=sources or [],
                entities=entities,
                timestamp=time.time(),
            ),
        )

    def maybe_write_candidates(
        self,
        query: str,
        rewritten_query: str = "",
        answer: str = "",
    ) -> list[dict[str, Any]]:
        candidates = MemoryPolicy.extract_candidate(query, answer, rewritten_query)
        memory = self.get_or_create()
        for candidate in candidates:
            if candidate.get("key_point") and candidate not in memory.pending_memory_candidates:
                memory.pending_memory_candidates.append(candidate)
        return candidates

    def build_trace(
        self,
        rewritten_query: str,
        rewrite_used_memory: bool,
        memory_candidates: list[dict[str, Any]],
    ) -> MemoryTrace:
        memory = self.get_or_create()
        return MemoryTrace(
            session_id=self.session_id,
            project_id=self.project_id,
            memory_read_used=rewrite_used_memory or bool(memory.turns),
            auto_generated_session_id=self.auto_generated,
            recent_turns_count=len(memory.turns),
            active_topic=memory.active_topic,
            last_focus=memory.last_focus,
            rewrite_used_memory=rewrite_used_memory,
            memory_context=self.build_context(),
            memory_write_candidate=memory_candidates,
            memory_write_status="candidate_only" if memory_candidates else "none",
            candidate_only_not_committed=True,
        )
