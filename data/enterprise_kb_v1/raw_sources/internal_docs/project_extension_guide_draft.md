---
source_id: internal_project_extension_guide_draft
title: "项目扩展指南草案 (内部文档)"
domain: internal_engineering
source_type: internal_project
doc_type: internal_markdown
authority_level: internal_current_snapshot
doc_status: draft
allowed_for_answer: false
answer_scope: future_plan
code_reference: >
  src/agents/, src/rag/, src/service/service.py,
  data/enterprise_kb_v1/source_registry/source_registry.yaml
last_verified: null
notes: >
  草案阶段。包含规划中的扩展方式，未实现内容已明确标注 planned/draft。
  不可作为当前系统行为的依据。
---

# 项目扩展指南草案

> ⚠️ 本文档中标记为 planned/draft 的内容为后续规划，当前代码**未实现**。
> 仅描述扩展接口和预期方向，不承诺最终实现方式。

## 一、新增知识源

### 1.1 当前状态

新知识源的唯一准入入口是 `source_registry.yaml`。当前 registry 中共 9 条 source（Phase 1 的 4 条示例 + Phase 2A 的 5 条 internal docs），全部 `enabled=false`（草案阶段）。

### 1.2 新增步骤（当前可用）

1. 在 `source_registry.yaml` 的 `sources` 列表中添加新条目
2. 设置 `enabled=false`、`allowed_for_answer=false`（准入审核前）
3. 填写必填字段：source_id、title、domain、source_type、doc_type、authority_level、local_path、version_policy、owner
4. **人工审核**后改为 `enabled=true`
5. 运行 ingestion pipeline 入库

### 1.3 当前 source_type 枚举

- `external_official`：外部官方文档（如 FastAPI 官网、Chroma 文档）
- `internal_project`：项目内部文档（如本文档）
- `policy`：团队工程规范（planned）
- `runbook`：故障排查手册（planned）

### 1.4 Planned/Draft：自动化抓取

以下功能当前**未实现**，属于规划：

- **外部 URL 自动抓取**：将 origin_url 的网页内容自动下载到 local_path（planned）
- **HTML → Markdown 自动转换**（planned）
- **自动 chunk 切分 + 入库**：从 raw → normalized → chunks → Chroma 的全自动 pipeline（draft）
- **版本追踪**：外部文档版本变更时自动重新抓取（planned）

## 二、新增工具

### 2.1 当前工具注册机制

工具定义在 `src/agents/tools.py`（LangChain `@tool` 装饰器）。当前企业 RAG 检索工具定义在 `src/agents/enterprise_tools.py`：

```python
enterprise_retrieval_tool: BaseTool = tool(enterprise_knowledge_retriever_func)
enterprise_retrieval_tool.name = "enterprise_knowledge_retriever"
```

### 2.2 新增工具步骤（当前可用）

1. 在 `src/agents/` 下创建工具函数
2. 使用 `@tool` 装饰器或 `BaseTool` 子类包装
3. 在对应 Agent Graph 中导入并在节点中调用

### 2.3 Planned/Draft：工具自动发现

以下功能当前**未实现**：

- **tool registry**：统一的工具注册表，自动发现 `src/agents/` 下所有 `BaseTool` 子类（planned）
- **MCP server 集成**：通过 MCP 协议接入外部工具服务（`src/agents/github_mcp_agent/` 有 GitHub MCP 示例，但企业 RAG 链路未接入 MCP）
- **动态工具路由**：根据 query_type 自动选择工具（planned）

## 三、新增 Graph 节点

### 3.1 当前 Graph 架构

系统有两套 graph：

- **Legacy** (`enterprise_rag_agent.py`)：线性节点序列，无条件分支
- **Custom Graph** (`enterprise_rag_graph.py`)：条件路由 + 可注入 retriever/answer_generator

### 3.2 在 Custom Graph 中新增节点（当前可用）

`build_enterprise_rag_graph()` 的设计支持扩展：

1. 定义新节点函数：`async def my_node(state: EnterpriseRAGGraphState) -> EnterpriseRAGGraphState`
2. 在 `build_enterprise_rag_graph()` 中 `graph.add_node("my_node", my_node)`
3. 修改条件路由函数添加入边/出边

当前 `_append_node()` 工具函数自动记录节点执行到 `graph_debug.nodes_executed`。

### 3.3 Planned/Draft：节点热插拔

以下功能当前**未实现**：

- **yaml 配置驱动 graph**：通过 yaml 定义节点序列而非硬编码（draft）
- **节点版本管理**：不同版本节点共存，A/B 测试（planned）
- **节点级超时/重试**：每个节点独立的 timeout 和 retry 策略（planned）

## 四、新增 Agent 模式

### 4.1 当前机制

`ENTERPRISE_AGENT_GRAPH_MODE` 环境变量控制 `/enterprise/agent/query` endpoint 使用哪个 graph：

- `legacy` → `enterprise_rag_agent.py` 的 compiled graph
- `custom_graph` → `enterprise_rag_graph.py` 的 `get_enterprise_rag_graph()`

### 4.2 新增 Agent 模式步骤（当前可用）

1. 创建新的 graph 模块（如 `src/agents/my_custom_agent.py`）
2. 在 `src/service/service.py` 的 endpoint 中添加新的 `graph_mode` 分支
3. 或在 `RagSettings` 中添加新的 mode 值并扩展 `agent_graph_mode` property

### 4.3 Planned/Draft

- **多 Agent 协作**：当前 `langgraph_supervisor_agent.py` 有 supervisor 模式示例，但企业 RAG 未集成（draft）
- **Agent 注册表**：统一的 agent 发现和注册机制（planned）

## 五、新增 Embedding Provider

### 5.1 当前状态

`get_embedding_model()` 仅支持 `provider="local"`。非 local 值抛出 `ValueError`。

### 5.2 Planned/Draft

- **OpenAI embedding**：通过 `OPENAI_API_KEY` 使用 `text-embedding-3-small` 等模型（planned）
- **其他 embedding provider**：HuggingFace Inference API、Voyage AI 等（draft）

## 六、扩展约束

1. **所有新 source 必须走 source_registry 准入流程**
2. **新工具/节点必须保持 graph_debug 输出兼容**（否则破坏现有评测）
3. **新 Agent 模式不能替代 legacy** — legacy 是稳定 baseline
4. **新增扩展不可引入旧工作区路径/文件名/实验编号**
