"""Phase 8: Long-term Memory data structures."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from enum import StrEnum


class CandidateStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class MemoryItemStatus(StrEnum):
    ACTIVE = "active"
    DISABLED = "disabled"


class MemoryType(StrEnum):
    CONSTRAINT = "project_constraint"
    PREFERENCE = "user_preference"
    KNOWLEDGE = "knowledge"
    RULE = "rule"


class ScopeType(StrEnum):
    PROJECT = "project"
    SESSION = "session"
    USER = "user"


@dataclass
class MemoryCandidate:
    candidate_id: str = ""
    content: str = ""
    memory_type: str = "project_constraint"
    scope_type: str = "project"
    scope_id: str = "enterprise_kb_v1"
    source_query: str = ""
    source_session_id: str = ""
    confidence: float = 1.0
    status: str = "pending"
    created_at: str = ""
    updated_at: str = ""
    metadata_json: str = "{}"


@dataclass
class MemoryItem:
    memory_id: str = ""
    content: str = ""
    memory_type: str = "project_constraint"
    scope_type: str = "project"
    scope_id: str = "enterprise_kb_v1"
    status: str = "active"
    confidence: float = 1.0
    source_candidate_id: str = ""
    created_at: str = ""
    updated_at: str = ""
    approved_at: str = ""
    disabled_at: str = ""
    metadata_json: str = "{}"


@dataclass
class MemoryEvent:
    event_id: str = ""
    target_type: str = ""   # candidate / memory_item
    target_id: str = ""
    event_type: str = ""    # created / approved / rejected / disabled
    event_detail: str = ""
    created_at: str = ""
    metadata_json: str = "{}"


@dataclass
class LongTermMemoryTrace:
    long_term_memory_used: bool = False
    approved_memory_count: int = 0
    pending_candidate_count: int = 0
    memory_write_status: str = "none"
    long_term_memory_scope: str = ""
    approved_memory_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "long_term_memory_used": self.long_term_memory_used,
            "approved_memory_count": self.approved_memory_count,
            "pending_candidate_count": self.pending_candidate_count,
            "memory_write_status": self.memory_write_status,
            "long_term_memory_scope": self.long_term_memory_scope,
            "approved_memory_ids": self.approved_memory_ids,
        }
