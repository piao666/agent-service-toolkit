"""Phase 8: Long-term memory policy — 控制何时生成 candidate 并持久化。"""

from __future__ import annotations

from session_memory.policy import MemoryPolicy


class LongTermMemoryPolicy:
    """长期记忆策略: 复用 Phase 7 MemoryPolicy 判断 + 持久化到 SQLite。"""

    @staticmethod
    def should_create_candidate(query: str, rewritten_query: str = "", answer: str = "") -> bool:
        """是否应将 candidate 持久化到 long-term store。"""
        return MemoryPolicy.should_write_candidate(query, rewritten_query, answer)

    @staticmethod
    def candidate_from_query(
        query: str,
        rewritten_query: str = "",
        session_id: str = "",
        project_id: str = "enterprise_kb_v1",
    ) -> dict:
        return {
            "content": rewritten_query or query,
            "memory_type": "project_constraint",
            "scope_type": "project",
            "scope_id": project_id,
            "source_query": query[:500],
            "source_session_id": session_id,
            "confidence": 1.0,
        }
