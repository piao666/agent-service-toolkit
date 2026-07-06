# Phase 6F v1.1 Checkpoint Report (Prep)

**日期**: 2026-07-07
**状态**: CONFIG SMOKE PASS — 待 HPC 运行

---

## v1.1 修复 (vs v1.0)

| 修复项 | v1.0 | v1.1 |
|--------|------|------|
| 索引缺失策略 | 两个都缺才 fatal | **任一缺失 → fatal** (含 count=0) |
| route metric 语义 | `route_accuracy` (误导性) | `route_execution_accuracy_given_gold_route` + 注释 |
| citation empty | 默认 valid=true | `no_candidates_with_hits` → false, `not_applicable` → 不计分母 |
| overall_pass | 只检查 failed_case 阈值 | + indices_ready, citation_ok, dual_ok, hit_degraded 警告 |
| case 分布 | 手写错误 (6/7/5...) | 自动统计 JSONL → 写入报告 |
| config smoke | 4 项基础检查 | + 4 项逻辑语义检查 |

## Cases 覆盖 (25 条，自动统计)

| case_type | 数量 |
|-----------|:---:|
| official_only | 8 |
| internal_only | 8 |
| dual | 5 |
| keyword_exact | 1 |
| metadata_filter | 1 |
| history_aware | 1 |
| no_hit | 1 |

## 本地 Config Smoke v1.1 (4/4 PASS)

| 检查 | 结果 |
|------|:---:|
| cases 可读 (25 cases, 7 types) | PASS |
| 脚本语法 + 4 逻辑语义 | PASS |
| 输出路径可创建 | PASS |
| 无 heavy import | PASS |

逻辑检查:
- `index_either_missing_fatal`: True
- `citation_empty_not_default_valid`: True
- `route_metric_semantic_clear`: True
- `overall_pass_has_gates`: True

## 关键语义修正

1. **索引**: `official_available` + `internal_available` 都必须是 True，任一 count=0 → fatal
2. **Route**: 使用 gold route 驱动检索，指标名为 `route_execution_accuracy_given_gold_route`
   — Phase 6F 不评估 classifier route correctness（那是 Phase 7 的范围）
3. **Citation**: hits>0 且 candidates=0 → `citation_validity=false, status=no_candidates_with_hits`
   hits=0 → `not_applicable` (不计入 citation 分母)
4. **overall_pass 门槛**: indices_ready + citation_ok + dual_ok + failed_case 阈值
   若 multi-channel hit@3 低于 baseline 超过 0.1，warning 写入 results

## HPC 运行命令

```bash
cd ~/jupyterlab/RAG/agent-service-toolkit-clean
PYTHONPATH=$PWD/src /opt/conda/envs/py310/bin/python \
  scripts/enterprise_kb_v1/run_phase6f_multichannel_retrieval_eval.py
```

详见 `phase6f_hpc_run_commands.md`。

## 后续

- **HPC 运行**: 上传 → 执行 → 拉回结果
- **Phase 6F 收口**: 审查 HPC 输出 → 更新 checkpoint → 提交
- **未跑**: real retrieval eval, embedding, Chroma rebuild

**Phase 6F v1.1 Prep: CONFIG SMOKE PASS — Ready for HPC.**
