---
source_id: internal_code_summary_schema_py
title: "src/schema/schema.py 代码摘要"
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

# src/schema/schema.py 代码摘要

## 模块概述 (module_purpose)
全项目 Pydantic 请求/响应模型定义。涵盖通用 agent 交互、企业 RAG 查询、检索、RAG 回答、反馈、会话历史等所有 API 的契约模型。通过 `src/schema/__init__.py` 重导出供 `service.py` 使用。

## 关键模型 (key_models)

| 模型 | 用途 | 关键字段 |
|------|------|----------|
| `UserInput` | agent invoke/stream 通用输入 | message, model, thread_id, user_id, agent_config |
| `StreamInput` | 流式输入 (继承 UserInput) | + stream_tokens |
| `ChatMessage` | 聊天消息 | type (human/ai/tool/custom), content, tool_calls, run_id, response_metadata |
| `ServiceMetadata` | 服务元信息 | agents, models, default_agent, default_model |
| `AgentInfo` | agent 描述 | key, description |
| `Feedback` / `FeedbackResponse` | LangSmith 反馈 | run_id, key, score |
| `ChatHistoryInput` / `ChatHistory` | 会话历史 | thread_id → messages |
| `EnterpriseAgentQueryInput` | 企业 RAG 查询输入 | query, session_id, top_k (0-20), return_sources, model |
| `EnterpriseAgentQueryResponse` | 企业 RAG 查询响应 | answer, sources, retrieval_debug, latency_ms, model_debug, memory_debug, planner_debug, verifier_debug, judge_debug, graph_debug, fallback, session_id |
| `EnterpriseKBRetrievalRequest` | 检索请求 | query (min_length=1), top_k (1-20), corpus |
| `EnterpriseKBRetrievalResponse` | 检索响应 | results (list[dict]), trace (dict), latency_ms, corpus_used |
| `EnterpriseKBRagAnswerRequest` | RAG 回答请求 | query, top_k, corpus (default="auto") |
| `EnterpriseKBRagAnswerResponse` | RAG 回答响应 | answer, citations, trace, latency_ms, corpus_used, llm_mode |
| `ToolCall` | 工具调用 (TypedDict) | name, args, id, type |

## corpus 字段设计

`EnterpriseKBRetrievalRequest` 和 `EnterpriseKBRagAnswerRequest` 共用 `corpus` 字段，类型为 `Literal["official_docs", "internal_engineering_docs", "auto"]`：

| 值 | 含义 |
|----|------|
| `"official_docs"` | 检索 bge-m3 官方文档索引（默认） |
| `"internal_engineering_docs"` | 检索 Phase 4F 内部工程文档索引 |
| `"auto"` | 由 corpus_router 根据 query 关键词自动路由 |

## RAG 回答响应设计

`EnterpriseKBRagAnswerResponse` 包含：
- `answer`: 带 `[citation:X]` 标记的回答文本
- `citations`: 引用列表，每项含 source_id / heading_path / score / text_preview
- `trace`: 检索 + routing trace
- `llm_mode`: 回答生成模式（"mock_extractive" = 无 LLM，基于检索结果拼接）

## 配置依赖 (config_dependency)
无。纯数据模型，不依赖 config、settings 或任何运行时模块。仅依赖 `schema.models` 中的模型枚举 (`AllModelEnum`, `OpenAIModelName`, `AnthropicModelName`)。

## 运行时风险 (runtime_risk)
1. **API 契约变更**：字段重命名或类型变更直接破坏所有客户端，无版本兼容层。
2. **序列化依赖**：使用 `SerializeAsAny` 包装 `AllModelEnum`，依赖 Pydantic 序列化行为。
3. **corpus Literal 扩展**：新增语料库需同时修改两处 `Literal` 定义（`EnterpriseKBRetrievalRequest` 和 `EnterpriseKBRagAnswerRequest`），容易遗漏。

## 与检索/RAG 的关系 (relation_to_retrieval_or_rag)
定义所有检索和 RAG 端点的请求/响应契约。Phase 4E 检索冒烟测试依赖 `EnterpriseKBRetrievalResponse.trace` 的 13 字段完整性验证。

## 代码尺寸
- 行数: ~347
- Pydantic 模型: 15
- TypedDict: 1 (ToolCall)
