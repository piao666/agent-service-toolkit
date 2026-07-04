# Demo 场景设计

> 版本: v1-draft | 状态: planned | 最后更新: 2026-07-04

---

## 场景总览

| # | 场景 | 类型 | 覆盖 source | 目标 |
|---|------|------|------------|------|
| 1 | 官方技术问答 | technical_reference | fastapi/chroma/langgraph 官方文档 | 验证外部文档 RAG 质量 |
| 2 | 项目运行配置问答 | current_behavior | internal_project_runtime_snapshot | 验证内部文档 RAG 质量 |
| 3 | RAG 故障排查问答 | troubleshooting | 内部 runbook | 验证排障知识可用性 |
| 4 | 知识库治理问答 | engineering_policy | source_registry + policies | 验证治理文档可检索 |

---

## 场景 1: 官方技术问答

**示例 query：**

```
"FastAPI 中请求体使用 Pydantic BaseModel，当字段校验失败时返回什么状态码？"
"Chroma 如何创建一个带 metadata filter 的 collection？"
"LangGraph 的 StateGraph 和 MessageGraph 有什么区别？"
"如何在 FastAPI endpoint 中使用 dependency injection？"
"Chroma 支持哪些 embedding function？"
```

**验证点：**
- 回答正确引用官方文档原文
- 代码示例准确
- 版本信息标注清楚

---

## 场景 2: 项目运行配置问答

**示例 query：**

```
"当前系统默认使用什么 embedding 模型？如何更换？"
"RAG pipeline 中的 retrieval policy 是如何工作的？"
"系统的 chat API endpoint 在哪里定义？"
"如何配置 MySQL/PostgreSQL 替代默认 SQLite？"
```

**验证点：**
- 回答反映当前代码实际行为（非旧版本）
- 配置项路径准确（如 `rag_settings.CHROMA_PERSIST_DIR`）
- 不泄露敏感信息

---

## 场景 3: RAG 故障排查问答

**示例 query：**

```
"为什么我的知识库查询返回空结果？可能的原因有哪些？"
"Chroma collection count 返回 0，但文件明明存在，怎么排查？"
"embedding 维度不匹配报错，如何确认正确的维度？"
"检索返回的结果和问题不相关，可能是哪些环节出问题？"
```

**验证点：**
- 给出系统化的排查步骤
- 每条步骤有明确的检查命令
- 覆盖最常见的失败模式

---

## 场景 4: 知识库治理问答

**示例 query：**

```
"如何给知识库新增一个外部文档来源？"
"source_registry 中 enabled=false 和 enabled=true 有什么区别？"
"document_status_policy 中 planned 和 draft 的差异是什么？"
"什么是 source_id 的命名规范？"
```

**验证点：**
- 正确引用 policies 文档
- 区分 policy（应遵守）和 implemented（当前行为）
- 指向具体的文档路径和字段

---

## 评估标准

每个场景的 demo 通过标准：

1. 答案中关键术语与 source_registry 一致（source_id、domain、doc_status 等）
2. 技术回答引用外部文档时有明确出处
3. 内部行为回答不出现幻觉（不杜撰不存在的配置项）
4. 排查建议可执行（有具体命令/检查点）
