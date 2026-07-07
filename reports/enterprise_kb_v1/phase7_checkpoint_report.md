# Phase 7 v1.3 Checkpoint Report

**日期**: 2026-07-07
**状态**: PASS

---

## 功能概述

为 enterprise_kb_v1 的 custom_graph 增加 session memory 能力：
- 多轮追问指代消解（entity-aware rewrite）
- 项目上下文保持（active_topic / memory_context）
- memory write candidate（candidate_only，不自动提交）
- 自动 session_id 生成与传播
- Graph API 返回 memory_trace

## 新增模块

| 模块 | 文件 | 功能 |
|------|------|------|
| session_memory | `schema.py` | MemoryTurn, SessionMemory, MemoryTrace dataclass |
| session_memory | `store.py` | 进程内 dict MemoryStore |
| session_memory | `session_memory.py` | SessionMemoryManager (rewrite/context/candidate) |
| session_memory | `policy.py` | MemoryPolicy (强约束优先) |

## 修改文件

| 文件 | 修改 |
|------|------|
| `custom_graph/state.py` | + memory_context, memory_trace, memory_candidates |
| `custom_graph/nodes/memory_rewriter.py` | 重写: entity-aware rewrite + auto id 回写 GraphState |
| `custom_graph/nodes/final_response.py` | + memory_trace 输出 + add_turn |
| `schema/schema.py` | EnterpriseKBGraphAnswerResponse + memory_trace |
| `service/service.py` | endpoint + memory_trace 字段 |

## Smoke 结果 (7/7, 全部 rc=0)

| Smoke | 版本 | 结果 |
|-------|------|:---:|
| Phase 7 Memory | v1.3 | PASS (13/13) |
| Phase 7 Memory Graph API | v1.3 | PASS |
| Phase 5 Custom Graph | - | PASS |
| Phase 5B Graph API | - | PASS |
| Phase 6 Multi-channel | - | PASS |
| Phase 6C PostProcessor | - | PASS |
| Phase 6D Retrieval Eval | - | PASS |

## 无 session_id 策略 (方案 A)

- `session_id=""` → 自动生成 `auto_xxxxxxxx`
- memory read/write 对该 auto session 生效
- `memory_trace.auto_generated_session_id=true`
- `memory_trace.session_id` 返回给前端
- 前端后续应携带该 session_id 以维持多轮上下文

### API 多轮示例

```
turn1: POST /api/enterprise-kb/graph/answer {"query":"internal_engineering_docs 是什么？"}
  → session_id=auto_e6408e63, auto_generated=true, recent_turns=0

turn2: POST /api/enterprise-kb/graph/answer {"query":"它和 official_docs 有什么区别？","session_id":"auto_e6408e63"}
  → session_id=auto_e6408e63, recent_turns=1, rewrite_used=true
  → rewritten_query: "internal_engineering_docs 和 official_docs 有什么区别？"
```

## Memory Trace 字段

| 字段 | 说明 |
|------|------|
| session_id | 会话 ID (auto-gen 或用户传入) |
| auto_generated_session_id | 是否自动生成 |
| memory_read_used | 本轮是否读取历史 |
| recent_turns_count | 历史轮数 |
| active_topic | 当前活跃主题 |
| rewrite_used_memory | 是否用历史改写 |
| memory_context | 上下文字符串 |
| memory_write_candidate | pending candidates |
| memory_write_status | none / candidate_only |
| candidate_only_not_committed | true (始终不自动提交) |

## 关键设计决策

| 决策 | 说明 |
|------|------|
| 存储 | 进程内 dict，服务重启清空 |
| candidate | 仅 pending，不自动写入 project_constraints |
| policy 优先级 | 强约束（必须/禁止/本项目/记住）> 触发 > 禁止 |
| entity rewrite | last_entities 替换指代词，输出 standalone query |
| 数据库 | 无（Phase 8 引入 SQLite） |

---

## 后续 Roadmap

### Phase 8: Persistent Long-term Memory
- SQLite 持久化
- memory_candidates / memory_items / memory_events
- candidate → approve/reject → approved memory
- approved memory 接入 custom_graph
- memory admin API

### Phase 9: Frontend & Admin Console MVP
- 用户问答端：session_id 自动生成/复用、citations/sources/memory_trace/retrieval_trace 展示
- memory admin console：pending candidate 审核、approved memory 查看与 disable
- source/eval/trace viewer

### Phase 10: MVP End-to-End Acceptance
- 用户问答 → 返回引用 → 生成 memory candidate → 管理员审核 → approved memory 生效
- 后续问答读取 long-term memory
- 后台可查看 memory/source/eval/trace

### 后续扩展
- **Phase 11**: Vectorized Memory Retrieval
- **Phase 12**: Cross-project Memory
- **Phase 13**: Multi-user & RBAC Permission
- **Phase 14**: Concurrency & Async Jobs
- **Phase 15**: Production Deployment & Observability

> 策略: 优先完成 Long-term Memory + Frontend/Admin + MVP E2E 最小交付闭环。

---

**Phase 7 v1.3: PASS.**
