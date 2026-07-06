# Phase 6C-6D Checkpoint Report

**日期**: 2026-07-06
**状态**: PASS

---

## Phase 6C: PostProcessor 增强

### 增强后的函数 (`src/rag/postprocess.py`)

| 函数 | 返回类型 | 说明 |
|------|---------|------|
| `deduplicate_by_chunk_id` | `tuple[list[SearchHit], dict]` | chunk_id 去重，保留最高分，trace 含 `removed_duplicates_count` |
| `deduplicate_by_source_id` | `tuple[list[SearchHit], dict]` | source_id 去重 (max_per_source)，trace 含 `source_dedup_policy` |
| `normalize_scores` | `tuple[list[SearchHit], dict]` | Min-max 归一化到 [0,1]，`original_score` 保留在 metadata |
| `balance_corpora` | `tuple[list[SearchHit], dict]` | Round-robin 语料平衡，trace 含 `corpus_distribution_before/after` |
| `select_citation_candidates` | `tuple[list[SearchHit], dict]` | Citation 候选，验证 chunk_id 非空且来自 merged |
| `run_postprocess_pipeline` | `dict` | 一站式管道：去重→归一化→源去重→语料平衡→citation |

### 向后兼容

所有旧函数名保持可用（返回 `list` 而非 `tuple`），Phase 5/5B/6A-6B smoke 不受影响。

新增畸形数据处理：空 `chunk_id` 的 hits 在 pipeline 入口被过滤并写入 errors。

## Phase 6D: 轻量 Retrieval Eval

### Eval 设计

6 条 fixture case，不依赖 Chroma/embedding：

| Case | Query | Route | Result |
|------|-------|-------|:---:|
| eval_001 | FastAPI middleware | official_only | PASS |
| eval_002 | internal corpus routing | internal_only | PASS |
| eval_003 | dual mixed query | dual | PASS |
| eval_004 | Chroma metadata (keyword) | official_only | PASS |
| eval_005 | bge-m3 decision (internal) | internal_only | PASS |
| eval_006 | query rewrite + session (history) | official_only | PASS |

### 指标

| 指标 | 值 |
|------|-----|
| total_cases | 6 |
| passed_cases | 6 |
| route_mode_accuracy | 1.0 |
| dual_cases_pass | true |
| citation_candidates_valid | true |
| all_cases_have_trace | true |

### 边界说明

- **Fixture eval vs 真实 retrieval eval**: 本阶段使用 fixture-based 轻量验证（keyword_bm25 fixture + vector channel trace），证明编排器、后处理链、citation 验证链正确。真实 embedding retrieval eval 需要在 HPC 上跑（有 Chroma + bge-m3），不属于本阶段范围。
- **不跑**: embedding、Chroma rebuild、HPC eval、真实 reranker。

## Smoke 回归结果 (8/8, 全部返回码 0)

| Smoke | 结果 |
|-------|:---:|
| Phase 5 LLM Provider | PASS |
| Phase 5 Custom Graph | PASS |
| Phase 5 Citation Guard | PASS |
| Phase 5 Grounded Answer | PASS |
| Phase 5B Graph API | PASS |
| Phase 6 Multi-channel Retrieval | PASS |
| Phase 6C PostProcessor | PASS (8/8 cases) |
| Phase 6D Retrieval Eval | PASS (6/6 cases) |

## 新增/修改文件

| 文件 | 操作 |
|------|------|
| `src/rag/postprocess.py` | 增强 (6 个函数 → tuple 返回 + trace) |
| `scripts/.../smoke_phase6c_postprocess.py` | 新增 |
| `scripts/.../smoke_phase6d_retrieval_eval.py` | 新增 |
| `reports/.../phase6c_postprocess_smoke.json` | 新增 |
| `reports/.../phase6d_retrieval_eval_smoke.json` | 新增 |
| `reports/.../phase6cd_checkpoint_report.md` | 新增 |

## 验收

| # | 标准 | 状态 |
|---|------|:---:|
| 1 | 所有新文件 py_compile 通过 | ✅ |
| 2 | Phase 6C + 6D 新增 smoke 返回码 0 | ✅ |
| 3 | 所有报告 overall_pass=true | ✅ (6C + 6D) |
| 4 | citation candidates chunk_id 来自 merged | ✅ |
| 5 | dual query 同时执行 official+internal channel | ✅ |
| 6 | postprocess_trace 包含去重/归一化/balance/citation | ✅ |
| 7 | 旧 smoke 不回退 (Phase 5 × 5 + Phase 6 × 1) | ✅ (6/6) |
| 8 | 不跑 embedding / Chroma rebuild / HPC eval | ✅ |

## 下一阶段建议

1. **Phase 6E**: 在 HPC 上跑真实 embedding retrieval eval（需要 Chroma + bge-m3）
2. **Phase 7**: Production-grade RAG answer pipeline（真实 LLM + reranker 可选）
3. **Phase 6F**: keyword_bm25_channel 升级为真实 BM25（需引入 rank_bm25 或 sklearn TfidfVectorizer）

## ZIP 可复现性

```
zip_type=full
independent_replay_supported=true
phase6c_return_code=0
phase6d_return_code=0
```

Fresh extract 验证通过:
```bash
cd <extract_dir>
PYTHONPATH=src python scripts/enterprise_kb_v1/smoke_phase6c_postprocess.py  # rc=0
PYTHONPATH=src python scripts/enterprise_kb_v1/smoke_phase6d_retrieval_eval.py  # rc=0
```

ZIP 包含完整依赖链: postprocess.py + search_channels (7 files) + orchestrator + custom_graph (4 files) + smoke scripts + reports.

**Phase 6C-6D v1.1: PASS.**
