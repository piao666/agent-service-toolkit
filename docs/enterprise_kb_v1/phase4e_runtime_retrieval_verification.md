# Phase 4E: Runtime Retrieval Verification

**日期**: 2026-07-05
**状态**: 执行中
**前序**: Phase 4D (bge-m3 embedding 切换完成)

## 目标

验证当前项目 runtime（API 服务器）是否能真正使用 bge-m3 official_docs 检索索引，
而不是只停留在 HPC 离线评测结果。重点验证：配置读取 → Chroma 连接 → query embedding → top-k retrieval → trace 输出。

## 范围

- 只验证 `enterprise_kb_v1_official_docs_bge_m3` 检索链路
- 不扩充语料、不重新采集、不重新 chunk、不重建 embedding index
- 不启用 reranker、不进入 RAG answer generation、不做 UI

## 新增文件

| 文件 | 用途 |
|------|------|
| `src/rag/official_docs_retriever.py` | runtime 配置验证 + 检索包装器 |
| `scripts/enterprise_kb_v1/runtime_retrieval_smoke.py` | HPC smoke test（10 queries） |
| `docs/enterprise_kb_v1/phase4e_runtime_retrieval_verification.md` | 本文档 |

## 修改文件

| 文件 | 变更 |
|------|------|
| `src/schema/schema.py` | 新增 `EnterpriseKBRetrievalRequest` + `EnterpriseKBRetrievalResponse` |
| `src/schema/__init__.py` | 导出 2 个新模型 |
| `src/service/service.py` | 新增 `GET /api/enterprise-kb/retrieval/health` + `POST /api/enterprise-kb/retrieval/search` |

## 验证项（7 项配置）

| # | 配置项 | 期望值 | 验证方式 |
|---|--------|--------|---------|
| 1 | default_embedding | bge-m3 | `rag_settings.local_embedding_model_path` |
| 2 | default_collection | enterprise_kb_v1_official_docs_bge_m3 | `rag_settings.CHROMA_COLLECTION_NAME` |
| 3 | default_persist_dir | storage/chroma_enterprise_kb_v1_bge_m3 | `rag_settings.CHROMA_PERSIST_DIR` |
| 4 | high_precision_candidate | qwen3-embedding-0.6b (注释) | config.py 注释验证 |
| 5 | lightweight_fallback | bge-small-zh-v1.5 (注释) | config.py 注释验证 |
| 6 | reranker_enabled | false | `rag_settings.RERANKER_ENABLED` |
| 7 | production_answer_pipeline | false (评估阶段) | 无 config key |

## 10 条 Smoke Query

| # | ID | Query | 语言 | 目标项目 |
|---|----|-------|------|---------|
| 1 | smoke_001 | How to create a Chroma collection with cosine similarity? | EN | Chroma |
| 2 | smoke_002 | Chroma 如何选择一个 collection? | ZH | Chroma |
| 3 | smoke_003 | FastAPI request body validation with Pydantic BaseModel | EN | FastAPI |
| 4 | smoke_004 | FastAPI 请求体是如何被验证的? | ZH | FastAPI |
| 5 | smoke_005 | LangGraph StateGraph nodes and edges construction | EN | LangGraph |
| 6 | smoke_006 | OpenAI chat completion streaming with tool calls | EN | OpenAI |
| 7 | smoke_007 | Pydantic Field validators and custom validation functions | EN | Pydantic |
| 8 | smoke_008 | 什么是 retrieval augmented generation? | ZH | RAG |
| 9 | smoke_009 | chroma collection embedding function | EN | Chroma |
| 10 | smoke_010 | 如何在 LangGraph 中定义 conditional edges? | ZH | LangGraph |

## API 端点

### `GET /api/enterprise-kb/retrieval/health`
无认证。返回 collection 状态、chunk 数量、embedding 模型信息。

### `POST /api/enterprise-kb/retrieval/search`
有认证（若 AUTH_SECRET 已配置）。Request body:
```json
{"query": "...", "top_k": 5}
```
Response:
```json
{
  "results": [{"chunk_id": "...", "source_id": "...", "score": 0.95, ...}],
  "trace": {"query": "...", "embedding_model": "bge-m3", "latency_ms": 12.3, ...},
  "latency_ms": 12.5
}
```

## Trace JSON Schema

```json
{
  "query": "string",
  "top_k": 5,
  "embedding_model": "bge-m3",
  "collection_name": "enterprise_kb_v1_official_docs_bge_m3",
  "persist_dir": "storage/chroma_enterprise_kb_v1_bge_m3",
  "retrieved_chunk_ids": ["id1", "id2", ...],
  "retrieved_source_ids": ["source1", ...],
  "scores": [0.95, 0.87, ...],
  "latency_ms": 12.3,
  "hit_count": 5,
  "errors": []
}
```

## 执行流程

1. 本地：编写代码 → ruff 检查 → config validation JSON
2. 本地：启动 uvicorn → curl health + search 冒烟
3. SCP 上传 smoke script 到 HPC
4. HPC：运行 smoke test → trace JSONL + results JSON
5. SCP 拉回结果到本地 A/
6. 本地：综合报告 + ZIP 打包

## 通过标准

- 7 项配置全部 pass
- 10/10 smoke query hit_count > 0
- API health 返回 200 + chunk_count > 0
- API search 返回 200 + trace 字段完整
- 未启用 reranker：确认
- 未进入 RAG answer：确认
- 本地未跑重型 embedding/eval：确认
