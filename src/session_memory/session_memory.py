"""Phase 7 v1.1: Session Memory Manager — entity-aware rewrite, pending candidates."""

from __future__ import annotations

import time, uuid, re
from typing import Any

from session_memory.schema import MemoryTurn, SessionMemory, MemoryTrace
from session_memory.store import get_memory_store
from session_memory.policy import MemoryPolicy

_KNOWN_ENTITIES = [
    "custom_graph", "official_docs", "internal_engineering_docs",
    "retrieval_orchestrator", "bge-m3", "bge-small-zh-v1.5",
    "qwen3-embedding-0.6b", "Chroma", "chromadb",
    "Phase 4FH", "Phase 5B", "Phase 6F", "Phase 7",
    "memory_rewriter", "query_classifier", "planner", "ranker",
    "answer_generator", "evidence_verifier", "final_response",
    "enterprise_kb_v1", "source_registry", "corpus_router",
    "FastAPI", "Pydantic", "LangGraph", "OpenAI",
    "HPC", "NVIDIA L40", "GPU",
]
_COREFERENCE_WORDS = [
    "它", "他", "她", "这个", "那个", "这些", "那些",
    "继续", "上面", "刚才", "之前", "前面", "该模块", "上述模块",
    "it", "this", "that", "continue", "previous",
]


class SessionMemoryManager:
    def __init__(self, session_id: str = ""):
        self.session_id = session_id
        self.store = get_memory_store()

    def get_or_create(self) -> SessionMemory:
        if not self.session_id:
            self.session_id = f"auto_{uuid.uuid4().hex[:8]}"
        return self.store.get_or_create(self.session_id)

    @property
    def has_session(self) -> bool:
        return bool(self.session_id)

    @property
    def is_auto_generated(self) -> bool:
        return self.session_id.startswith("auto_")

    def _extract_entities(self, text: str) -> list[str]:
        return [e for e in _KNOWN_ENTITIES if e.lower() in text.lower()]

    def rewrite_coreference(self, query: str) -> tuple[str, dict[str, Any]]:
        mem = self.get_or_create()
        recent = mem.recent_queries(3)
        entities = self._extract_entities(query)
        trace: dict[str, Any] = {
            "original_query": query,
            "previously_asked": recent,
            "rewrite_used_memory": False,
            "memory_sources": [],
            "entities": entities,
            "last_entities": mem.last_entities,
            "rewrite_reason": "no_rewrite_needed",
        }
        is_followup = any(kw in query for kw in _COREFERENCE_WORDS)

        if not recent:
            if is_followup:
                trace["rewrite_reason"] = "followup_but_no_history"
            if entities:
                mem.last_entities = entities
            return query, trace

        if is_followup or len(query.strip()) < 5:
            replacement = ""
            if mem.last_entities:
                replacement = "、".join(mem.last_entities[:3])
            elif recent:
                replacement = recent[-1][:100]
            if replacement:
                # 构建 standalone query: 用实体替换指代词，清理冗余格式
                # "它和 X 有什么区别？" → "REPLACEMENT 和 X 有什么区别？"
                rewritten = re.sub(
                    r"(它|他|她|这个|那个|这些|那些|该模块|上述模块|it|this|that)",
                    replacement, query, flags=re.IGNORECASE)
                # 清理重复的 "[上下文] 追问" 模式
                rewritten = re.sub(r"\[.*?\]\s*追问\s*[:：]?\s*", "", rewritten)
            elif recent:
                rewritten = f"[{recent[-1][:100]}] {query}"
            else:
                rewritten = query
            trace["rewritten_query"] = rewritten
            trace["rewrite_used_memory"] = True
            trace["memory_sources"] = ["recent_turn"]
            if mem.last_entities:
                trace["memory_sources"].append("last_entities")
            trace["rewrite_reason"] = "coreference_resolution_with_entities"
            new_entities = self._extract_entities(rewritten)
            if new_entities:
                mem.last_entities = list(dict.fromkeys(mem.last_entities[-5:] + new_entities))
            if entities:
                mem.last_entities = list(dict.fromkeys(mem.last_entities[-5:] + entities))
            return rewritten, trace

        if entities:
            mem.last_entities = list(dict.fromkeys(mem.last_entities[-5:] + entities))
        return query, trace

    def build_context(self, include_pending: bool = False) -> str:
        mem = self.get_or_create()
        parts: list[str] = []
        if mem.active_topic:
            parts.append(f"Active topic: {mem.active_topic}")
        recent = mem.recent_queries(3)
        if recent:
            parts.append("Recent questions: " + " | ".join(recent))
        if mem.project_constraints:
            parts.append("Project constraints: " + "; ".join(mem.project_constraints))
        if mem.last_entities:
            parts.append("Recent entities: " + ", ".join(mem.last_entities[:5]))
        if include_pending and mem.pending_memory_candidates:
            parts.append("Pending candidates: " + str(mem.pending_memory_candidates))
        return "\n".join(parts)

    def detect_topic(self, query: str) -> str:
        topic_keywords = {
            "retrieval": ["检索", "recall", "retrieval", "hit@", "MRR", "channel"],
            "embedding": ["embedding", "bge-m3", "向量", "dense"],
            "routing": ["路由", "routing", "corpus", "dual", "auto"],
            "evaluation": ["eval", "评测", "gold label", "hit_rate"],
            "config": ["配置", "config", "pipline", "环境变量"],
            "memory": ["记忆", "context", "session", "追问", "多轮"],
        }
        for topic, keywords in topic_keywords.items():
            if any(kw in query.lower() for kw in keywords):
                return topic
        return "general"

    def add_turn(self, query: str, rewritten_query: str = "",
                  intent: str = "", sources: list[str] | None = None,
                  topic: str = "") -> None:
        turn = MemoryTurn(
            query=query, rewritten_query=rewritten_query, intent=intent,
            sources=sources or [], topic=topic or self.detect_topic(query),
            entities=self._extract_entities(query), timestamp=time.time(),
        )
        self.store.add_turn(self.session_id, turn)

    def maybe_write_candidates(self, query: str, rewritten_query: str = "",
                                answer: str = "", intent: str = "") -> list[dict[str, Any]]:
        """生成 pending candidate, 不自动写入 project_constraints。"""
        candidates = MemoryPolicy.extract_candidate(query, answer, rewritten_query)
        mem = self.get_or_create()
        for c in candidates:
            if c.get("key_point") and c not in mem.pending_memory_candidates:
                mem.pending_memory_candidates.append(c)
        return candidates

    def build_trace(self, query: str, rewritten_query: str = "",
                     rewrite_used_memory: bool = False,
                     memory_candidates: list[dict[str, Any]] | None = None,
                     ) -> MemoryTrace:
        mem = self.get_or_create()
        return MemoryTrace(
            session_id=self.session_id,
            memory_read_used=rewrite_used_memory or len(mem.turns) > 0,
            auto_generated_session_id=self.is_auto_generated,
            recent_turns_count=len(mem.turns),
            active_topic=mem.active_topic,
            rewrite_used_memory=rewrite_used_memory,
            memory_context=self.build_context(),
            memory_write_candidate=memory_candidates or [],
            memory_write_status="candidate_only" if memory_candidates else "none",
            candidate_only_not_committed=True,
        )
