# Phase 6F Final Closure

## 1. Phase 6F 完成内容

Phase 6F 从 metadata/symbol index 构建开始，逐步实现了 structured retrieval infrastructure，最终在 HPC 上完成全量 API-level 验证。

| Sub-phase | 内容 | 关键结果 |
|-----------|------|---------|
| 6F-0/1 | Metadata index (6 sources, 607 chunks) | ✅ |
| 6F-2 | Symbol index (1712 symbols, 698 unique) | ✅ |
| 6F-3 | Structured probe: 94.9% hit rate | ✅ |
| 6F-4 | Feature flag wiring (ENTERPRISE_STRUCTURED_RETRIEVAL_MODE) | ✅ |
| 6F-5 | HPC 59-case: structured debug only, no improvement | ❌ |
| 6F-6 | Score boost injection: still no improvement | ❌ |
| 6F-7 | Candidate materialization + real injection: 59-case bad 32 (-8) | ✅ |
| 6F-8 | Fix Chroma crash, rerun 240: **bad 49 (-10)**, source 0.751 | 🥇 |
| 6F-9 | Low-risk refinement: bad 50 (-1 regression) | ❌ |
| 6F-10 | Failure boundary analysis: retrieval fixable only 10 cases | 诊断 |

## 2. Phase 6F-8 最佳结果

| 指标 | baseline | 6F-8 structured | Δ |
|------|----------|---------------|-----|
| 59 bad_case | 40 | 33 | −7 |
| 240 bad_case | 59 | **49** | **−10** |
| 240 source_hit | 0.694 | **0.751** | +5.7% |
| 240 error | 0 | 0 | ✅ |

## 3. Case Delta Matrix

| Delta | Count | 说明 |
|-------|-------|------|
| baseline_fail_6f8_pass | 12 | 6F-8 修复 |
| baseline_pass_6f8_fail | 1 | 6F-8 误伤 |
| sixf8_pass_6f9_fail | 1 | 6F-9 退化 |
| sixf8_fail_6f9_pass | 0 | 6F-9 无修复 |

## 4. 剩余 Bad Cases 分布

| 类型 | 数量 | 失败层 |
|------|------|--------|
| phase6c_bad_case_regression | 14 | retrieval + generation |
| code_api_config | 7 | code_symbol_index |
| citation_required_query | 8 | citation_verifier |
| multi_hop_lookup | 7 | query_decomposition |
| short_keyword | 5 | sparse/BM25 |
| exact_metadata_lookup | 3 | metadata_index |
| mixed_zh_en_api | 3 | generation/evaluator |

## 5. Phase 6F 核心结论

1. ✅ Structured candidate materialization 首次把 240 bad_case 降到 50 以下
2. ✅ source_hit 首次超过 0.75
3. ❌ 低风险 refinement (6F-9) 没有改善，反而轻微退化
4. ❌ 继续做 retrieval refinement 的收益已经很低（6F-10: retrieval_still_fixable=10）
5. 🥇 **Phase 6F-8 作为全阶段最佳版本，应保留**

## 6. 不应继续做的事

- 继续调 retrieval policy / gate / sparse 权重 / overlay 权重
- 继续调 metadata/symbol ranker boost level
- 为追求 240 bad <30 而反复迭代 retrieval-only fix

## 7. 下一阶段：Phase 6G

Phase 6G 重点不再是 retrieval ranking，而是：

1. **Citation verifier**: 对 citation_required_query 做 evidence 验证
2. **Answer evidence grounding**: 确保 Agent answer 确实引用 retrieved sources
3. **Evaluator calibration**: 修复 ambiguous_query / negative_banned_source 等类型的 metric 过严
4. **Code/config index 精修**: 提升 code_api_config 类型的 source_hit
5. **Multi-hop query decomposition**: 分解 multi_hop_lookup 为子查询
6. **Chunk/evidence cleanup**: 过滤导航/样板文本噪声

## 8. 不声称事项

- 不声称生产上线
- 不声称所有 bad cases 已解决
- 不声称 240 bad_case <30
- 不声称 retrieval pipeline 已完备
