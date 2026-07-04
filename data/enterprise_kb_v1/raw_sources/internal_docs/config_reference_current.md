---
source_id: internal_config_reference_current
title: "当前系统关键配置参考 (内部文档)"
domain: internal_engineering
source_type: internal_project
doc_type: internal_markdown
authority_level: internal_current_snapshot
doc_status: draft
allowed_for_answer: false
answer_scope: current_behavior
code_reference: >
  src/rag/config.py, src/core/settings.py,
  .env.example, pyproject.toml
last_verified: null
notes: >
  草案阶段，基于 2026-07-04 代码快照。配置项说明反映 .env.example
  和 RagSettings / Settings 中定义的真实默认值。
---

# 当前系统关键配置参考

## 一、配置体系

系统有两套 Pydantic Settings：

1. **`src/core/settings.py` — `Settings`**：全局配置（LLM Provider、数据库、追踪、语音、端口/主机等）
2. **`src/rag/config.py` — `RagSettings`**：RAG 专有配置（嵌入、Chroma、检索策略、memory、verifier 等）

两套 settings 都从 `.env` 文件自动加载（通过 `python-dotenv`）。

## 二、嵌入与向量存储配置

### 2.1 嵌入模型

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `EMBEDDING_PROVIDER` | `local` | **当前只支持 local**。非 local 值会在检索时触发 fallback |
| `LOCAL_EMBEDDING_MODEL_PATH` | `./models/bge-small-zh-v1.5` | 本地 SentenceTransformer 模型路径 |
| `LOCAL_EMBEDDING_MODEL_ROOT` | null | 可选，设置后路径为 `{ROOT}/bge-small-zh-v1.5` |

嵌入模型通过 `HuggingFaceEmbeddings` 加载，`device="cpu"`，`normalize_embeddings=True`。

### 2.2 Chroma 向量存储

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `CHROMA_PERSIST_DIR` | `./storage/chroma_enterprise_kb_v1` | Chroma 持久化目录 |
| `CHROMA_COLLECTION_NAME` | `enterprise_kb_v1` | 默认 collection 名称 |
| `ENTERPRISE_CHROMA_COLLECTION` | null | 可选覆盖 collection 名称（优先级高于 `CHROMA_COLLECTION_NAME`） |

`RagSettings.chroma_collection_name` property 优先使用 `CHROMA_COLLECTION_NAME`，如果为默认值则回退到 `ENTERPRISE_CHROMA_COLLECTION`。

## 三、RAG 检索配置

### 3.1 检索策略

| 变量 | 默认值 | 可选值 | 说明 |
|------|--------|--------|------|
| `ENTERPRISE_RAG_POLICY_MODE` | `baseline` | baseline / query_type_aware / targeted_overlay | 检索策略模式 |
| `ENTERPRISE_STRUCTURED_RETRIEVAL_MODE` | `off` | off / metadata_symbol | 结构化检索开关 |
| `RAG_CHUNK_SIZE` | 800 | int | chunk 切分大小（ingestion 阶段使用） |
| `RAG_CHUNK_OVERLAP` | 120 | int | chunk 重叠大小 |
| `RAG_DEFAULT_TOP_K` | 5 | int (1-20) | 默认检索结果数 |

### 3.2 Agent Graph 模式

| 变量 | 默认值 | 可选值 | 说明 |
|------|--------|--------|------|
| `ENTERPRISE_AGENT_GRAPH_MODE` | `legacy` | legacy / custom_graph | Agent 编排模式 |
| `ENTERPRISE_MULTI_HOP_MODE` | `off` | off / rule_based | 多跳检索（实测未证明收益，建议保持 off） |
| `ENTERPRISE_PLANNER_MODE` | `debug_only` | active / debug_only | Planner 模式（建议 debug_only） |
| `ENTERPRISE_JUDGE_MODE` | `rule_based_fallback` | off / rule_based_fallback | Judge 模式 |
| `ENTERPRISE_LLM_JUDGE_MODE` | null | null | 预留 LLM judge（当前无 LLM judge 实现） |

### 3.3 Memory 配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `ENTERPRISE_MEMORY_MODE` | `off` | off / buffer。buffer 为进程内 buffer |
| `ENTERPRISE_MEMORY_MAX_TURNS` | 5 | 最大保留轮次 |
| `ENTERPRISE_MEMORY_MAX_ANSWER_CHARS` | 1000 | 每轮答案最大字符数 |

### 3.4 Evidence Verifier 配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `ENTERPRISE_EVIDENCE_VERIFIER_MODE` | `off` | off / rule_based |
| `ENTERPRISE_EVIDENCE_SAFE_FALLBACK` | false | grounding 不足时是否替换答案为安全回退 |
| `ENTERPRISE_EVIDENCE_MIN_SCORE` | 0.30 | grounding 最低阈值 |
| `ENTERPRISE_EVIDENCE_HIGH_SCORE` | 0.60 | grounding 高分阈值 |

## 四、LLM Provider 配置

### 4.1 主要 Provider

| 变量 | 说明 |
|------|------|
| `DEEPSEEK_API_KEY` | **主要开发 provider**（中文 QA） |
| `OPENAI_API_KEY` | OpenAI |
| `ANTHROPIC_API_KEY` | Anthropic Claude |
| `GOOGLE_API_KEY` | Google Gemini |
| `GROQ_API_KEY` | Groq |
| `OPENROUTER_API_KEY` | OpenRouter |
| `OLLAMA_MODEL` | Ollama 模型名（如 llama3.2） |
| `OLLAMA_BASE_URL` | Ollama 服务地址 |
| `USE_AWS_BEDROCK` | AWS Bedrock 开关（bool） |
| `USE_FAKE_MODEL` | Fake 模型开关（demo/test 用） |

### 4.2 OpenAI Compatible

| 变量 | 说明 |
|------|------|
| `COMPATIBLE_MODEL` | 兼容 OpenAI API 的模型名 |
| `COMPATIBLE_API_KEY` | API Key |
| `COMPATIBLE_BASE_URL` | API Base URL |

### 4.3 默认模型选择

`DEFAULT_MODEL` 若未显式设置，根据已配置的 API key 自动选择：
- DeepSeek API key 存在 → `deepseek-chat`
- OpenAI API key 存在 → `gpt-5-nano`
- Anthropic API key 存在 → `claude-haiku-4-5`
- Fake model → `fake`

## 五、服务与数据库配置

### 5.1 服务配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `HOST` | `0.0.0.0` | 服务监听地址 |
| `PORT` | 8080 | 服务监听端口 |
| `AUTH_SECRET` | null | HTTP Bearer token（不设置则无认证） |
| `MODE` | null | `dev` 时启用 uvicorn reload |

### 5.2 数据库配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `DATABASE_TYPE` | sqlite | sqlite / postgres / mongo |
| `SQLITE_DB_PATH` | `checkpoints.db` | SQLite 文件路径 |

PostgreSQL（`DATABASE_TYPE=postgres`）需配置: `POSTGRES_USER`、`POSTGRES_PASSWORD`、`POSTGRES_HOST`、`POSTGRES_PORT`、`POSTGRES_DB`。

## 六、可观测性配置

| 变量 | 说明 |
|------|------|
| `LANGCHAIN_TRACING_V2` | LangSmith 追踪开关 |
| `LANGCHAIN_PROJECT` | LangSmith 项目名 |
| `LANGCHAIN_API_KEY` | LangSmith API Key |
| `LANGFUSE_TRACING` | Langfuse 追踪开关 |
| `LANGFUSE_PUBLIC_KEY` | Langfuse Public Key |
| `LANGFUSE_SECRET_KEY` | Langfuse Secret Key |

## 七、配置优先级

对于 `ENTERPRISE_AGENT_GRAPH_MODE`、`ENTERPRISE_JUDGE_MODE`、`ENTERPRISE_MULTI_HOP_MODE`、`ENTERPRISE_PLANNER_MODE` 等关键 RAG 配置项，`RagSettings` 的 property 使用 `os.getenv()` 读取**进程环境变量**优先于 `.env` 文件中的值。这使得同一次部署可以用不同环境变量启动多个实例（如 legacy 和 custom_graph 分别监听不同端口）。
