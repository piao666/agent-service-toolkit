# Phase 6E-4: HPC Re-evaluation Report

## 1. 代码同步

- Commit `35b2eb0` (phase-6e retrieval policy simulator) 已通过 scp 同步到 HPC
- HPC 项目路径: `<PROJECT_DIR>`
- Python: 3.11.15 (JupyterLab uv环境)

## 2. Phase 6E 文件清单

| 文件 | 状态 |
|------|------|
| `docs/enterprise_rag_backend/PHASE6E_RETRIEVAL_POLICY.md` | ✅ |
| `scripts/run_phase6e_policy_simulator.py` | ✅ |
| `src/rag/retrieval_policy.py` | ✅ |
| `src/rag/config.py` | ✅ (含 `ENTERPRISE_RAG_POLICY_MODE`) |
| `data/knowledge_base/evaluation/phase6e_remaining_bad_cases.jsonl` | ✅ |
| `data/knowledge_base/evaluation/phase6e_policy_simulation_summary.json` | ✅ |

## 3. Policy 接入状态

### 静态检查结果

```
src/rag/retrieval_policy.py:108 → select_retrieval_policy()   ← 仅定义
src/rag/config.py:28            → ENTERPRISE_RAG_POLICY_MODE   ← 仅声明
```

**结论：Policy 未接入 Agent/API 生产检索路径**

- `src/rag/retriever.py`: 未引用 `retrieval_policy`
- `src/agents/enterprise_tools.py`: 未引用 `retrieval_policy`
- `src/rag/config.py` 的 `ENTERPRISE_RAG_POLICY_MODE` 未在任何检索入口被读取
- 当前默认生产 Agent/API 行为仍为 baseline dense-only 检索

## 4. Offline Policy Simulator 结果

```
total_remaining_bad_cases:      59
simulated_improvable_count:     36
design_only_count:              13
requires_production_change_count: 59
recommended_phase6e4_eval:      true
writes_chroma:                  false
calls_llm:                      false
modifies_agent_api:             false
```

### by_recommended_policy

| Policy | Cases | 目标 query_type |
|--------|-------|----------------|
| metadata_first | 31 | exact_metadata_lookup |
| dense_sparse_fusion | 10 | phase6c_bad_case_regression |
| sparse_first_bm25 | 7 | code_api_config |
| clarification_first | 6 | ambiguous_query |
| citation_aware_evidence | 5 | citation_required_query |

### by_simulation_status

| Status | Count | 说明 |
|--------|-------|------|
| offline_rule_estimate | 36 | 可用离线策略改善 |
| baseline_reference | 10 | 基线对比组 |
| design_only | 13 | 需要代码级修改 |

## 5. API-level Evaluation 决策

**本轮不进行 Agent/API baseline vs query_type_aware 对比**，原因：

1. `query_type_aware` policy 是 offline helper/simulator，未接入生产 Agent/API
2. `enterprise_tools.py` 和 `retriever.py` 未读取 `ENTERPRISE_RAG_POLICY_MODE`
3. 启动服务并跑 `/enterprise/agent/query` 只会得到 baseline 结果，与 Phase 6D-9 相同
4. 强行跑不会产生有意义的 query_type_aware vs baseline 对比

## 6. 下一步

需要 **Phase 6E-5 Codex**: 将 `query_type_aware` policy wire into enterprise retrieval path behind feature flag:

- 在 `enterprise_tools.py` 的 `build_enterprise_retrieval_payload()` 中读取 `ENTERPRISE_RAG_POLICY_MODE`
- 当 `ENTERPRISE_RAG_POLICY_MODE=query_type_aware` 时调用 `select_retrieval_policy()`
- 根据 policy 选择 retrieval strategy (metadata_first / sparse_first / dense_sparse_fusion / etc.)
- 保持 `ENTERPRISE_RAG_POLICY_MODE=baseline` 为默认值，不改变生产行为

## 7. 合规确认

| 检查 | 状态 |
|------|------|
| 不调用 LLM | ✅ (offline simulator only) |
| 不写 Chroma | ✅ |
| 不启动长期服务 | ✅ |
| 不修改生产默认行为 | ✅ |
| 不 commit / push | ✅ |
| 不开始 Phase 6F | ✅ |
