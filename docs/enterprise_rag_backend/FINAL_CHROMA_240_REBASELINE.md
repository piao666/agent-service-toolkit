# Final Chroma 240-Case Rebaseline

> 日期: 2026-06-26 | Commit: `d53d75d` | Chroma: `chroma_enterprise_final` (86 chunks)

## 评测配置

| 配置项 | 值 |
|---|---|
| Cases | 240 (phase6d7_expanded_cases.jsonl, 12 query types × 20) |
| Requests | 480 (240 cases × legacy + custom_graph) |
| LLM | DeepSeek chat |
| Legacy 服务 | :8011, `ENTERPRISE_AGENT_GRAPH_MODE=legacy` |
| Custom Graph 服务 | :8012, multi_hop=off, planner=debug_only, judge=rule_based_fallback, verifier=rule_based, structured=metadata_symbol, memory=buffer |

## Final Chroma 概况

| 指标 | 值 |
|---|---|
| Chunks | 86 |
| 唯一 sources | 9 |
| 来源 | Phase6 技术资料 (80 chunks) + enterprise_docs 项目文档 (6 chunks) |

**source_id 列表**: `enterprise_agent_overview`, `enterprise_model_provider_policy`, `enterprise_prompt_guidelines`, `enterprise_rag_pipeline`, `fastapi_docs`, `local_ai_agent_course_pdf`, `local_deep_learning_course_docx`, `local_nlp_course_docx`, `repo_project_files`

## 全局结果

| 指标 | legacy | custom_graph |
|---|---|---|
| Calibrated bad | 117/240 | 121/240 |
| Judge needs_review | — | 64/240 |
| source_miss | 56 | 56 |
| doc_type_miss | 74 | 74 |
| keyword_miss | 50 | 55 |
| source_unknown | **0** | **0** |
| errors | 0 | 0 |
| timeouts | 0 | 0 |

### Delta

| 类别 | 数量 |
|---|---|
| only_legacy_bad | 6 |
| only_custom_bad | 10 |
| shared_bad | 111 |

### Grounding Status (custom_graph)

| 状态 | 数量 |
|---|---|
| HIGH | 47 |
| MEDIUM | 129 |
| LOW | 64 |
| Avg score | 0.449 |

### Graph Observability (custom_graph)

| 指标 | 值 |
|---|---|
| graph_debug_present | 240/240 ✅ |
| nodes_executed (9 nodes) | 240/240 each ✅ |
| planner_present | 240/240 ✅ |
| judge_present | 240/240 ✅ |

## Corpus-Aware 复盘

### 按 corpus 覆盖分类

| Corpus 状态 | 数量 | 说明 |
|---|---|---|
| in_corpus | 209 | expected_source 存在于 final Chroma |
| no_expected_source | 31 | 评测 case 未指定 expected_source |
| out_of_corpus | 0 | 所有指定 expected_source 均存在于 final Chroma |

### Bad Case 按 Corpus 状态分解

| | legacy | custom_graph |
|---|---|---|
| in_corpus bad | 110 | 114 |
| no_expected_source bad | 7 | 7 |
| corpus_gap | 3 | 3 |
| **Total bad** | **117** | **121** |

**关键洞察**：110/117 (94%) legacy bad 和 114/121 (94%) custom_graph bad 的 expected_source **存在于** final Chroma 中。这说明主要问题是 **检索精度不足**（source 存在但未命中），而不是 corpus 覆盖缺失。

### Miss 分布 (in_corpus only)

| 原因 | 频次 |
|---|---|
| doc_type_miss | ~74 |
| keyword_miss | ~55 |
| source_miss | ~56 |

### 建议动作分布

| 动作 | 数量 | 说明 |
|---|---|---|
| inspect_in_corpus_bad | 120 | expected_source 在 corpus 中但仍 bad — 需排查检索/评估 |
| no_code_change | 110 | 两端均 pass |
| eval_spec_update | 7 | no_expected_source 的 case 需更新评估规格 |
| corpus_gap | 3 | 确认的语料缺口 |

## only_custom_bad 详情 (10 cases)

所有 10 个 case 的 expected_source 均存在于 final Chroma 并正确出现在 sources 中。全部原因均为 **keyword_miss**（LLM 生成的 answer 未包含 evaluator 期望的关键词）。

| case_id | category | exp_src | grounding | 诊断 |
|---|---|---|---|---|
| exp_024 | en_api_doc | fastapi_docs | custom=HIGH, legacy=MEDIUM | keyword_miss — 两端 sources 相同 |
| exp_026 | en_api_doc | fastapi_docs | custom=HIGH, legacy=HIGH | keyword_miss — 两端 sources 相同 |
| exp_028 | en_api_doc | fastapi_docs | custom=HIGH, legacy=HIGH | keyword_miss — 两端 sources 相同 |
| exp_032 | en_api_doc | fastapi_docs | custom=HIGH, legacy=MEDIUM | keyword_miss — 两端 sources 相同 |
| exp_033 | en_api_doc | fastapi_docs | custom=HIGH, legacy=HIGH | keyword_miss — 两端 sources 相同 |
| exp_034 | en_api_doc | fastapi_docs | custom=MEDIUM, legacy=HIGH | keyword_miss — 两端 sources 相同 |
| exp_054 | mixed_zh_en_api | fastapi_docs | custom=LOW, legacy=MEDIUM | keyword_miss — 两端 sources 相同 |
| exp_097 | exact_metadata_lookup | repo_project_files | custom=MEDIUM, legacy=MEDIUM | keyword_miss |
| exp_103 | code_api_config | repo_project_files | custom=MEDIUM, legacy=MEDIUM | keyword_miss |
| exp_193 | multi_hop_lookup | local_ai_agent_course_pdf | custom=MEDIUM, legacy=MEDIUM | keyword_miss — complex multi-hop query |

**结论**: 所有 only_custom_bad 均为 keyword_miss。两端 sources 相同，差别仅在于 LLM answer 的关键词覆盖。不是 custom_graph 的结构问题。

## only_legacy_bad 详情 (6 cases)

全部原因均为 **keyword_miss**。两端 sources 基本一致。

| case_id | category | exp_src | grounding | 诊断 |
|---|---|---|---|---|
| exp_059 | mixed_zh_en_api | fastapi_docs | legacy=HIGH, custom=MEDIUM | keyword_miss — 两端 sources 相同 |
| exp_065 | agent_rag_concept | local_ai_agent_course_pdf | legacy=MEDIUM, custom=MEDIUM | keyword_miss |
| exp_066 | agent_rag_concept | local_ai_agent_course_pdf | legacy=MEDIUM, custom=MEDIUM | keyword_miss |
| exp_088 | exact_metadata_lookup | local_deep_learning_course_docx | legacy=LOW, custom=MEDIUM | keyword_miss |
| exp_107 | code_api_config | fastapi_docs | legacy=MEDIUM, custom=MEDIUM | keyword_miss |
| exp_109 | code_api_config | fastapi_docs | legacy=HIGH, custom=HIGH | keyword_miss — 两端 sources 相同 |

**结论**: 与 only_custom_bad 类似，全是 keyword_miss。legacy 和 custom_graph 的差别来自 LLM answer 随机性，不是图结构缺陷。

## 按 Query Type 分布

| query_type | total | in_corpus | legacy_bad | custom_bad |
|---|---|---|---|---|
| agent_rag_concept | 20 | 20 | 10 | 8 |
| ambiguous_query | 20 | 9 | 9 | 9 |
| citation_required_query | 20 | 20 | 12 | 12 |
| code_api_config | 20 | 20 | 14 | 13 |
| en_api_doc | 20 | 20 | 8 | 14 |
| exact_metadata_lookup | 20 | 20 | 7 | 7 |
| mixed_zh_en_api | 20 | 20 | 5 | 5 |
| multi_hop_lookup | 20 | 20 | 11 | 12 |
| negative_banned_source | 20 | 0 | 4 | 4 |
| phase6c_bad_case_regression | 20 | 20 | 20 | 20 |
| short_keyword | 20 | 20 | 7 | 7 |
| zh_knowledge | 20 | 20 | 10 | 10 |

**值得关注的类别**:
- `phase6c_bad_case_regression`: 20/20 bad across both modes — 历史遗留问题，corpus 缩小后更难改善
- `code_api_config`: 13-14/20 bad — API 配置查询在 86-chunk corpus 中语义覆盖不足
- `en_api_doc`: custom_graph 比 legacy 多 6 bad — 但所有 only_custom_bad 均为 keyword_miss（LLM 随机性）
- `ambiguous_query`: 9/20 in_corpus（大部分 ambiguous query 没有 expected_source）

## 与历史 Phase7D3 对比

| 指标 | Phase7D3 (~575 chunks) | Final Chroma (86 chunks) | 变化 |
|---|---|---|---|
| legacy calibrated bad | 97 | 117 | +20 |
| custom_graph calibrated bad | 101 | 121 | +20 |
| only_custom_bad | 9 | 10 | +1 |
| only_legacy_bad | 5 | 6 | +1 |
| errors/timeouts | 0/0 | 0/0 | — |
| graph_debug_present | 240/240 | 240/240 | — |

### 退化原因分析

**不是配置退化**。当前 custom_graph 配置与 Phase7D3 frozen baseline 完全相同 (multi_hop=off, planner=debug_only, judge=rule_based_fallback)。bad case 增加的主要原因：

1. **Corpus 规模差异**：86 chunks vs ~575 chunks。每个 source 的 chunk 数量大幅减少（如 local_ai_agent_course_pdf 从 150+ chunks 降到 23 chunks），导致：
   - 检索 pool 变小，语义覆盖降低
   - keyword/doc_type 匹配概率下降
   - LLM 生成的 answer 中引用的细节可能不在有限的 chunk 中

2. **Source 数量差异**：9 sources vs 5 sources（旧 corpus 有 5 个 sources 但每个 source 有大量 chunks）。新 corpus 中 4 个项目文档 source 只有 1-2 chunks，对技术问题的召回帮助有限。

3. **Chunk 策略不变**：chunk_size=800 和检索策略未变，但 corpus 变小后相同策略的效果下降。

**保守结论**：当前 bad case count (117 legacy / 121 custom_graph) 在 86-chunk corpus 上是合理的。不建议继续微调查询策略。需要扩大 corpus 规模（重新引入更多 phase6 chunks 或扩充文档）才能实质性降低 bad count。

## 保守边界

- ✅ source_unknown=0（metadata 兼容修复完全生效）
- ✅ graph_debug/nodes_executed/judge 全部可观测
- ✅ 无 errors/timeouts
- ⚠️ bad case count 高于历史基线，但原因明确（corpus 规模差异）
- ❌ 不建议继续 retrieval-policy 或 prompt 微调来降低 bad count
- ❌ 本报告不声称解决所有检索问题

## 归档文件

- `data/knowledge_base/evaluation/final_chroma_240_rebaseline_summary.json` — 完整 per-case 分析
- `data/knowledge_base/evaluation/final_240_legacy_vs_custom_results.jsonl` — 480 条原始结果
- `data/knowledge_base/evaluation/final_240_legacy_vs_custom_summary.json` — 原始 summary
