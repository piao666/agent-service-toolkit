"""Phase 8: SQLite store for long-term memory. Python stdlib sqlite3 only."""

from __future__ import annotations

import json, os, sqlite3, time, uuid
from pathlib import Path
from typing import Any

DEFAULT_DB_PATH = "workspace/enterprise_kb_v1_long_term_memory.sqlite"


class LongTermMemoryStore:
    """SQLite-backed long-term memory store."""

    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = db_path
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS memory_candidates (
                    candidate_id TEXT PRIMARY KEY,
                    content TEXT NOT NULL,
                    memory_type TEXT NOT NULL DEFAULT 'project_constraint',
                    scope_type TEXT NOT NULL DEFAULT 'project',
                    scope_id TEXT NOT NULL DEFAULT 'enterprise_kb_v1',
                    source_query TEXT DEFAULT '',
                    source_session_id TEXT DEFAULT '',
                    confidence REAL DEFAULT 1.0,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    metadata_json TEXT DEFAULT '{}'
                );
                CREATE TABLE IF NOT EXISTS memory_items (
                    memory_id TEXT PRIMARY KEY,
                    content TEXT NOT NULL,
                    memory_type TEXT NOT NULL DEFAULT 'project_constraint',
                    scope_type TEXT NOT NULL DEFAULT 'project',
                    scope_id TEXT NOT NULL DEFAULT 'enterprise_kb_v1',
                    status TEXT NOT NULL DEFAULT 'active',
                    confidence REAL DEFAULT 1.0,
                    source_candidate_id TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    approved_at TEXT DEFAULT '',
                    disabled_at TEXT DEFAULT '',
                    metadata_json TEXT DEFAULT '{}'
                );
                CREATE TABLE IF NOT EXISTS memory_events (
                    event_id TEXT PRIMARY KEY,
                    target_type TEXT NOT NULL,
                    target_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    event_detail TEXT DEFAULT '',
                    created_at TEXT NOT NULL,
                    metadata_json TEXT DEFAULT '{}'
                );
                CREATE INDEX IF NOT EXISTS idx_candidates_status ON memory_candidates(status);
                CREATE INDEX IF NOT EXISTS idx_items_status ON memory_items(status);
                CREATE INDEX IF NOT EXISTS idx_items_scope ON memory_items(scope_type, scope_id);
                CREATE INDEX IF NOT EXISTS idx_events_target ON memory_events(target_type, target_id);
            """)

    def _now(self) -> str:
        return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    def _uid(self) -> str:
        return uuid.uuid4().hex[:12]

    # ── Candidates ────────────────────────────────────────────────────

    def create_candidate(self, content: str, memory_type: str = "project_constraint",
                          scope_type: str = "project", scope_id: str = "enterprise_kb_v1",
                          source_query: str = "", source_session_id: str = "",
                          confidence: float = 1.0, metadata: dict | None = None) -> dict:
        cid = f"cand_{self._uid()}"
        now = self._now()
        meta_json = json.dumps(metadata or {}, ensure_ascii=False)
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO memory_candidates VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (cid, content, memory_type, scope_type, scope_id, source_query,
                 source_session_id, confidence, "pending", now, now, meta_json))
            conn.execute(
                "INSERT INTO memory_events VALUES (?,?,?,?,?,?,?)",
                (f"evt_{self._uid()}", "candidate", cid, "candidate_created",
                 f"created pending candidate: {content[:100]}", now, "{}"))
        return self.get_candidate(cid)

    def get_candidate(self, candidate_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM memory_candidates WHERE candidate_id=?", (candidate_id,)).fetchone()
            return dict(row) if row else None

    def list_candidates(self, status: str | None = None) -> list[dict]:
        with self._connect() as conn:
            if status:
                rows = conn.execute("SELECT * FROM memory_candidates WHERE status=? ORDER BY created_at DESC", (status,)).fetchall()
            else:
                rows = conn.execute("SELECT * FROM memory_candidates ORDER BY created_at DESC").fetchall()
            return [dict(r) for r in rows]

    def approve_candidate(self, candidate_id: str) -> dict | None:
        cand = self.get_candidate(candidate_id)
        if not cand or cand["status"] != "pending":
            return None
        now = self._now()
        mid = f"mem_{self._uid()}"
        with self._connect() as conn:
            conn.execute("UPDATE memory_candidates SET status='approved', updated_at=? WHERE candidate_id=?", (now, candidate_id))
            conn.execute(
                "INSERT INTO memory_items VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (mid, cand["content"], cand["memory_type"], cand["scope_type"], cand["scope_id"],
                 "active", cand["confidence"], candidate_id, now, now, now, "", cand["metadata_json"]))
            conn.execute(
                "INSERT INTO memory_events VALUES (?,?,?,?,?,?,?)",
                (f"evt_{self._uid()}", "candidate", candidate_id, "candidate_approved",
                 f"approved -> memory_item {mid}", now, "{}"))
        return self.get_item(mid)

    def reject_candidate(self, candidate_id: str) -> None:
        now = self._now()
        with self._connect() as conn:
            conn.execute("UPDATE memory_candidates SET status='rejected', updated_at=? WHERE candidate_id=?", (now, candidate_id))
            conn.execute(
                "INSERT INTO memory_events VALUES (?,?,?,?,?,?,?)",
                (f"evt_{self._uid()}", "candidate", candidate_id, "candidate_rejected",
                 "rejected", now, "{}"))

    # ── Items ─────────────────────────────────────────────────────────

    def get_item(self, memory_id: str) -> dict | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM memory_items WHERE memory_id=?", (memory_id,)).fetchone()
            return dict(row) if row else None

    def list_items(self, status: str | None = None, scope_type: str | None = None,
                    scope_id: str | None = None) -> list[dict]:
        with self._connect() as conn:
            q = "SELECT * FROM memory_items WHERE 1=1"
            params: list = []
            if status:
                q += " AND status=?"; params.append(status)
            if scope_type:
                q += " AND scope_type=?"; params.append(scope_type)
            if scope_id:
                q += " AND scope_id=?"; params.append(scope_id)
            q += " ORDER BY created_at DESC"
            rows = conn.execute(q, params).fetchall()
            return [dict(r) for r in rows]

    def read_approved_memories(self, scope_type: str = "project",
                                scope_id: str = "enterprise_kb_v1") -> list[dict]:
        return self.list_items(status="active", scope_type=scope_type, scope_id=scope_id)

    def disable_memory(self, memory_id: str) -> None:
        now = self._now()
        with self._connect() as conn:
            conn.execute("UPDATE memory_items SET status='disabled', disabled_at=?, updated_at=? WHERE memory_id=?", (now, now, memory_id))
            conn.execute(
                "INSERT INTO memory_events VALUES (?,?,?,?,?,?,?)",
                (f"evt_{self._uid()}", "memory_item", memory_id, "memory_disabled",
                 "disabled", now, "{}"))

    # ── Events ────────────────────────────────────────────────────────

    def list_events(self, target_type: str | None = None, limit: int = 50) -> list[dict]:
        with self._connect() as conn:
            if target_type:
                rows = conn.execute("SELECT * FROM memory_events WHERE target_type=? ORDER BY created_at DESC LIMIT ?", (target_type, limit)).fetchall()
            else:
                rows = conn.execute("SELECT * FROM memory_events ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
            return [dict(r) for r in rows]


# 全局单例
_global_ltm_store: LongTermMemoryStore | None = None


def get_ltm_store(db_path: str | None = None) -> LongTermMemoryStore:
    global _global_ltm_store
    if _global_ltm_store is None:
        _global_ltm_store = LongTermMemoryStore(db_path or DEFAULT_DB_PATH)
    return _global_ltm_store
