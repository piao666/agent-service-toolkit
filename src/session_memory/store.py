"""Phase 7: Memory Store — lightweight in-memory session store.

不引入数据库重依赖。基于 dict 的内存存储，服务重启后清空。
"""

from __future__ import annotations

from session_memory.schema import MemoryTurn, SessionMemory


class MemoryStore:
    """进程内 session memory store。"""

    def __init__(self):
        self._sessions: dict[str, SessionMemory] = {}

    def get_or_create(self, session_id: str) -> SessionMemory:
        if session_id not in self._sessions:
            import time
            self._sessions[session_id] = SessionMemory(
                session_id=session_id,
                created_at=time.time(),
            )
        return self._sessions[session_id]

    def get(self, session_id: str) -> SessionMemory | None:
        return self._sessions.get(session_id)

    def add_turn(self, session_id: str, turn: MemoryTurn) -> None:
        import time
        mem = self.get_or_create(session_id)
        mem.turns.append(turn)
        mem.last_updated = time.time()

    def update_active_topic(self, session_id: str, topic: str) -> None:
        mem = self.get(session_id)
        if mem:
            mem.active_topic = topic

    def add_constraint(self, session_id: str, constraint: str) -> None:
        mem = self.get(session_id)
        if mem and constraint not in mem.project_constraints:
            mem.project_constraints.append(constraint)

    def list_sessions(self) -> list[str]:
        return list(self._sessions.keys())

    def clear(self) -> None:
        self._sessions.clear()


# 全局单例
_global_store: MemoryStore | None = None


def get_memory_store() -> MemoryStore:
    global _global_store
    if _global_store is None:
        _global_store = MemoryStore()
    return _global_store
