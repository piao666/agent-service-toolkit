"""Phase 7 v1.1: Memory data structures with entity tracking and pending candidates."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class MemoryTurn:
    """单轮对话记录。"""
    query: str
    response: str = ""
    rewritten_query: str = ""
    intent: str = ""
    topic: str = ""
    sources: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    timestamp: float = 0.0


@dataclass
class SessionMemory:
    """会话级记忆。"""
    session_id: str = ""
    turns: list[MemoryTurn] = field(default_factory=list)
    active_topic: str = ""
    last_entities: list[str] = field(default_factory=list)
    project_constraints: list[str] = field(default_factory=list)
    pending_memory_candidates: list[dict[str, Any]] = field(default_factory=list)
    created_at: float = 0.0
    last_updated: float = 0.0

    def recent_turns(self, n: int = 5) -> list[MemoryTurn]:
        return self.turns[-n:] if self.turns else []

    def recent_queries(self, n: int = 3) -> list[str]:
        return [t.query for t in self.recent_turns(n)]


@dataclass
class MemoryTrace:
    """memory 操作 trace。"""
    session_id: str = ""
    memory_read_used: bool = False
    auto_generated_session_id: bool = False
    recent_turns_count: int = 0
    active_topic: str = ""
    rewrite_used_memory: bool = False
    memory_context: str = ""
    memory_write_candidate: list[dict[str, Any]] = field(default_factory=list)
    memory_write_status: str = "none"  # none / candidate_only / pending
    candidate_only_not_committed: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "memory_read_used": self.memory_read_used,
            "auto_generated_session_id": self.auto_generated_session_id,
            "recent_turns_count": self.recent_turns_count,
            "active_topic": self.active_topic,
            "rewrite_used_memory": self.rewrite_used_memory,
            "memory_context": self.memory_context,
            "memory_write_candidate": self.memory_write_candidate,
            "memory_write_status": self.memory_write_status,
            "candidate_only_not_committed": self.candidate_only_not_committed,
        }
