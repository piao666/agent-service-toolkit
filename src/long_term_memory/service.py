"""Phase 8: Long-term memory service — 封装 store 操作供 API 和 custom_graph 调用。"""

from __future__ import annotations

from long_term_memory.sqlite_store import get_ltm_store
from long_term_memory.policy import LongTermMemoryPolicy


class LongTermMemoryService:
    """长期记忆服务层。"""

    def __init__(self):
        self.store = get_ltm_store()

    # ── Candidate ─────────────────────────────────────────────────────

    def create_candidate(self, query: str, rewritten_query: str = "",
                          session_id: str = "") -> dict | None:
        if not LongTermMemoryPolicy.should_create_candidate(query, rewritten_query):
            return None
        spec = LongTermMemoryPolicy.candidate_from_query(query, rewritten_query, session_id)
        return self.store.create_candidate(**spec)

    def list_pending_candidates(self) -> list[dict]:
        return self.store.list_candidates(status="pending")

    def approve(self, candidate_id: str) -> dict | None:
        return self.store.approve_candidate(candidate_id)

    def reject(self, candidate_id: str) -> None:
        self.store.reject_candidate(candidate_id)

    # ── Items ─────────────────────────────────────────────────────────

    def list_approved_items(self, scope_type: str = "project",
                             scope_id: str = "enterprise_kb_v1") -> list[dict]:
        return self.store.read_approved_memories(scope_type, scope_id)

    def list_all_items(self, status: str | None = None) -> list[dict]:
        return self.store.list_items(status=status)

    def disable(self, memory_id: str) -> None:
        self.store.disable_memory(memory_id)

    # ── Events ────────────────────────────────────────────────────────

    def list_events(self, target_type: str | None = None,
                     limit: int = 50) -> list[dict]:
        return self.store.list_events(target_type=target_type, limit=limit)

    # ── Read context for custom_graph ─────────────────────────────────

    def read_context(self, scope_type: str = "project",
                      scope_id: str = "enterprise_kb_v1") -> tuple[str, list[str]]:
        """返回 (context_str, memory_ids)。"""
        items = self.list_approved_items(scope_type, scope_id)
        if not items:
            return "", []
        parts = [f"[{i['memory_type']}] {i['content']}" for i in items]
        ids = [i["memory_id"] for i in items]
        return "Approved long-term memories:\n" + "\n".join(parts), ids


# 全局单例
_global_ltm_service: LongTermMemoryService | None = None


def get_ltm_service() -> LongTermMemoryService:
    global _global_ltm_service
    if _global_ltm_service is None:
        _global_ltm_service = LongTermMemoryService()
    return _global_ltm_service
