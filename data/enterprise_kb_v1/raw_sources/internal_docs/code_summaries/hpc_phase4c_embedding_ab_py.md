---
source_id: internal_code_summary_hpc_embedding_ab
title: "scripts/enterprise_kb_v1/hpc_phase4c_run_embedding_ab.py 代码摘要"
domain: embedding_evaluation
source_type: internal_engineering_docs
doc_type: code_summary
authority_level: internal_current_snapshot
doc_status: active
allowed_for_answer: false
answer_scope: current_behavior
enabled: false
corpus: internal_engineering_docs
version: v1
owner_phase: phase4c
---

# scripts/enterprise_kb_v1/hpc_phase4c_run_embedding_ab.py 代码摘要

## 模块概述 (module_purpose)
HPC 独立运行的 4 模型 embedding A/B 评测脚本。不依赖项目 Python 包，直接用 SentenceTransformer + chromadb 完成全流程：GPU 检查 → 加载 4 个 embedding 模型 → 逐模型构建 Chroma 索引 → 22 条 eval case 检索评测 → per-case debug (88 行 = 22×4) → hit_rate / MRR 汇总。

## 关键流程

```
GPU 检查 (CUDA required)
  → 加载 preflight JSON (model_path_check)
  → 读取 clean_chunks.jsonl + eval_gold_official_docs.jsonl
  → for each model in [bge-small-zh-v1.5, bge-m3, qwen3-embedding-0.6b, multilingual-e5-base]:
       → SentenceTransformer(model_path, device='cuda')
       → 分 batch (100) 构建 Chroma 索引 (cosine space)
       → 对 22 条 eval case 逐条检索 @k=3/5/10
       → 计算 hit_rate, MRR, source_dedup_hit_rate
       → 记录 per-case debug (仅 k=10 时)
  → 输出 3 个文件: per_case_debug.jsonl, ab_results.json, ab_report.md
```

## 模型列表

| 模型名 | 路径 | 用途 |
|--------|------|------|
| `bge-small-zh-v1.5` | `~/jupyterlab/models/bge-small-zh-v1.5` | 轻量 baseline |
| `bge-m3` | `~/jupyterlab/models/bge-m3` | 多语言候选 |
| `qwen3-embedding-0.6b` | `~/jupyterlab/models/qwen3-embedding-0.6b` | 最新对比 |
| `multilingual-e5-base` | `~/jupyterlab/models/multilingual-e5-base` | 多语言 baseline |

## metadata 设计

Chroma 索引中每个 chunk 的 metadata 包含 3 个字段：
- `source_id`: 来源文档标识
- `heading_path`: 章节路径
- `chunk_id`: 唯一 chunk 标识

## Score 计算

余弦距离 → 相似度转换：`score = 1.0 - distance`（直接，非 `1/(1+distance)` 的倒数转换）。

## 评测指标

| 指标 | 说明 |
|------|------|
| `hit_rate@k` | top-k 中至少命中 1 个 expected source 的比例 |
| `MRR@k` | 首个命中 expected source 排名的倒数均值 |
| `source_dedup_hit_rate@k` | top-k 返回的 source 与 expected sources 有交集的比例（去重） |

## 输出文件

| 文件 | 内容 |
|------|------|
| `phase4c_hpc_embedding_ab_per_case_debug.jsonl` | 88 行 per-case debug (22 案例 × 4 模型)，含 query / expected / retrieved / distances / scores / hit_at_3/5/10 |
| `phase4c_hpc_embedding_ab_results.json` | 4 模型汇总 JSON (dimension, build_time, GPU memory, per_k metrics) |
| `phase4c_hpc_embedding_ab_report.md` | Markdown 表格 + 推荐结论 |

## 配置依赖 (config_dependency)
无。完全独立脚本，HPC 路径硬编码 (PROJECT, A_DIR, MODEL_ROOT, STORAGE)。仅依赖 preflight 阶段生成的 `phase4c_hpc_model_path_check.json`。

## 运行时风险 (runtime_risk)
1. **GPU 显存不足**：qwen3-embedding-0.6b 需约 5.57 GB，4 模型顺序运行时显存峰值可能接近 11 GB 上限。
2. **Python 3.10 兼容**：SentenceTransformer `get_embedding_dimension()` 在 3.10 中命名有差异（代码中做了 hasattr 兼容）。
3. **路径缺失静默**：模型路径不存在时仅记录 error 到结果 dict，不阻断后续模型评测。

## 与检索/RAG 的关系 (relation_to_retrieval_or_rag)
Phase 4D bge-m3 选择的核心证据来源。该脚本的 hit_rate/MRR 对比结果直接决定了生产环境 embedding 模型的选型。

## 代码尺寸
- 行数: ~212
- 评测案例: 22
- Per-case debug 行数: 88 (22×4)
- 输出文件: 3
