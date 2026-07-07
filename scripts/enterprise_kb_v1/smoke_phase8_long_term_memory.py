#!/usr/bin/env python3
"""Phase 8 Smoke: Long-term Memory — SQLite store + approve/reject/disable lifecycle."""

import json, sys
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))
REPORTS = Path(__file__).resolve().parent.parent.parent / "reports" / "enterprise_kb_v1"
REPORTS.mkdir(parents=True, exist_ok=True)

import uuid
from long_term_memory.sqlite_store import LongTermMemoryStore


# Shared store — 每个 test 不复用 DB，避免 WAL 锁
def _new_store() -> LongTermMemoryStore:
    uid = str(uuid.uuid4())[:8]
    path = f"workspace/phase8_smoke_{uid}.sqlite"
    return LongTermMemoryStore(path)


def test_init_store():
    store = _new_store()
    return {"pass": "phase8_smoke_" in store.db_path}


def test_create_pending_candidate():
    store = _new_store()
    c = store.create_candidate("本项目默认使用 bge-m3 embedding", memory_type="project_constraint")
    return {"pass": c["status"] == "pending" and c["candidate_id"].startswith("cand_")}


def test_pending_not_in_approved():
    store = _new_store()
    store.create_candidate("禁止本地重建 Chroma")
    approved = store.read_approved_memories()
    return {"pass": len(approved) == 0}


def test_approve_creates_item():
    store = _new_store()
    c = store.create_candidate("必须使用 HPC 跑 eval")
    item = store.approve_candidate(c["candidate_id"])
    return {"pass": item is not None and item["status"] == "active"}


def test_approved_memory_readable():
    store = _new_store()
    c = store.create_candidate("本项目禁止提交 Chroma storage")
    store.approve_candidate(c["candidate_id"])
    approved = store.read_approved_memories()
    return {"pass": len(approved) == 1}


def test_reject_no_item():
    store = _new_store()
    c = store.create_candidate("test reject")
    store.reject_candidate(c["candidate_id"])
    cand = store.get_candidate(c["candidate_id"])
    approved = store.read_approved_memories()
    return {"pass": cand["status"] == "rejected" and len(approved) == 0}


def test_disable_removes_from_context():
    store = _new_store()
    c = store.create_candidate("test disable")
    item = store.approve_candidate(c["candidate_id"])
    store.disable_memory(item["memory_id"])
    approved = store.read_approved_memories()
    item2 = store.get_item(item["memory_id"])
    return {"pass": len(approved) == 0 and item2["status"] == "disabled"}


def test_events_recorded():
    store = _new_store()
    c = store.create_candidate("event test")
    store.approve_candidate(c["candidate_id"])
    events = store.list_events()
    event_types = [e["event_type"] for e in events]
    return {"pass": len(events) >= 2 and "candidate_created" in event_types}


def main():
    print("=== Phase 8 Smoke: Long-term Memory ===")
    results = {"smoke": "phase8_long_term_memory", "timestamp": datetime.now(timezone.utc).isoformat()}
    tests = [
        ("init_store", test_init_store()),
        ("create_pending", test_create_pending_candidate()),
        ("pending_not_approved", test_pending_not_in_approved()),
        ("approve_creates_item", test_approve_creates_item()),
        ("approved_readable", test_approved_memory_readable()),
        ("reject_no_item", test_reject_no_item()),
        ("disable_removes", test_disable_removes_from_context()),
        ("events_recorded", test_events_recorded()),
    ]
    for name, r in tests:
        print(f"  {name}: {'PASS' if r['pass'] else 'FAIL'}")
        results[name] = r
    all_pass = all(r["pass"] for _, r in tests)
    results["overall_pass"] = all_pass
    path = REPORTS / "phase8_long_term_memory_smoke.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\nSaved: {path}")
    print(f"Overall: {'PASS' if all_pass else 'FAIL'}")
    if not all_pass: sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
