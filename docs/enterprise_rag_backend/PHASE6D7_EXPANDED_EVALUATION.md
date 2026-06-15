# Phase 6D-7: Expanded Evaluation Set + HPC Full Re-validation

## 1. 为什么从 72/40 cases 扩展到 240 cases

Phase 6D-4 全量测试（72 cases, 575 chunks）发现了有价值的趋势，但样本量不足：
- 每个 query_type 仅 8 条 case，统计学意义有限
- 缺少 multi_hop、ambiguous、citation_required 等关键检索类型
- exact_metadata_lookup 和 phase6c_bad_case_regression 是老大难类型，需要更多 case 确认
- Qwen3-Reranker 在 72 cases 上未显优势，需要更大样本确认

Phase 6D-7 将评估集扩展至 240 cases（12 类 × 20），为 Phase 6D 结论提供统计学意义支撑。

## 2. 12 类 query_type 设计

| # | query_type | 设计目的 | case数 |
|---|-----------|---------|--------|
| T01 | zh_knowledge | 中文深度学习/NLP 知识检索 | 20 |
| T02 | en_api_doc | 英文 API 文档查询 | 20 |
| T03 | mixed_zh_en_api | 中英混合 API 查询 | 20 |
| T04 | agent_rag_concept | Agent/RAG 概念理解 | 20 |
| T05 | exact_metadata_lookup | 精确元数据/字段查询 | 20 |
| T06 | code_api_config | 代码配置/常量值查询 | 20 |
| T07 | short_keyword | 短关键词/术语查询 | 20 |
| T08 | negative_banned_source | 负向 banned 源测试 | 20 |
| T09 | phase6c_bad_case_regression | Phase 6C bad cases 回归 | 20 |
| T10 | multi_hop_lookup | 跨文档链式查询 | 20 |
| T11 | ambiguous_query | 故意模糊/开放查询 | 20 |
| T12 | citation_required_query | 要求引用特定来源 | 20 |

生成方式：复用 Phase 6D-4 72 条 + agent_api 补充 + 手写 harder variants + 全手写 3 个新类型。不调用 LLM。

## 3. Embedding 复验结果

HPC: NVIDIA L40 11GB, PyTorch 2.6.0+cu124, Python 3.9, batch_size=8

| 模型 | source_hit@5 | MRR | vs Phase 6D-4 (72 cases) |
|------|-------------|-----|--------------------------|
| **qwen3-embedding-0.6b** | **0.8373** | **0.7224** 🥇 | 1.0→0.8373 (harder cases 导致下降) |
| bge-m3 | 0.6986 | 0.5908 🥈 | 0.7969→0.6986 |
| bge-small-zh-v1.5 | 0.6938 | 0.5533 🥉 | 0.8125→0.6938 |

**确认**: qwen3-embedding-0.6b 仍然是压倒性最强的 embedding model（MRR 领先 bge-m3 22%）。

## 4. Retrieval Strategy 复验结果

基于 bge-small-zh-v1.5，5 种策略 × 240 cases：

| 策略 | source_hit@5 | MRR | vs dense 基线 |
|------|-------------|-----|---------------|
| **sparse_bm25** | **0.7273** | **0.6341** 🥇 | **+14.6%** |
| dense_only | 0.6938 | 0.5533 | baseline |
| hybrid_weighted | 0.6459 | 0.5513 | -0.36% |
| hybrid_rrf | 0.6124 | 0.5375 | -2.85% |
| exact_match | 0.5837 | 0.5065 | -8.45% |

**关键发现**: sparse_bm25 在 240 harder cases 上**碾压所有策略**，甚至比 hybrid 融合更好。此发现推翻了 Phase 6D-3 中 "hybrid ≥ dense ≥ sparse" 的初步结论。

## 5. Reranker 复验结果

### bge-reranker-base (batch=8, candidate_pool=20, 212ms avg)

| 指标 | before | after | delta |
|------|--------|-------|-------|
| source_hit@5 | 0.6459 | **0.6699** | **+2.4%** |
| top1_source_hit | 0.488 | **0.5311** | **+4.3%** |
| MRR | 0.5513 | **0.5799** | **+2.86%** |
| improved/degraded/unchanged | — | 27/22/191 | net +5 |

### Qwen3-Reranker-0.6B (batch=1, candidate_pool=10, 700ms avg)

| 指标 | before | after | delta |
|------|--------|-------|-------|
| source_hit@5 | 0.6459 | 0.6172 | **-2.87%** |
| top1_source_hit | 0.488 | 0.4833 | -0.47% |
| MRR | 0.5513 | 0.5348 | **-1.65%** |
| improved/degraded/unchanged | — | 17/30/193 | net -13 |

**关键发现**:
- **bge-reranker-base 首次确认正向改善**：在 240 harder cases 上 MRR +2.86%，top1 +4.3%
- **Qwen3-Reranker 确认不适合此任务**：在 240 cases 上 MRR -1.65%，与 Phase 6D-4 结论一致且统计学更显著
- bge-reranker-base 的 candidate_pool=20 coverage (0.7751) 远高于 Qwen3 的 pool=10 (0.7129)

## 6. Agent/API 复验结果

### 诊断过程

- **初始问题**: Phase 6D-7 首次 Agent/API eval 因 `api_available=False` 被 skipped
- **根因**: Claude Code 误用默认 Python 3.9 (d2lbook conda env)，而项目需 Python ≥3.11
- **解决**: 定位 JupyterLab 中 Python 3.11 kernel (uv环境) → `/home/.../HM/jupyter/.venv/bin/python`
- **依赖安装**: pip install fastapi uvicorn langchain-* chromadb sentence-transformers 等
- **LLM provider**: 使用 `USE_FAKE_MODEL=true` (FakeListChatModel)，不调用真实 LLM
- **Chroma**: `/tmp/chroma_phase6d7_runtime`，575 chunks，`enterprise_ai_learning_kb_reviewed`
- **DB**: `DATABASE_TYPE=sqlite` 绕过 MongoDB 依赖

### 服务状态

| 指标 | 值 |
|------|-----|
| app import | ✅ FastAPI |
| `/health` | ✅ `{"status":"ok"}` |
| `/enterprise/agent/query` | ✅ POST |
| 服务启动 | ✅ uvicorn on 0.0.0.0:8000 |

### 20-case Smoke Test

| 指标 | 值 |
|------|-----|
| request_success_rate | **1.0** (100%) |
| response_schema_valid_rate | **1.0** (100%) |
| source_hit_rate | **0.95** (95%) |
| keyword_hit_rate | 0.85 |
| avg_latency_ms | 136.8 |
| error_count | **0** |
| bad_case_count | 4 |

### 240-case Full Eval

| 指标 | 值 |
|------|-----|
| case_count | 240 |
| request_success_rate | **1.0** (100%) |
| response_schema_valid_rate | **1.0** (100%) |
| answer_non_empty_rate | **1.0** (100%) |
| citation_present_rate | **1.0** (100%) |
| source_hit_rate | **0.689** |
| keyword_hit_rate | 0.56 |
| avg_latency_ms | **132.6** |
| error_count | **0** |
| timeout_count | **0** |
| bad_case_count | 116 |

> ⚠️ answer 由 FakeListChatModel 生成 ("This is a test response from the fake model")，不反映真实 Agent answer quality。但 transport/schema/retrieval pipeline 已完整验证。

## 7. Phase 6D 前置结论验证

| Phase 6D 结论 | Phase 6D-7 验证 | 状态 |
|--------------|----------------|------|
| qwen3-embedding-0.6b 最强 | MRR=0.7224，领先第二名 22% | ✅ 确认 |
| bge-reranker-base 未显著改善 MRR | MRR +2.86%，top1 +4.3% | ⚠️ **推翻** — 240 cases 首次确认改善 |
| Qwen3-Reranker 不稳定/恶化 | MRR -1.65%，degraded=30 | ✅ 确认（更显著） |
| exact_metadata_lookup 是弱项 | 仍然是，sparse_bm25 部分缓解 | ✅ 确认 |
| hybrid ≥ dense ≥ sparse | sparse_bm25 碾压所有策略 | ⚠️ **推翻** — sparse 更强 |

## 8. 被确认的结论

1. **qwen3-embedding-0.6b 是项目最强 embedding model**，应在后续 Phase 优先采用
2. **Qwen3-Reranker 不适合当前任务**（score.weight 未训练，MRR 下降，latency 700ms）
3. **exact_metadata_lookup / phase6c_bad_case_regression 是持续难点**

## 9. 被推翻的结论

1. **bge-reranker-base 无效果** → 在 240 harder cases 上确认 **正向改善**（MRR +2.86%）
2. **hybrid 策略优于单一策略** → **sparse_bm25 单策略最优**（MRR=0.6341 vs hybrid=0.5513）

## 10. 剩余 Bad Cases 分析

从 Phase 6C bad cases 纳入回归的 4 条（qa_006, qa_017, qa_023, qa_024）在 240-case expanded set 中的表现待详细分析（需读取 results JSONL）。初步判断：
- qa_006 ("PyTorch 训练步骤") 和 qa_017 ("RAG 幻觉") 可能是 source coverage 问题
- qa_023 ("manifest 审查") 和 qa_024 ("Phase 6B-2 评估") 可能是 chunk granularity 问题

## 11. 未声明事项

- 不声称生产上线
- 不声称高并发压测完成
- 不声称所有问题解决
- Agent/API eval 未完成（HPC 无 LLM provider）
- Reranker 改善幅度有限（+2.86% MRR），需权衡 latency 成本（+212ms）

## 12. 建议下一步

1. **Phase 6E**: 基于 Phase 6D-7 结论，将 qwen3-embedding-0.6b 和 bge-reranker-base 接入生产 pipeline
2. **稀疏检索集成**: sparse_bm25 在 240 cases 上表现最佳，应评估接入生产 retriever
3. **Agent/API 复验**: 在配置了 LLM provider 的环境中补跑 Phase 6D-7 Agent/API eval
4. **扩展 bad cases**: 分析 Phase 6D-7 新增的 168 条 harder cases 中的失败模式
