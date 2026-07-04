# 外部官方文档技术域映射

> 版本: v1-draft | 状态: policy | 最后更新: 2026-07-04

---

## 一、域映射总览

| domain | 编号 | 名称 | Phase 3A source 数 |
|--------|------|------|---------------------|
| `api_backend` | A | FastAPI / Pydantic | 6 |
| `vector_database` | B | Chroma / Vector Store | 5 |
| `agent_orchestration` | C | LangGraph / Agent Workflow | 5 |
| `llm_provider` | D | LLM Provider / OpenAI-compatible API | 5 |

合计: **21 条外部官方候选 source**

---

## 二、api_backend — FastAPI / Pydantic

### 覆盖范围

- FastAPI 路由声明、路径参数、查询参数
- 请求体解析（JSON / Form / File Upload）
- Pydantic BaseModel、Field、Validator
- Dependency Injection / Depends
- Middleware / CORS
- HTTPException / 自定义错误处理
- 响应模型、状态码、Header

### 不覆盖范围

- FastAPI WebSocket
- FastAPI Background Tasks
- FastAPI Testing
- FastAPI Advanced Security（OAuth2 scopes 等高级主题，v1 暂不纳入）
- SQLModel / SQLAlchemy 集成
- Starlette 底层实现细节
- Pydantic v1 兼容层

### 推荐 source_id

| source_id | 对应 core_eval_30 |
|-----------|-------------------|
| `fastapi_official_routing` | core_001, core_002 |
| `fastapi_official_request_body` | core_001, core_003, core_005 |
| `fastapi_official_dependency_injection` | core_004 |
| `fastapi_official_middleware` | core_007 |
| `fastapi_official_error_handling` | core_006 (状态码) |
| `pydantic_official_models_validation` | core_003, core_008 |

---

## 三、vector_database — Chroma / Vector Store

### 覆盖范围

- Collection 的创建/获取/删除
- 文档添加（add / upsert）
- 相似度查询（query / similarity_search）
- Metadata 过滤（where 子句）
- Embedding function（默认 + 自定义）
- 持久化存储配置
- 距离/相似度度量选择

### 不覆盖范围

- Chroma 的 gRPC/HTTP 服务端部署
- Chroma 多节点集群
- 第三方 embedding service 的详细配置文档
- Chroma 与其他向量数据库的性能对比
- 向量索引算法（HNSW 参数调优）

### 推荐 source_id

| source_id | 对应 core_eval_30 |
|-----------|-------------------|
| `chroma_official_collections` | core_009 |
| `chroma_official_add_query` | core_013, core_015 |
| `chroma_official_persistence` | core_014 |
| `chroma_official_metadata_filter` | core_011 |
| `chroma_official_embedding_functions` | core_010, core_012 |

---

## 四、agent_orchestration — LangGraph / Agent Workflow

### 覆盖范围

- StateGraph 定义和编译
- State Schema（TypedDict / Pydantic）
- 节点（Node）和边（Edge）的类型
- 条件边（conditional_edges）和动态路由
- Checkpoint / Memory / Persistence
- ToolNode / Tool Calling
- Streaming 模式

### 不覆盖范围

- LangGraph Cloud / LangGraph Platform 部署
- LangGraph Supervisor / Multi-Agent 高级模式
- LangSmith 集成细节
- 自定义 Checkpointer 实现
- LangGraph 与 LangChain 的互操作
- Human-in-the-loop / Interrupt 高级用法

### 推荐 source_id

| source_id | 对应 core_eval_30 |
|-----------|-------------------|
| `langgraph_official_stategraph` | core_016 |
| `langgraph_official_nodes_edges` | core_017 |
| `langgraph_official_conditional_edges` | core_021 |
| `langgraph_official_checkpoint_memory` | core_018, core_019 |
| `langgraph_official_tool_calling` | core_020 (streaming 相关) |

---

## 五、llm_provider — LLM Provider / OpenAI-compatible API

### 覆盖范围

- Chat Completions API（messages / model / temperature / max_tokens）
- Structured Outputs / JSON mode / Function Calling
- Streaming（Server-Sent Events / chunked response）
- OpenAI-compatible API 协议规范
- Qwen 模型参数和能力限制

### 不覆盖范围

- Embedding API / TTS API / Image Generation API
- Fine-tuning API
- Moderation API
- 各 Provider 的计费细节
- 模型 benchmark 数据
- 非 OpenAI-compatible 的 API 协议（如 Anthropic Messages API 的差异）

### 推荐 source_id

| source_id | 对应 core_eval_30 |
|-----------|-------------------|
| `openai_official_chat_completions` | core_022 (LLM provider 配置相关) |
| `openai_official_structured_outputs` | — |
| `openai_official_streaming` | — |
| `qwen_official_openai_compatible_api` | — |
| `qwen_official_model_parameters` | — |

> 注：llm_provider 域的 core_eval_30 覆盖度较低，首版建议以项目内部文档（internal_config_reference_current.md）为主来回答 provider 配置问题。
