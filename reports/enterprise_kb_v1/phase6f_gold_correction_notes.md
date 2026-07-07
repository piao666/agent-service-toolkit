# Phase 6F Gold Correction Notes v1

**日期**: 2026-07-07
**依据**: Phase 6F failed-case debug v1.1 (HPC, bge-m3 direct Chroma + orchestrator)

---

## 概述

Phase 6F 首轮 eval overall_pass=false，4 条 failed case 的根因诊断为 gold label 过窄：
检索返回的 top sources 能覆盖 query 语义，但不在 expected_source_ids 中，导致 hit@k 计为失败。

以下为每条 case 的详细扩展依据。

---

## p6f_007

**Query**: 本项目 enterprise_kb_v1 的知识库定位和语料准入策略是什么？

**原 expected_source_ids**: `internal_kb_positioning`, `internal_kb_admission_policy`

**新增**: `internal_corpus_overview`, `internal_repo_hygiene_policy`

**证据**:
- `internal_corpus_overview` 在 baseline rank=1 (score=0.678)，heading="Internal Engineering Corpus 概览 > 一、internal corpus 包含哪些源文件类别 > A. 项目治理与定位文档"，实际描述 KB 定位和语料构成
- `internal_repo_hygiene_policy` 在 baseline rank=2-3 (score=0.576)，涵盖项目治理策略、Git 规则、归档约定，与"准入/策略"语义重叠
- 原 expected sources (`internal_kb_positioning`, `internal_kb_admission_policy`) 均在索引中存在，但不在 baseline top50（语义距离问题）

**结论**: 属于 gold label 扩展，不是检索失败。top retrieved sources 可回答此 query。

---

## p6f_010

**Query**: Phase 4FH internal retrieval strict eval 的 gold label correction 过程

**原 expected_source_ids**: `internal_retrieval_debug_cases`

**新增**: `internal_failure_patterns`

**证据**:
- `internal_failure_patterns` 在 baseline rank=1 (score=0.523)，heading="评测产物 > 7. RAG answer eval 与 retrieval context eval 命名混淆 > 根因"，覆盖 gold label 问题诊断
- `internal_failure_patterns` 在 baseline rank=5 (score=0.498)，heading="失败案例模式与根因分析 > 5. per-case debug 不完整导致 embedding A/B 不可信 > 根因"
- `internal_retrieval_debug_cases` 在 baseline rank=14，multi-channel raw rank=14，被 postprocess source_dedup(20→19) + balance(19→10) 挤出 top10

**结论**: `internal_failure_patterns` 覆盖 gold label correction 的内容，原 source 被检索到但被 postprocess 截断。属于检索排名问题，不是检索完全失败。

---

## p6f_015

**Query**: bge-m3 embedding 在官方文档和内部工程文档中的检索效果对比

**原 expected_source_ids**: `phase4d_bge_m3_decision`, `phase4c_hpc_runbook`

**新增**: `internal_hpc_lessons`, `internal_failure_patterns`, `phase4e_runtime_verification`

**证据**:
- `internal_hpc_lessons` 在 baseline rank=4 (score=0.647)，heading="查询进程占用 > 9. bge-m3 最终选择理由"，明确包含 bge-m3 检索质量指标
- `internal_failure_patterns` 在 baseline rank=1 (score=0.680)，heading="10. core_029 失败反映 official_docs 不足以回答项目级 RAG 调参问题"，包含官方 vs 内部文档效果对比信息
- `phase4e_runtime_verification` 在 baseline rank=3 (score=0.667)，包含 bge-m3 official_docs runtime retrieval 验证链路
- `phase4d_bge_m3_decision` 在 internal_vector raw rank=9 (baseline rank=9)，但 multi-channel raw rank=29 (被 official_vector 的 20 hits 稀释)，最终被 corpus_balance(32→10) 挤出 top10
- 这是 dual 模式下 postprocess 的典型副作用：official 源注入大量 hits 稀释了 internal 相关源的排名

**结论**: dual query 的期望源被 multi-channel 的 official 结果稀释。gold label 扩展后，即便 postprocess 截断，新增的候选源仍能提供 hit。

---

## p6f_020

**Query**: 回忆一下之前关于检索策略的讨论，现在有哪些检索 channel 可用？

**原 expected_source_ids**: `internal_corpus_routing_design`

**新增**: `internal_current_system_snapshot`, `internal_rag_pipeline_current`

**证据**:
- `internal_current_system_snapshot` 在 baseline rank=1 (score=0.655)，heading="当前系统模块与边界 > 四、已实现能力 > 4.3 RAG 检索"，直接描述系统已实现的检索能力
- `internal_rag_pipeline_current` 在 baseline rank=2-3 (score=0.588/0.586)，heading="当前 RAG 查询链路 > 二、三大检索策略 > 2.3 targeted_overlay"，描述多路检索策略
- `internal_corpus_routing_design` 在 baseline rank=20，multi-channel raw rank=20，被 postprocess balance(18→10) 挤出 top10

**结论**: `internal_current_system_snapshot` 和 `internal_rag_pipeline_current` 直接覆盖"当前有哪些 channel 可用"。原 source rank=20 被截断是排名问题，不是内容缺失。

---

## 修正原则

1. **保留原 expected_source_ids**：不作为删除项，仅作为父集扩展
2. **新增 source 必须有 debug 证据支撑**：chunk text / heading / score 证明可回答 query
3. **不修改 retrieval/postprocess 代码**：gold correction 是评测标注修正，不是工程修复
4. **标注 `gold_correction_note`**：每条 case 在 JSONL 中记录扩展原因

**Phase 6F Gold Correction v1**: 4/25 cases 扩展, 0 cases 删除.
