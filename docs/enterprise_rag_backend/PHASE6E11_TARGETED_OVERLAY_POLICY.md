# Phase 6E-11: Targeted Overlay Retrieval Policy

## 1. 为什么需要 Targeted Overlay

Phase 6E-6/6E-8/6E-10 暴露了核心问题：

| Phase | Policy | 59 bad_case | 240 bad_case | 根因 |
|-------|--------|-----------|-------------|------|
| 6E-6 | global | 33 ✅ | 71 ❌ | mixed_zh_en_api -0.70 |
| 6E-8 | gated | 33 ✅ | 72 ❌ | 与 global 相同 |
| 6E-10 | conservative | 40 ❌ | 75 ❌ | 过于保守，两头落空 |

**一致的 degraders**: `mixed_zh_en_api` (-0.70), `code_api_config` (-0.10), `citation_required_query` (-0.05)
**一致的 improvers**: `exact_metadata_lookup` (+0.30), `short_keyword` (+0.10)

所有三个 policy 变体都是 **替换 baseline dense results**，而非 **补充**。

## 2. 设计原则

- **Baseline is sacred**: 所有 query 先跑 baseline dense retrieval
- **Overlay, not replace**: auxiliary results 与 baseline 合并，baseline top results 永远保留
- **Strong signal only**: 只有命中 ≥2 个强 metadata/code/citation 信号才启用 overlay
- **Non-target = noop**: zh_knowledge, en_api_doc, mixed_zh_en_api, agent_rag_concept 强制 baseline

## 3. 触发条件

| Overlay | 条件 | 目标类型 |
|---------|------|---------|
| `metadata_overlay` | ≥2 STRONG_METADATA_TERMS | exact_metadata_lookup |
| `sparse_overlay` | ≥2 STRONG_CODE_API_TERMS or code pattern | code_api_config/short_keyword |
| `citation_overlay` | ≥1 STRONG_CITATION_TERMS | citation_required_query |
| `noop` | 以上都不满足 | 所有其他类型 |

## 4. 本地验证结果

### 240-case overlay ratio: 17.5%（42/240）

| query_type | overlay | 状态 |
|-----------|---------|------|
| zh_knowledge | 0/20 (0%) | ✅ noop |
| en_api_doc | 0/20 (0%) | ✅ noop |
| mixed_zh_en_api | 0/20 (0%) | ✅ noop（消除 -0.70 退化） |
| agent_rag_concept | 0/20 (0%) | ✅ noop |
| exact_metadata_lookup | 11/20 (55%) | ✅ overlay |
| short_keyword | 8/20 (40%) | ✅ overlay |
| citation_required_query | 12/20 (60%) | ✅ overlay |

### 59-case overlay ratio: 32%（19/59）

- exact_metadata_lookup: 12/31
- citation_required_query: 4/5

### Critical probe

- FastAPI Request Body → `noop, baseline_only` ✅
- zh_knowledge → `noop, baseline_only` ✅

## 5. 预期 HPC 结果

- **240-case**: bad_case ≤ baseline (≤59)，消除 mixed_zh_en_api 退化
- **59-case**: bad_case 保持下降（部分 exact_metadata_lookup 受益于 overlay）
- **no regression on knowledge queries**

## 6. 边界说明

- 不声称生产上线
- 不声称所有 bad cases 已解决
- targeted_overlay 是 retrieval 优化，不改变 answer generation
- 240 bad_case_count <30 在当前 corpus 下不现实（corpus 覆盖不足、evaluator 规则严格）
