# Final Chroma 索引修复与统一构建

> 日期：2026-06-25
> 分支：`feature/enterprise-rag-backend`
> 不调用 LLM，不提交 Chroma 数据库目录。

## 问题根因

项目之前同时存在两个 Chroma 向量库，metadata schema 不兼容：

| 库 | 目录 | Collection | 内容 | 数量 | metadata 主键 |
|---|---|---|---|---|---|
| 小型库 | `chroma_enterprise` | `enterprise_knowledge_base` | 4 篇项目说明文档 | 6 chunks | `source`, `title`, `doc_type`, `chunk_id`, `chunk_index` |
| Phase6 库 | `chroma_enterprise_phase6` | `enterprise_ai_learning_kb_reviewed` | FastAPI/NLP/深度学习/Agent 课程 | 80 chunks | `source_id`, `source_url`, `section_path`, `domain`, `normalized_id`, `language`, `review_status`, ... |

**核心问题**：`retriever.py` 的 `_result_from_document()` 函数使用 `metadata.get("source", "unknown")` 解析 source 字段。Phase6 库使用 `source_id` 而非 `source`，导致检索结果顶层 `source` 始终为 `unknown`。

## 修复内容

### A. metadata schema 兼容 (`src/rag/retriever.py`)

- 新增 `_resolve_source()` 函数，按优先级解析 source：
  `source_id` → `source_url` → `source` → `"unknown"`
- 替换 `_result_from_document()` 中的 `source` 赋值逻辑

### B. source payload 扩展 (`src/agents/enterprise_tools.py`)

- `_source_payload()` 新增字段：`source_id`、`source_url`、`section_path`、`domain`、`normalized_id`、`language`、`review_status`
- `_format_context()` 新增 `source_id` 行，便于在上下文中追踪来源

### C. 最终 Chroma 构建 (`scripts/build_final_enterprise_chroma.py`)

- 合并 Phase6 技术资料 + `data/enterprise_docs/` 项目说明文档
- 输出到 `chroma_enterprise_final` / `enterprise_knowledge_base`
- 默认 dry-run，`--execute --reset-final` 写入
- 不调用 LLM

### D. Chroma 审计 (`scripts/audit_chroma_collections.py`)

- 列出所有已知 Chroma 库的 count、source_id 分布、metadata keys、关键文档覆盖
- 只读不写，不加载 embedding 模型

### E. 配置更新 (`.env.example`)

- 推荐配置更新为指向最终合并库

## 验证结果

### Final collection 概况

| 指标 | 值 |
|---|---|
| 总 chunks | 86 |
| 唯一 sources | 9 |
| fastapi_docs 覆盖 | ✅ 16 chunks |
| enterprise_rag_pipeline 覆盖 | ✅ 2 chunks |
| enterprise_agent_overview 覆盖 | ✅ 2 chunks |

### source_id 分布 Top 10

| source_id | chunks |
|---|---|
| local_ai_agent_course_pdf | 23 |
| repo_project_files | 17 |
| local_nlp_course_docx | 16 |
| fastapi_docs | 16 |
| local_deep_learning_course_docx | 8 |
| enterprise_agent_overview | 2 |
| enterprise_rag_pipeline | 2 |
| enterprise_model_provider_policy | 1 |
| enterprise_prompt_guidelines | 1 |

### FastAPI / Request Body 检索验证

```
查询: "FastAPI 里 Request Body 如何定义？"
结果: source=fastapi_docs (不再是 unknown)
  [1] Request Body - FastAPI, score=0.9213
  [2] Request Body - FastAPI, score=0.9084
  [3] Request Body - FastAPI, score=0.9081
  [4] Path Parameters - FastAPI, score=0.8273
  [5] Repository YAML sample, score=0.7683
```

### 系统检索流程验证

```
查询: "这个系统是如何进行检索的？"
结果:
  [1] local_ai_agent_course_pdf, score=0.6945
  [2] enterprise_rag_pipeline, score=0.6910  ← 命中
  [3] enterprise_agent_overview, score=0.6906 ← 命中
  [4] enterprise_agent_overview, score=0.6860 ← 命中
  [5] local_ai_agent_course_pdf, score=0.6810
```

### LoRA 语料缺口

LoRA 检索在所有 top_k 档位下无直接 source_id / 内容命中，确认为语料缺口。当前 corpus 不包含 LoRA 专题文档。报告中记录但不硬修。

## 不修改的模块

严格遵守本轮禁令，未修改以下文件：
- `src/service/service.py`
- `src/agents/enterprise_rag_graph.py`
- `src/streamlit_app.py`
- prompt 相关文件
- verifier / judge / multi-hop 相关文件

## 已知限制

1. LoRA 检索无命中是语料缺口，不是 metadata 或检索策略问题
2. Final collection 包含 86 chunks，覆盖有限，不是完整生产级知识库
3. 未运行 240-case 评估或真实 LLM 端到端验证
4. metadata schema 兼容性修复是向后兼容的：小型库的 `source` 字段仍然能正确解析
