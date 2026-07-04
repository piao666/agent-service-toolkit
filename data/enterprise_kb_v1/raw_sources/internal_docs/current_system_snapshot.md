---
source_id: internal_current_system_snapshot
title: "Agent-Service-Toolkit 当前系统模块与边界 (内部文档)"
domain: internal_engineering
source_type: internal_project
doc_type: internal_markdown
authority_level: internal_current_snapshot
doc_status: draft
allowed_for_answer: false
answer_scope: current_behavior
code_reference: >
  src/service/service.py, src/agents/enterprise_rag_agent.py,
  src/agents/enterprise_rag_graph.py, src/rag/,
  src/core/settings.py, src/schema/schema.py,
  pyproject.toml, .env.example
last_verified: null
notes: >
  草案阶段，基于 2026-07-04 代码快照生成。未经人工审核。
  描述当前真实行为，不含规划内容（规划内容见 project_extension_guide_draft.md）。
---

# 当前系统模块与边界

## 一、项目概况

本项目是基于 [agent-service-toolkit](https://github.com/piao666/agent-service-toolkit) 扩展的企业知识库 RAG 后端系统。
编程语言 Python 3.11+，使用 FastAPI 作为 HTTP 服务框架、LangGraph 作为 Agent 编排框架、Chroma 作为向量存储。

**当前阶段**: 工程原型，非生产部署完成品。

## 二、目录职责

| 目录 | 职责 | 状态 |
|------|------|------|
| `src/service/` | FastAPI 服务入口，路由注册，认证 | 已实现 |
| `src/agents/` | Agent 定义（legacy + custom_graph） | 已实现 |
| `src/rag/` | RAG 检索、配置、策略、evidence verifier、memory | 已实现 |
| `src/schema/` | Pydantic 请求/响应模型，Provider/Model 枚举 | 已实现 |
| `src/core/` | 全局 Settings（多 Provider API key）、模型工厂 | 已实现 |
| `src/memory/` | LangGraph checkpoint 后端（SQLite/Postgres/MongoDB） | 已实现 |
| `src/voice/` | 语音输入/输出（OpenAI STT/TTS，可选） | 已实现 |
| `scripts/` | 评测/诊断/构建脚本 | 工具集 |
| `tests/` | pytest 测试（agents + service + voice + client） | 已实现 |
| `data/enterprise_kb_v1/` | 企业知识库 v1 数据目录 | Phase 1 蓝图 |

## 三、主要运行入口

| 入口 | 方式 | 用途 |
|------|------|------|
| `src/run_service.py` | `python src/run_service.py` | 启动 FastAPI 服务 |
| `src/run_agent.py` | `python src/run_agent.py` | 命令行交互式 Agent |
| `src/run_client.py` | `python src/run_client.py` | HTTP 客户端示例 |
| `src/streamlit_app.py` | `streamlit run src/streamlit_app.py` | Web 演示界面 |
| `langgraph dev` | LangGraph CLI | 开发模式启动（仅 research_assistant graph） |

## 四、已实现能力

### 4.1 多 Provider LLM 支持

支持 12 种 LLM Provider：OpenAI、DeepSeek、Anthropic、Google Gemini、VertexAI、Groq、AWS Bedrock、Ollama、Azure OpenAI、OpenRouter、OpenAI Compatible、Fake。

Provider 发现机制：`Settings.model_post_init()` 根据已配置的 API key 自动激活对应 provider。主要开发 provider 为 DeepSeek（中文 QA 场景）。

`USE_FAKE_MODEL=true` 时使用 `FakeListChatModel`，不调用真实 LLM。

### 4.2 RAG 查询链路

两条并行链路，通过 `ENTERPRISE_AGENT_GRAPH_MODE` 环境变量切换：

- **legacy**：稳定 baseline。`StateGraph(MessagesState)`，节点顺序：input_guard → route_need_retrieval → rewrite_query → retrieve → answer_synthesis → verify_evidence → fallback_or_finish。
- **custom_graph**：可观测调试链路。`StateGraph(EnterpriseRAGGraphState)`，节点顺序含 query_classifier、memory_rewriter、planner、retriever、ranker、answer_generator、evidence_verifier、judge、final_response。

两种模式在 `/enterprise/agent/query` endpoint 层切换，不互相替代。

### 4.3 RAG 检索

- 密集向量检索：SentenceTransformers（默认 `bge-small-zh-v1.5`）→ Chroma
- 三种检索策略模式：baseline / query_type_aware（gated 策略选择）/ targeted_overlay
- 结构化检索：metadata/symbol 精确字段召回（通过 `ENTERPRISE_STRUCTURED_RETRIEVAL_MODE` 开关）
- Source catalog patch router：feature-flag 控制，默认关闭

### 4.4 多轮会话记忆

基于 `session_id` 的进程内 buffer memory。服务重启后清空。通过 `ENTERPRISE_MEMORY_MODE=buffer` 启用。

### 4.5 证据校验

Rule-based evidence verifier（`ENTERPRISE_EVIDENCE_VERIFIER_MODE=rule_based`）。不调用真实 LLM。输出 `grounding_score`、`grounding_status`、`citation_coverage`。

### 4.6 LLM Judge

Rule-based fallback judge（`ENTERPRISE_JUDGE_MODE=rule_based_fallback`）。用于 custom_graph 链路的诊断节点，不调用真实 LLM。

### 4.7 Planner

Debug-only 计划生成（`ENTERPRISE_PLANNER_MODE=debug_only`）。不改变路由，仅记录计划到 graph_debug。

### 4.8 Streamlit 演示

展示 answer、sources、retrieval_debug、memory_debug、verifier_debug、graph_debug。

### 4.9 日志与可观测性

- LangSmith 追踪（可选）
- Langfuse 追踪（可选）
- graph_debug 字段：nodes_executed、calls_llm、calls_real_llm、writes_chroma、planner、judge 详情

## 五、已知边界与限制

1. **工程原型**：非生产部署完成品。不含认证/权限/审计（除可选 HTTP Bearer token）。
2. **memory 是进程内 buffer**：服务重启清空，无跨会话持久化。
3. **evidence verifier 是 rule-based baseline**：不是事实核查系统。
4. **judge 是 rule-based fallback**：不调用 LLM 做质量判断。
5. **multi-hop 检索默认关闭**：`ENTERPRISE_MULTI_HOP_MODE=off`，实测未证明收益。
6. **planner 是 debug_only**：不产生实际路由影响。
7. **嵌入仅支持 local**：`get_embedding_model()` 在非 local provider 时抛出 ValueError。
8. **Chroma 是唯一向量存储**：不支持 FAISS/Milvus/Weaviate 等其他向量数据库。

## 六、未实现内容（planned/draft）

以下内容不在当前代码中，属于后续规划：

- **persistent memory**：计划中，当前仅有进程内 buffer
- **claim-level verifier**：计划中，当前仅有 rule-based 整体 evidence check
- **hybrid retrieval**：dense + sparse + metadata 融合，当前仅有 experimental overlay
- **query-doc_type routing**：计划中
- **alias dictionary**：术语别名映射，计划中
- **production auth/audit**：计划中
- **多向量存储后端**：计划中
