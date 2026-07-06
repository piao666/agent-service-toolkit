---
source_id: internal_code_summary_api_smoke
title: "scripts/enterprise_kb_v1/api_retrieval_smoke.py 代码摘要"
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
owner_phase: phase4e1
---

# scripts/enterprise_kb_v1/api_retrieval_smoke.py 代码摘要

## 模块概述 (module_purpose)
Phase 4E1 API 级别检索冒烟测试脚本。HPC 独立运行，不依赖项目 Python 包，仅需 `requests`。向运行中的 FastAPI 服务 (`http://127.0.0.1:8000`) 发 POST 请求到 `/api/enterprise-kb/retrieval/search`，验证 HTTP 200、results 非空、trace 13 字段完整性。输出 JSONL trace 到 `~/jupyterlab/RAG/A/`。

## 关键流程

```
服务可用性检查 (GET /health)
  → for each of 3 queries:
       → POST /api/enterprise-kb/retrieval/search (JSON body)
       → 验证: HTTP 200 + results 非空 + trace 13 字段完整且非空
       → 写入 JSONL trace line
  → 汇总 JSON + 退出码 (all_pass → 0, else → 1)
```

## 3 条 Test Query 设计

覆盖 3 种 corpus 模式，每条 query 针对不同语料库：

| ID | Query | corpus | 预期路由 |
|----|-------|--------|----------|
| api_smoke_001 | What is retrieval augmented generation? | `official_docs` | official_docs 索引 |
| api_smoke_002 | service.py FastAPI enterprise agent query endpoint | `internal_engineering_docs` | internal 索引 |
| api_smoke_003 | Chroma collection embedding function cosine similarity | `auto` | corpus_router 自动路由 |

## 验证逻辑

| 检查项 | 条件 | 失败标记 |
|--------|------|----------|
| `http_ok` | HTTP status == 200 | HTTP{code} |
| `results_ok` | response.results 非空 | EMPTY |
| `trace_ok` | response.trace 含全部 13 个预期字段且均非空 | TRACE |
| `overall_pass` | 以上三项全部通过 | FAIL |

## Trace 13 字段验证

验证 `response.trace` 中以下 13 个字段全部存在且值非空（数字 0 允许）：

1. `query` — 原始查询文本
2. `top_k` — 检索数量
3. `embedding_model` — embedding 模型名
4. `collection_name` — Chroma collection 名
5. `persist_dir` — 持久化目录
6. `retrieved_chunk_ids` — chunk ID 列表
7. `retrieved_source_ids` — source ID 列表
8. `scores` — 相似度分数列表
9. `origin_urls` — 来源 URL 列表
10. `heading_paths` — 章节路径列表
11. `text_previews` — 文本预览列表
12. `latency_ms` — 检索延迟
13. `errors` — 错误列表

## 错误处理

| 场景 | 行为 |
|------|------|
| 服务未启动 (ConnectionError) | FATAL 退出，exit code 1 |
| /health 非 200 | FATAL 退出，exit code 1 |
| 单条 query 超时 (30s) | 记录 error，继续下一条 |
| 单条 query 连接失败 | 记录 error，继续下一条 |
| 部分 query 失败 | 汇总输出 FAILED 列表，exit code 1 |

## 输出文件

| 文件 | 内容 |
|------|------|
| `phase4e1_api_retrieval_smoke_trace.jsonl` | 3 行 JSONL，每行含 query 信息、验证结果、response_trace |
| `phase4e1_api_retrieval_smoke_results.json` | 汇总 JSON（含 smoke_test 统计、per-query summary） |

## 配置依赖 (config_dependency)
无。完全独立 HPC 脚本。仅依赖：
- `requests` 库 (Python 标准外，需预装)
- 运行中的 FastAPI 服务 (`http://127.0.0.1:8000`)

## 运行时风险 (runtime_risk)
1. **服务依赖**：要求 FastAPI 服务已在 HPC 上启动且端口 8000 可访问。
2. **internal_engineering_docs 依赖**：如果 Phase 4F internal 索引未构建，corpus=internal_engineering_docs 的 query 将返回空结果。
3. **corpus_router 依赖**：corpus=auto 的 query 依赖 `rag.corpus_router.route_corpus()` 存在且正常工作。
4. **网络延迟**：本地 HPC 回环 (127.0.0.1)，延迟通常在 10-100ms 量级。

## 与检索/RAG 的关系 (relation_to_retrieval_or_rag)
Phase 4E1 的核心验证脚本。与 `runtime_retrieval_smoke.py` (Phase 4E, Chroma 直连) 互补——Phase 4E 验证索引层正确性，Phase 4E1 验证 API 层正确性。二者共同构成 Phase 4E runtime verification 的证据链。

## 代码尺寸
- 行数: ~190
- Test query: 3 条
- 验证字段: 13
- 输出文件: 2
