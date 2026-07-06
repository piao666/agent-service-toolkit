---
source_id: internal_code_summary_service_py
title: "src/service/service.py 代码摘要"
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
owner_phase: phase4fh
---

# src/service/service.py 代码摘要

## 模块概述 (module_purpose)
FastAPI 应用入口，含 9+ API 端点、lifespan 管理、认证中间件。双路由架构：`app` (无认证，3 个 endpoint) 和 `router` (Bearer 认证，6 个 endpoint)。支持 LangGraph agent invoke/stream，以及 Phase 4E/4F/4H 的企业知识库检索与 RAG 回答。

## 关键函数与类 (key_functions_or_classes)

| 函数 | 签名 | 说明 |
|------|------|------|
| `lifespan` | `async (app: FastAPI) → AsyncGenerator` | 启动时初始化 checkpointer + store + 加载所有 agent |
| `verify_bearer` | `(http_auth) → None` | Bearer token 认证，AUTH_SECRET 未配置时放行 |
| `health_check` | `async () → dict` | `/health` — 含 Langfuse 连接检测 |
| `enterprise_kb_retrieval_health` | `async () → dict` | `/api/enterprise-kb/retrieval/health` — 双语料库索引健康检查 |
| `enterprise_kb_retrieval_search` | `async (EnterpriseKBRetrievalRequest) → EnterpriseKBRetrievalResponse` | Phase 4F 双语料检索，支持 corpus=auto 自动路由 |
| `enterprise_kb_rag_answer` | `async (EnterpriseKBRagAnswerRequest) → EnterpriseKBRagAnswerResponse` | Phase 4H RAG 回答（mock/extractive 模式） |
| `enterprise_agent_query` | `async (EnterpriseAgentQueryInput) → EnterpriseAgentQueryResponse` | 企业 RAG Agent 主端点，支持 legacy / custom_graph 两种模式 |
| `invoke` | `async (UserInput, agent_id) → ChatMessage` | Agent 同步调用 |
| `stream` | `async (StreamInput, agent_id) → StreamingResponse` | Agent SSE 流式调用 |
| `feedback` | `async (Feedback) → FeedbackResponse` | LangSmith feedback 记录 |
| `history` | `async (ChatHistoryInput) → ChatHistory` | 会话历史查询 |
| `info` | `async () → ServiceMetadata` | 服务元信息（可用 agent / model 列表） |

## 双路由架构

| 路由对象 | 认证 | 端点 |
|----------|------|------|
| `app` (FastAPI) | 无认证 | `/health`, `/api/enterprise-kb/retrieval/health`, `/api/enterprise-kb/retrieval/search` |
| `router` (APIRouter) | Bearer (verify_bearer) | `/info`, `/invoke`, `/stream`, `/feedback`, `/history`, `/api/enterprise-kb/rag/answer` |

注意：`/api/enterprise-kb/retrieval/search` 挂载在 `app` 上（无认证），用于 HPC API 级别冒烟测试。

## 输入/输出 (inputs_outputs)

| 端点 | 请求模型 | 响应模型 |
|------|----------|----------|
| `/health` | — | `{"status": "ok", "langfuse": ...}` |
| `/enterprise/agent/query` | `EnterpriseAgentQueryInput` (query, session_id, top_k, return_sources, model) | `EnterpriseAgentQueryResponse` (answer, sources, retrieval_debug, latency_ms, model_debug, memory_debug, verifier_debug, judge_debug, graph_debug, fallback, session_id) |
| `/api/enterprise-kb/retrieval/search` | `EnterpriseKBRetrievalRequest` (query, top_k, corpus) | `EnterpriseKBRetrievalResponse` (results, trace, latency_ms, corpus_used) |
| `/api/enterprise-kb/rag/answer` | `EnterpriseKBRagAnswerRequest` (query, top_k, corpus) | `EnterpriseKBRagAnswerResponse` (answer, citations, trace, latency_ms, corpus_used, llm_mode) |

## 配置依赖 (config_dependency)
- `rag_settings` (from `rag.config`) — agent_graph_mode, CHROMA_PERSIST_DIR, CHROMA_INTERNAL_PERSIST_DIR, CHROMA_COLLECTION_NAME, CHROMA_INTERNAL_COLLECTION_NAME, EMBEDDING_PROVIDER, RERANKER_ENABLED
- `core.settings` — AUTH_SECRET, LANGFUSE_TRACING, DEFAULT_MODEL, AVAILABLE_MODELS

## 运行时风险 (runtime_risk)
1. **延迟导入 (lazy import)**：`enterprise_agent_query` 在 custom_graph 模式下首次请求才 `from agents.enterprise_rag_graph import run_enterprise_rag_graph`，触发模型加载，首请求延迟较高。
2. **相对路径依赖 CWD**：uvicorn 启动目录不同时 `rag_settings` 中的相对路径解析可能错误。
3. **corpus_router 延迟导入**：`enterprise_kb_retrieval_search` 在函数体内 `from rag.corpus_router import route_corpus`，corpus_router 不存在时首请求即崩溃。
4. **agent_id 硬编码**：`history` 端点硬编码 `DEFAULT_AGENT`，多 agent 场景有局限。

## 与检索/RAG 的关系 (relation_to_retrieval_or_rag)
Phase 4E/4F/4H 所有 enterprise KB 端点的宿主。`/api/enterprise-kb/retrieval/search` 是检索冒烟测试的 API 目标，`/enterprise/agent/query` 是全链路 RAG agent 的入口。

## 代码尺寸
- 行数: ~690
- 端点: 9 (app 3 + router 6)
- 内部辅助函数: 4 (`_handle_input`, `_enterprise_retrieval_debug`, `_enterprise_model_debug`, `_create_ai_message`)
