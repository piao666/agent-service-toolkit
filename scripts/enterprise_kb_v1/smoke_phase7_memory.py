#!/usr/bin/env python3
"""Phase 7 v1.3 Smoke: Session Memory — entity rewrite, pending candidates, policy boundaries.

Covers:
  1. session create
  2. recent turns read
  3. coreference rewrite (entity-aware)
  4. active_topic
  5. 普通问答不写 memory
  6. 项目约束生成 memory_candidate (candidate_only_not_committed)
  7. policy 边界: HPC constraint / 禁止本地重建 / 知识问答不触发
  8. entity rewrite: internal_engineering_docs + official_docs coreference
"""

import json, sys
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))
REPORTS = Path(__file__).resolve().parent.parent.parent / "reports" / "enterprise_kb_v1"
REPORTS.mkdir(parents=True, exist_ok=True)

from session_memory.store import MemoryStore
from session_memory.session_memory import SessionMemoryManager
from session_memory.policy import MemoryPolicy


def test_session_create():
    store = MemoryStore()
    sid = "test_session_001"
    mem = store.get_or_create(sid)
    return {"pass": mem.session_id == sid and len(mem.turns) == 0}


def test_recent_turns():
    mgr = SessionMemoryManager("test_session_002")
    mgr.add_turn("What is FastAPI?", rewritten_query="What is FastAPI?", intent="knowledge")
    mgr.add_turn("How does middleware work?", intent="knowledge")
    mem = mgr.get_or_create()
    recent = mem.recent_turns(3)
    return {"pass": len(mem.turns) == 2 and len(recent) == 2}


def test_coreference_rewrite():
    mgr = SessionMemoryManager("test_session_003")
    mgr.add_turn("FastAPI middleware 怎么用？", intent="knowledge")
    rewritten, trace = mgr.rewrite_coreference("它的实现原理是什么？")
    return {
        "original": "它的实现原理是什么？",
        "rewritten": rewritten,
        "rewrite_used_memory": trace.get("rewrite_used_memory", False),
        "pass": trace.get("rewrite_used_memory") is True and "FastAPI" in rewritten,
    }


def test_entity_rewrite():
    """第1轮 internal_engineering_docs, 第2轮追问 + official_docs 对比。"""
    mgr = SessionMemoryManager("test_entity_001")
    # 清除旧数据
    mgr.store._sessions.pop("test_entity_001", None)
    mgr = SessionMemoryManager("test_entity_001")
    mgr.add_turn("internal_engineering_docs 是什么？", intent="knowledge")
    rewritten, trace = mgr.rewrite_coreference("它和 official_docs 有什么区别？")
    return {
        "original": "它和 official_docs 有什么区别？",
        "rewritten": rewritten,
        "rewrite_used": trace.get("rewrite_used_memory", False),
        "has_internal": "internal_engineering_docs" in rewritten,
        "has_official": "official_docs" in rewritten or "official_docs" in rewritten.lower(),
        "pass": trace.get("rewrite_used_memory") is True and "internal_engineering_docs" in rewritten,
    }


def test_active_topic():
    mgr = SessionMemoryManager("test_session_004")
    mgr.add_turn("bge-m3 的 hit@3 是多少？", intent="knowledge", topic="embedding")
    mgr.store.update_active_topic("test_session_004", "embedding")
    mem = mgr.get_or_create()
    ctx = mgr.build_context()
    return {"pass": mem.active_topic == "embedding" and "embedding" in ctx}


def test_no_write_for_qa():
    should = MemoryPolicy.should_write_candidate("什么是 FastAPI middleware？")
    return {"pass": should is False}


def test_write_for_constraint():
    should = MemoryPolicy.should_write_candidate("本项目以后都使用 bge-m3 作为默认 embedding")
    candidates = MemoryPolicy.extract_candidate("本项目以后都使用 bge-m3 作为默认 embedding", answer="已记录")
    return {"pass": should is True and len(candidates) > 0}


def test_candidate_only_not_committed():
    """candidate 不应自动写入 project_constraints。"""
    mgr = SessionMemoryManager("test_candidate_001")
    mgr.store._sessions.pop("test_candidate_001", None)
    mgr = SessionMemoryManager("test_candidate_001")
    candidates = mgr.maybe_write_candidates("本项目以后都使用 bge-m3 作为默认 embedding")
    mem = mgr.get_or_create()
    has_pending = len(mem.pending_memory_candidates) > 0
    not_in_constraints = "bge-m3" not in str(mem.project_constraints)
    ctx = mgr.build_context()
    candidate_not_in_context = "candidate" not in ctx.lower()
    return {
        "candidates_count": len(candidates),
        "has_pending": has_pending,
        "not_in_project_constraints": not_in_constraints,
        "candidate_not_in_memory_context": candidate_not_in_context,
        "pass": has_pending and not_in_constraints and candidate_not_in_context,
    }


def test_policy_hpc_constraint():
    """HPC 约束应生成 candidate。"""
    should = MemoryPolicy.should_write_candidate("以后所有 retrieval eval 怎么跑都必须在 HPC 上执行")
    return {"pass": should is True}


def test_policy_no_rebuild():
    """禁止本地重建 Chroma 应生成 candidate。"""
    should = MemoryPolicy.should_write_candidate("本项目禁止本地重建 Chroma")
    return {"pass": should is True}


def test_policy_qa_no_write():
    """知识问答不应生成 candidate。"""
    tests = [
        MemoryPolicy.should_write_candidate("怎么使用 FastAPI middleware？"),
        MemoryPolicy.should_write_candidate("介绍一下 Chroma collection"),
        MemoryPolicy.should_write_candidate("internal_engineering_docs 和 official_docs 有什么区别？"),
    ]
    return {"pass": all(not t for t in tests)}


def test_policy_strong_override():
    """强约束关键词应覆盖弱禁止规则。"""
    tests = [
        MemoryPolicy.should_write_candidate("以后所有 retrieval eval 如何执行都必须在 HPC 上"),
        MemoryPolicy.should_write_candidate("为什么本项目禁止本地重建 Chroma？"),
    ]
    return {"pass": all(tests)}


def test_auto_session_id():
    """无 session_id 时自动生成临时 id (方案 A: memory 仍生效)。"""
    mgr = SessionMemoryManager("")
    mem = mgr.get_or_create()
    return {
        "session_id": mem.session_id,
        "is_auto": mem.session_id.startswith("auto_"),
        "has_session": mgr.has_session,
        "is_auto_generated": mgr.is_auto_generated,
        "pass": mem.session_id.startswith("auto_") and mgr.has_session and mgr.is_auto_generated,
    }


def main():
    print("=== Phase 7 v1.3 Smoke: Session Memory ===")
    results = {"smoke": "phase7_memory_v1.3", "timestamp": datetime.now(timezone.utc).isoformat()}

    tests = [
        ("session_create", test_session_create()),
        ("recent_turns", test_recent_turns()),
        ("coreference_rewrite", test_coreference_rewrite()),
        ("entity_rewrite", test_entity_rewrite()),
        ("active_topic", test_active_topic()),
        ("no_write_for_qa", test_no_write_for_qa()),
        ("write_for_constraint", test_write_for_constraint()),
        ("candidate_only_not_committed", test_candidate_only_not_committed()),
        ("policy_hpc_constraint", test_policy_hpc_constraint()),
        ("policy_no_rebuild", test_policy_no_rebuild()),
        ("policy_qa_no_write", test_policy_qa_no_write()),
        ("policy_strong_override", test_policy_strong_override()),
        ("auto_session_id", test_auto_session_id()),
    ]

    for name, r in tests:
        status = "PASS" if r["pass"] else "FAIL"
        print(f"  {name}: {status}")
        results[name] = r

    all_pass = all(r["pass"] for _, r in tests)
    results["overall_pass"] = all_pass

    path = REPORTS / "phase7_memory_smoke.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\nSaved: {path}")
    print(f"Overall: {'PASS' if all_pass else 'FAIL'}")
    if not all_pass: sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
