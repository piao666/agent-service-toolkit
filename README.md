# 企业 AI 应用工程知识库助手 (enterprise_kb_v1)

面向企业 AI 研发团队的知识库问答平台，解决技术文档分散、检索召回率低、多轮对话上下文丢失、答案不可溯源等工程痛点。覆盖语料治理、双语料检索、Agent 图编排、证据校验、双层记忆与可审计后台的完整 RAG 链路。

> **项目定位**：小型企业 AI 工程知识库平台 MVP，支持 official_docs（官方技术文档）与 internal_engineering_docs（内部工程经验）双语料统一检索与问答。

---

## 项目成效

- **语料规模**：完成 1117 条 official_docs chunks（18 sources，覆盖 FastAPI/Pydantic/Chroma/LangGraph 官方文档）与 508 条 internal_engineering_docs chunks（32 sources，覆盖系统架构、代码摘要、失败案例、工程经验）的结构化入库。
- **检索效果**：在 25 个真实业务 query 的 HPC 评测集上，5 路多通道检索相比单路向量基线，**hit@3 从 87.5% 提升至 91.7%**，MRR 从 0.7778 提升至 0.7951，dual query 路由准确率 100%，citation validity 1.0。
- **可审计性**：每次问答保留 retrieval_trace / memory_trace / long_term_memory_trace / citation_trace 完整审计链路，支持通过 Admin Console 查看记忆事件与来源治理状态。
- **记忆治理**：长期记忆采用 pending → approved → disabled 三级状态机，管理员审核后生效，避免 LLM 自动写入不可靠记忆污染后续对话。

---

## 技术架构

```
Python 3.10 + FastAPI + LangGraph + ChromaDB + bge-m3 + SQLite + DeepSeek/Qwen + Streamlit
```

| 层级 | 技术选型 | 职责 |
|------|---------|------|
| 嵌入层 | bge-m3 (1024 dim) | 官方与内部文档统一 embedding，经 Embedding A/B（对比 bge-small/e5/qwen3-embedding）验证选型 |
| 向量存储 | ChromaDB PersistentClient | 双语料独立 collection，支持 metadata filtering 与 similarity search |
| 检索层 | 5 路异步检索 + 4 阶段后处理 | official_vector / internal_vector / keyword_bm25 / metadata_filter / history_aware |
| 编排层 | LangGraph StateGraph | 8 节点确定性流水线（query_classifier → memory_rewriter → planner → retriever → ranker → answer_generator → evidence_verifier → final_response） |
| 记忆层 | Session Memory (内存) + Long-term Memory (SQLite) | 短期多轮上下文 + 长期项目约束审核生效 |
| 服务层 | FastAPI | 检索 API、Graph 问答 API、Memory Admin API |
| 前端层 | Streamlit | 用户问答端 + Memory Admin Console + Source/Eval/Trace Viewer |

---

## 核心能力

### 1. 语料治理与双语料库

- **Source Registry 准入机制**：每个 source 需登记 source_id、title、source_type、origin_url、document_status、enabled、allowed_for_answer 等字段，通过审核后才进入检索或回答链路。
- **Official Docs**：外部官方技术文档（FastAPI、Pydantic、Chroma、LangGraph、OpenAI 等），经 URL 验证、Text/DOM 采集、evidence audit 后入库。
- **Internal Engineering Docs**：内部工程知识（系统架构、RAG pipeline、代码摘要、失败案例、HPC 经验、repo hygiene），经 gold label 语义 review 后纳入。

### 2. 多路检索与融合排序

5 路异步检索通道并行执行，经 4 阶段后处理输出 citation candidates：

| 阶段 | 策略 | 目的 |
|------|------|------|
| Chunk 去重 | 按 chunk_id 保留最高分 | 消除多路重复召回 |
| 分数归一化 | Min-Max 到 [0,1] | 统一向量相似度与 BM25 分数尺度 |
| Source 截断 | 每个 source_id 最多保留 3 条 | 避免单一 source 占满 top_k |
| 语料平衡 | Round-robin 分配 official / internal | 防止 dual query 时某一语料库垄断结果 |

### 3. LangGraph 节点化问答与证据校验

- **8 节点确定性流水线**：每个节点独立执行、独立 trace，错误定位从"全链路排查"降至"单节点 trace"。
- **Citation Guard**：校验引用 chunk_id 是否属于 retrieved_chunks 集合，拦截空引用与非法引用。
- **幻觉风险标记**：输出 unsupported_claims 与 hallucination_risk，抑制大模型无依据生成。

### 4. 双层记忆与可审计设计

- **Session Memory**：基于 session_id 的短期记忆，支持多轮指代消解（"它"、"这个"、"继续"）与 query 改写。
- **Long-term Memory**：SQLite 持久化，三级状态流转：
  - `pending`：候选记忆，不参与回答
  - `approved`：管理员审核通过，参与后续 query rewrite
  - `disabled`：失效记忆，不再进入上下文
- **Memory Events**：记录 candidate_created / candidate_approved / memory_disabled 等完整生命周期事件。

---

## 评测数据

### Phase 6F：多路检索 HPC 真实评测

| 指标 | 单路 Dense Baseline | 5 路 Multi-channel | Delta |
|------|--------------------|--------------------|-------|
| hit@3 | 87.50% | 91.67% | +4.17% |
| hit@5 | 95.83% | 95.83% | — |
| hit@10 | 95.83% | 100.00% | +4.17% |
| MRR | 0.7778 | 0.7951 | +0.0173 |
| dual_accuracy | — | 100.00% | — |
| citation_validity | — | 100.00% | — |

> 评测环境：HPC (NVIDIA L40, CUDA 12.4)，25 个真实业务 case，覆盖 official_only / internal_only / dual / keyword / metadata / history-aware 六类场景。

### Phase 4FH：内部语料严格评测

| 指标 | 初版 | 修复后 |
|------|------|--------|
| hit@3 | 60.00% | 93.33% |
| hit@5 | 73.33% | 96.67% |
| hit@10 | 86.67% | 100.00% |

> 修复内容：gold label 语义 review（17 条 correction）、D 组代码摘要补录、per-case debug 根因分析。

---

## 快速开始

### 1. 环境配置

```bash
# 克隆仓库
git clone https://github.com/piao666/agent-service-toolkit.git
cd agent-service-toolkit
git checkout feature/enterprise-kb-v1-clean

# 安装依赖
pip install -r requirements.txt

# 配置环境变量（复制模板后填入真实 API Key）
cp .env.example .env
# 配置 Qwen / DeepSeek API Key 与本地 bge-m3 模型路径
```

### 2. 启动服务

```bash
# 启动 FastAPI 后端
python -m uvicorn src.service.service:app --host 127.0.0.1 --port 8000

# 启动 Streamlit 前端（含 Memory Admin Console）
streamlit run frontend/streamlit_app.py
```

### 3. 调用示例

**POST /api/enterprise-kb/graph/answer**

```json
{
  "query": "FastAPI 中如何配置 CORS 中间件？",
  "corpus": "dual",
  "session_id": "auto_xxxxxxxx"
}
```

**Response：**

```json
{
  "answer_markdown": "在 FastAPI 中配置 CORS 中间件...",
  "citations": [
    {
      "chunk_id": "chunk_xxx",
      "source_id": "fastapi_cors",
      "corpus": "official_docs",
      "quoted_evidence": "from fastapi.middleware.cors import CORSMiddleware..."
    }
  ],
  "unsupported_claims": [],
  "hallucination_risk": "low",
  "memory_trace": { "session_memory_used": true, "rewritten_query": "..." },
  "long_term_memory_trace": { "approved_memory_count": 2, "approved_memory_ids": ["mem_xxx"] },
  "retrieval_trace": { "route_mode": "dual", "channels": ["official_vector", "internal_vector", "keyword_bm25"], ... }
}
```

---

## 项目目录

```
├── data/enterprise_kb_v1/
│   ├── source_registry/          # 语料准入注册表
│   ├── raw_sources/              # 原始文档
│   ├── chunks/                   # 切分后的结构化 chunk
│   └── eval/                     # 评测数据集
├── src/
│   ├── rag/                      # 检索核心（embedding、Chroma、5路检索、后处理）
│   ├── custom_graph/             # LangGraph 8节点编排
│   ├── llm/                      # Qwen / DeepSeek 模型抽象
│   ├── session_memory/           # 短期会话记忆
│   ├── long_term_memory/         # 长期记忆持久化（SQLite）
│   ├── schema/                   # API 请求/响应模型
│   └── service/                  # FastAPI 服务入口
├── frontend/
│   └── streamlit_app.py          # 用户问答 + Admin Console
├── scripts/enterprise_kb_v1/     # 各阶段 Smoke 测试与评测脚本
├── reports/enterprise_kb_v1/     # 阶段评测报告
└── storage/                      # Chroma 向量索引（不提交 Git）
```

---

## 当前状态与扩展性

- **当前状态**：MVP-ready，支持 controlled demo 与 evaluation-ready 运行。reranker=false，LLM 使用 mock_extractive / grounded answer 模式。
- **可扩展方向**：
  - Vectorized Memory Retrieval：长期记忆语义召回
  - Cross-project Memory：多项目记忆隔离
  - RBAC 权限体系：corpus / source / memory 级权限控制
  - Production Deployment：PostgreSQL + Redis + Docker + 监控

---

## 贡献说明

本项目基于 [agent-service-toolkit](https://github.com/piao666/agent-service-toolkit) 开源框架扩展，在上游提供的 FastAPI + LangGraph 骨架之上，新增并验证了：企业知识库语料治理、双语料检索、5 路多通道检索、系统化评测体系、双层记忆与审核机制、可审计 Agent 图编排。
