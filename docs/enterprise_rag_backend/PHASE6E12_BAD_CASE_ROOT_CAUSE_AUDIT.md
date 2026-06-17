# Phase 6E-12: Bad Case Root Cause Audit + Evidence Coverage Diagnosis

## 1. Phase 6E 结果回顾

| Phase | Policy | 59 Δ | 240 Δ | 结论 |
|-------|--------|------|------|------|
| 6E-6 | global query_type_aware | -7 | +9 | 目标有效，全量退化 |
| 6E-8 | gated | -6 | +11 | =global |
| 6E-10 | conservative | 0 | +16 | 过于保守 |
| 6E-11 | targeted_overlay | -1 | — | 过于温和 |

## 2. 为什么 Retrieval Policy-Only 进入瓶颈

- Phase 6E-6 的 -7 改善全部来自 `exact_metadata_lookup` 类型（source_hit +0.30）
- `mixed_zh_en_api` 退化 -0.70 是固定伤害，无法通过 policy 规避
- 所有 policy 变体都**替换 baseline dense results**，而非真正**扩展检索能力**
- **retrieval strategy switching 天花板已触达**：最佳 case (-7) 后无法进一步改善

## 3. Root Cause 分布（59 cases）

| Root Cause | Count | % |
|-----------|-------|-----|
| **expected_source_exists_but_not_retrieved** | 43 | **73%** |
| chunk_too_noisy_or_too_broad | 31 | 53% |
| **needs_metadata_index** | 22 | 37% |
| chunk_too_small_or_context_missing | 7 | 12% |
| evaluator_too_strict_or_misaligned | 6 | 10% |
| needs_citation_verifier | 5 | 8% |
| needs_code_symbol_index | 4 | 7% |
| needs_query_decomposition | 3 | 5% |
| unknown | 1 | 2% |

> 73% 的 bad cases 是 **expected_source 存在但未被检索到**。不是 corpus 缺失问题，而是当前 dense-only retrieval 无法匹配特定查询类型。

## 4. Per-query-type 失败原因

| Query Type | Cases | 主要失败模式 |
|-----------|-------|------------|
| **exact_metadata_lookup** | 31 | source 存在但不被检索 + 需要 metadata index |
| phase6c_bad_case_regression | 10 | source 存在但不被检索 |
| code_api_config | 7 | source 存在但不被检索 + 需要 code index |
| ambiguous_query | 6 | evaluator 过严 + 需要 query decomposition |
| citation_required_query | 5 | 需要 citation verifier |

## 5. 哪些还能靠 Retrieval Policy 修？

**仅 7-10 cases**（Phase 6E-6 经验证）。剩余 33-36 cases 需要：
- metadata index（22 cases）
- code symbol index（4 cases）
- citation verifier（5 cases）
- query decomposition（3 cases）

## 6-9. 需要的结构化能力

| 能力 | Cases | 实现方式 |
|------|-------|---------|
| Metadata Index | 22 | Chroma metadata filter / SQLite metadata lookup |
| Code/Symbol Index | 4 | BM25F over code files / symbol extraction |
| Citation Verifier | 5 | Post-retrieval citation evidence check |
| Query Decomposition | 3 | Multi-query decomposition for multi-hop |

## 10. Evaluator Calibration

6 cases (ambiguous_query) 的 expected_source_id 要求可能过严。Phase 6D-9 已部分校准，但仍需人工 review。

## 11. 240 bad_case_count <30 是否现实？

**不现实**。当前 best case (6E-6) 240 bad = 71。即使完全解决 59 remaining cases，理论上限 ~71-59+remaining = ~12-20 bad cases 可通过纯 retrieval 解决。240 <30 需要：
- Structured metadata index (22 cases)
- Code symbol index (4 cases)
- Citation verifier (5 cases)
- Corpus expansion for phase6c regression cases
- 以上全部实现后 theoretical floor ≈ 30-40

## 12. 下一阶段建议

**Phase 6F: Structured Retrieval Infrastructure**
- 6F-1: Metadata exact-match index (solves exact_metadata_lookup)
- 6F-2: Code/config symbol index (solves code_api_config)
- 6F-3: Citation evidence verifier (solves citation_required_query)
- 6F-4: Query decomposition for multi-hop
- 6F-5: Corpus expansion audit (solves phase6c_bad_case_regression)
