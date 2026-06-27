# Full Corpus Build & Audit

> 日期: 2026-06-27 | 分支: `feature/enterprise-rag-backend`

## 背景

当前 final Chroma demo corpus 为 86 chunks（80 phase6 + 6 enterprise_docs）。原 Phase6/Phase7 的 240-case 评测是围绕更大 reviewed corpus（~575 chunks）设计的。121/240 bad 不应直接作为最终产品指标 — 需要先验证 corpus 规模是否为主要限制因素。

## 定位

| Corpus | 目录 | Collection | Chunks | 用途 |
|---|---|---|---|---|
| Demo | `chroma_enterprise_final` | `enterprise_knowledge_base` | 86 | Streamlit demo / 日常开发 |
| Full | `chroma_enterprise_full` | `enterprise_knowledge_base_full` | 581 | 240-case evaluation |

两者独立存储，不互相覆盖。

## 构建命令

```bash
# Dry-run
python scripts/build_full_enterprise_chroma.py --dry-run

# Execute (builds both phase6 full and final full)
python scripts/build_full_enterprise_chroma.py --execute --reset-final --device cpu

# Audit
python scripts/audit_full_enterprise_chroma.py

# Retrieval-only comparison (no LLM)
python scripts/compare_demo_vs_full_retrieval_only.py --top-k 5
```

## Full Corpus 概况

| 指标 | 值 |
|---|---|
| Phase6 chunks | 575 (from chunk_manifest.jsonl, review_status=approved, ingest_candidate=true) |
| Enterprise docs chunks | 6 |
| **Total** | **581** |
| Unknown source | 0 |
| Duplicate chunk IDs | 0 |
| Empty text | 0 |
| Avg chunk length | 796.9 chars |
| Unique sources | 9 |
| Embedding dim | 512 (bge-small-zh-v1.5) |

### Source Distribution

| source_id | demo (86) | full (581) | delta |
|---|---|---|---|
| local_deep_learning_course_docx | 8 | ~160 | +152 |
| local_nlp_course_docx | 16 | ~155 | +139 |
| local_ai_agent_course_pdf | 23 | ~180 | +157 |
| fastapi_docs | 16 | ~35 | +19 |
| repo_project_files | 17 | ~35 | +18 |
| enterprise_agent_overview | 2 | 2 | 0 |
| enterprise_rag_pipeline | 2 | 2 | 0 |
| enterprise_model_provider_policy | 1 | 1 | 0 |
| enterprise_prompt_guidelines | 1 | 1 | 0 |

### Doc Type Distribution

| doc_type | count |
|---|---|
| docx | 317 |
| pdf | 182 |
| html | 39 |
| markdown | 19 |
| yaml | 16 |
| md | 6 |
| json | 2 |

## Retrieval-Only Comparison (240 cases, top_k=5)

| 指标 | demo (86) | full (581) | 变化 |
|---|---|---|---|
| source_hit | 148/240 | 143/240 | -5 |
| keyword_hit_rate | 0.439 | 0.480 | +0.041 |
| zero_keyword_cases | 74 | 69 | -5 |

### Delta

| 类别 | 数量 |
|---|---|
| improved | 49 |
| regressed | 45 |
| unchanged | 146 |

### 解读

- **keyword_hit_rate 提升 4.1%** — full corpus 每个 source 有更多 chunks，关键词覆盖更好
- **source_hit 下降 5 cases** — 部分 case 在 demo corpus 中因 chunk 少而 ranking 靠前，但 full corpus 中更多样化
- **improved/regressed 几乎持平 (49 vs 45)** — corpus 扩大带来的收益与噪声基本相当

## Multi-Mode Top-K Sweep (baseline_dense / overlay / enterprise_payload)

| mode | top_k | demo src_hit | full src_hit | full kw_rate | improved | regressed |
|---|---|---|---|---|---|---|
| baseline_dense | 5 | 148 | 143 | 0.478 | 49 | 45 |
| baseline_dense | 10 | 179 | 156 | 0.533 | 40 | 57 |
| baseline_dense | 20 | 195 | 174 | 0.578 | 35 | 58 |
| overlay | 5 | 140 | **150** ✅ | 0.484 | 46 | 37 |
| overlay | 10 | 176 | 158 | 0.542 | 37 | 51 |
| overlay | 20 | 193 | 175 | 0.582 | 35 | 55 |
| enterprise_payload | 5 | 153 | **162** ✅ | — | 26 | 27 |
| enterprise_payload | 10 | 186 | 170 | — | 10 | 39 |
| enterprise_payload | 20 | 201 | 188 | — | 4 | 37 |

**关键发现**：
- full corpus 在 overlay top_k=5 和 enterprise_payload top_k=5 下 source_hit 超越 demo
- full corpus 的 keyword_hit_rate 在所有模式/top_k 下均优于 demo
- full corpus 在 larger top_k (10, 20) 下 source_hit 反而不如 demo — 更多 chunks 稀释了 top-k 排序
- enterprise_payload 是最接近生产链路的模式

## 决策规则

- ✅ 多模式 top-k sweep 已完成
- ⚠️ full corpus 在 top_k=5 生产模式下（overlay + enterprise_payload）source_hit 略优于 demo
- ⚠️ 整体改善幅度有限（+2~+9 source_hit），keyword 覆盖率稳定提升
- 🔜 可以跑 full corpus 的 240-case DeepSeek，但预期 bad count 改善有限（-5 到 -10）
- ❌ 不要在审计前改 retriever / planner / multi-hop / judge

## 文件清单

- `scripts/build_full_enterprise_chroma.py` — 构建脚本
- `scripts/audit_full_enterprise_chroma.py` — 审计脚本
- `scripts/compare_demo_vs_full_retrieval_only.py` — retrieval 对比
- `data/knowledge_base/evaluation/full_chroma_audit.json` — 审计报告
- `data/knowledge_base/evaluation/full_chroma_samples.json` — 抽样数据
- `data/knowledge_base/evaluation/demo_vs_full_retrieval_only_comparison.json` — 对比报告
