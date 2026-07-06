---
source_id: internal_code_summary_runtime_smoke
title: "scripts/enterprise_kb_v1/runtime_retrieval_smoke.py 代码摘要"
domain: runtime_retrieval
source_type: internal_engineering_docs
doc_type: code_summary
authority_level: internal_current_snapshot
doc_status: active
allowed_for_answer: false
answer_scope: current_behavior
enabled: false
corpus: internal_engineering_docs
version: v1
owner_phase: phase4e
---

# scripts/enterprise_kb_v1/runtime_retrieval_smoke.py 代码摘要

## 模块概述 (module_purpose)
HPC 独立运行的 10 条 smoke query 检索验证脚本。不依赖项目 Python 包，直接用 SentenceTransformer + chromadb 对 bge-m3 官方文档索引执行检索。输出 trace JSONL + results JSON 到 `~/jupyterlab/RAG/A/`。

## 10 条 Smoke Query 设计

覆盖 5 个开源项目，中英双语各 1 条：

| ID | Query | 目标项目 | 语言 |
|----|-------|----------|------|
| smoke_001 | How to create a Chroma collection with cosine similarity? | Chroma | en |
| smoke_002 | Chroma 如何选择一个 collection? | Chroma | zh |
| smoke_003 | FastAPI request body validation with Pydantic BaseModel | FastAPI | en |
| smoke_004 | FastAPI 请求体是如何被验证的? | FastAPI | zh |
| smoke_005 | LangGraph StateGraph nodes and edges construction | LangGraph | en |
| smoke_006 | OpenAI chat completion streaming with tool calls | OpenAI | en |
| smoke_007 | Pydantic Field validators and custom validation functions | Pydantic | en |
| smoke_008 | 什么是 retrieval augmented generation? | RAG | zh |
| smoke_009 | chroma collection embedding function | Chroma | en |
| smoke_010 | 如何在 LangGraph 中定义 conditional edges? | LangGraph | zh |

## Trace 13 字段

每条 smoke query 的 trace 记录包含 13 个必含字段：

| 字段 | 类型 | 说明 |
|------|------|------|
| `query` | str | 原始查询文本 |
| `top_k` | int | 检索数量 (固定 5) |
| `embedding_model` | str | "bge-m3" |
| `collection_name` | str | Chroma collection 名称 |
| `persist_dir` | str | 持久化目录相对路径 |
| `retrieved_chunk_ids` | list[str] | 检索到的 chunk ID 列表 |
| `retrieved_source_ids` | list[str] | 检索到的 source ID 列表（去重） |
| `scores` | list[float] | 余弦相似度分数 (1/(1+distance)) |
| `origin_urls` | list[str] | 来源 URL（从 source_registry.yaml 映射） |
| `heading_paths` | list[str] | 章节路径 |
| `text_previews` | list[str] | 文本预览（前 200 字符） |
| `latency_ms` | float | 检索延迟（毫秒） |
| `errors` | list | 错误列表（正常为空） |

## source_registry.yaml URL 映射

通过 `_build_source_url_map()` 从 `data/enterprise_kb_v1/source_registry/source_registry.yaml` 构建 source_id → origin_url 映射，使 trace 中的 `origin_urls` 字段包含可访问的原始文档链接。

## 输出文件

| 文件 | 内容 |
|------|------|
| `phase4e_runtime_retrieval_trace_samples.jsonl` | 10 行 trace JSONL（每行 13 字段） |
| `phase4e_hpc_runtime_retrieval_results.json` | 汇总 JSON（含 GPU 信息、模型信息、smoke test 统计、trace 字段覆盖率、summary） |

## 汇总统计

`results.json` 中包含：
- `smoke_test.queries_with_results`: 有结果的 query 数（目标 = 10）
- `smoke_test.all_queries_pass`: 是否全部通过
- `smoke_test.avg_latency_ms`: 平均延迟
- `trace_field_coverage`: 13 字段逐字段完整性检查
- `trace_all_fields_complete`: 是否全部字段完整

## 配置依赖 (config_dependency)
无。完全独立 HPC 脚本，路径硬编码。仅依赖：
- `~/jupyterlab/models/bge-m3` (embedding 模型)
- `storage/chroma_enterprise_kb_v1_bge_m3` (Chroma 索引，需先由 Phase 4D 构建)
- `data/enterprise_kb_v1/source_registry/source_registry.yaml` (URL 映射)

## 运行时风险 (runtime_risk)
1. **Chroma 索引缺失**：启动时检查 `CHROMA_DIR` 和 collection 存在性，缺失时 FATAL 退出。
2. **模型路径依赖**：模型路径硬编码，路径变更需修改脚本。
3. **GPU 依赖**：强制 CUDA，无 CPU fallback。

## 与检索/RAG 的关系 (relation_to_retrieval_or_rag)
Phase 4E runtime verification 的核心证据来源。证明 bge-m3 索引在 HPC 上可正常检索并返回有意义的结果。对应服务的 `/api/enterprise-kb/retrieval/search` 端点。

## 代码尺寸
- 行数: ~249
- Smoke query: 10 条
- Trace 字段: 13
- 输出文件: 2
