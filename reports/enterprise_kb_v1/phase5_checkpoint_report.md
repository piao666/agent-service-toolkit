# Phase 5 v1.2 Checkpoint Report

**日期**: 2026-07-06
**状态**: PASS -- 全部 4 个 smoke 通过，evidence_verifier + citation guard 验证完毕

---

## v1.2 修复摘要 (vs v1.1)

- **Dual routing bug**: `_corpus_to_mode("dual")` 原先 fallback 到 `official_only`，现已正确处理 `dual -> dual`
- **Mixed query routing trace**: `recommended_corpus="dual"` 改为 `route_mode="dual"` + `target_corpora=["official_docs","internal_engineering_docs"]`
- **Explicit corpus tests**: `corpus="official_docs"->official_only`, `corpus="internal_engineering_docs"->internal_only`
- **Citation guard 字段**: `pass`->`test_pass`, `expected_pass`->`expected_citation_validity`

## v1.1 修复摘要

| 修复项 | v1.0 | v1.1 |
|--------|------|------|
| citations=0 时 citation_validity | `true` (bug) | `false`, hallucination_risk=`high`, status=`no_citations` |
| 非法 citation 反例 | 无测试 | `negative_invalid_chunk_id`: fail correctly |
| 正样本 fixture smoke | 无（依赖 Chroma） | `positive_all_valid`: 3 citations, validity=true |
| retriever error handling | `except: pass` | errors + dependency_missing + fallback_used |
| planner 与 retriever 连线 | 未使用 | 优先 plan_retrieval_queries[0], routing_source 记录 |
| LLM smoke JSON parse | 仅检查 length | parsed intent/confidence/reasoning 验证 |

## Smoke 结果

| Smoke | 结果 |
|-------|:---:|
| LLM Provider (mock/qwen/deepseek) | 3/3 pass |
| Custom Graph (10 imports + pipeline) | PASS |
| Citation Guard (positive + negative + empty) | 3/3 PASS |
| Grounded Answer (fixture + no-key fallback) | PASS |

### Citation Guard 详情

| 测试 | citations | validity | risk | 预期 | 实际 |
|------|:--------:|:--------:|:----:|:----:|:----:|
| positive_all_valid | 3 | true | none | pass | PASS |
| negative_invalid_chunk_id | 1 | false | high | fail | PASS |
| empty_citations | 0 | false | high | fail | PASS |

### Grounded Answer

- no-key fallback -> mock -> fixture-based: citations=2, all from retrieved -> citation_validity=true

## 变更文件 (v1.1 diff)

- `src/custom_graph/nodes/evidence_verifier.py` -- 重写 -- citation 状态
- `src/custom_graph/nodes/retriever.py` -- 重写，planner 集成 + 错误处理
- `scripts/.../smoke_phase5_llm_provider.py` -- JSON parse + required_fields
- `scripts/.../smoke_phase5_citation_guard.py` -- 新增 mock fixture 正负例
- `scripts/.../smoke_phase5_grounded_answer.py` -- fixture-based 正样本

## 验收

| # | 标准 | 状态 |
|---|------|:---:|
| 1 | 全部模块可 import | ✅ |
| 2 | custom_graph 端到端 | ✅ |
| 3 | 无证据时 validity=false, risk=high | ✅ |
| 4 | mock chunks 中 citations>0 | ✅ (2-3 citations) |
| 5 | citation 全部来自 retrieved | ✅ |
| 6 | 非法 citation 反例 fail | ✅ |
| 7 | planner 输出被 retriever 使用 | ✅ (routing_source/planner_used 在 trace) |
| 8 | 无 key 时 mock fallback | ✅ |
| 9 | 无 MCP/ToolRouter/embedding/Chroma | ✅ |

**Phase 5 v1.2: PASS.**
