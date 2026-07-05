# Phase 3G Verified Sources Text/DOM 正式采集计划

> 版本: v1 | 时间: 2026-07-05 | 阶段: Phase 3G (dry-run plan)
> 状态: 计划完成，待审批后进入 Phase 3H 真实采集

---

## 一、Source 数量校验

| 类型 | 数量 | 预期 |
|------|:--:|:--:|
| external_official 总数 | **21** | 21 |
| url_status=verified | **19** | 19 |
| url_status=needs_manual_review | **2** | 2 (均为 Qwen) |
| Qwen 排除采集计划 | ✅ 已排除 | both Qwen |

**来源**: `source_registry.yaml` + `official_docs_allowlist.yaml`，交叉验证一致。

---

## 二、19 条 Verified Source 清单

### Domain: api_backend (6)

| source_id | origin_url |
|-----------|-----------|
| fastapi_official_routing | https://fastapi.tiangolo.com/tutorial/path-params/ |
| fastapi_official_request_body | https://fastapi.tiangolo.com/tutorial/body/ |
| fastapi_official_dependency_injection | https://fastapi.tiangolo.com/tutorial/dependencies/ |
| fastapi_official_middleware | https://fastapi.tiangolo.com/tutorial/middleware/ |
| fastapi_official_error_handling | https://fastapi.tiangolo.com/tutorial/handling-errors/ |
| pydantic_official_models_validation | https://docs.pydantic.dev/latest/concepts/models/ |

### Domain: vector_database (5)

| source_id | origin_url |
|-----------|-----------|
| chroma_official_collections | https://docs.trychroma.com/docs/collections/manage-collections |
| chroma_official_add_query | https://docs.trychroma.com/docs/querying-collections/query-and-get |
| chroma_official_persistence | https://docs.trychroma.com/docs/run-chroma/client-server |
| chroma_official_metadata_filter | https://docs.trychroma.com/docs/querying-collections/metadata-filtering |
| chroma_official_embedding_functions | https://docs.trychroma.com/docs/embeddings/embedding-functions |

### Domain: agent_orchestration (5)

| source_id | origin_url |
|-----------|-----------|
| langgraph_official_stategraph | https://docs.langchain.com/oss/python/langgraph/graph-api |
| langgraph_official_nodes_edges | https://langchain-ai.github.io/langgraph/concepts/low_level/ |
| langgraph_official_conditional_edges | https://langchain-ai.github.io/langgraph/how-tos/branching/ |
| langgraph_official_checkpoint_memory | https://langchain-ai.github.io/langgraph/concepts/persistence/ |
| langgraph_official_tool_calling | https://langchain-ai.github.io/langgraph/how-tos/tool-calling/ |

### Domain: llm_provider (3)

| source_id | origin_url |
|-----------|-----------|
| openai_official_chat_completions | https://platform.openai.com/docs/api-reference/chat/create |
| openai_official_structured_outputs | https://platform.openai.com/docs/guides/structured-outputs |
| openai_official_streaming | https://platform.openai.com/docs/api-reference/streaming |

---

## 三、正式采集目录结构

```
data/enterprise_kb_v1/raw_sources/official_docs/{source_id}/v1/
  ├── raw.html
  ├── normalized.md
  └── text_metadata.json
```

每条 source 的 `planned_output_dir` 统一指向 `data/enterprise_kb_v1/raw_sources/official_docs/{source_id}/v1/`，与 `source_registry.yaml` 中 `local_path` 字段一致。

---

## 四、Batch 执行策略

| 参数 | 值 |
|------|-----|
| 每批最多 | **5 条** |
| 总批次 | **4 批** |
| 失败策略 | **停止整批，不继续下一批** |
| 每批产物 | audit.json + manifest.yaml + report.md |

### 批次分配

| Batch | 条数 | Source |
|:--:|:--:|------|
| 1 | 5 | fastapi_official_routing, fastapi_official_request_body, fastapi_official_dependency_injection, fastapi_official_middleware, fastapi_official_error_handling |
| 2 | 5 | pydantic_official_models_validation, chroma_official_collections, chroma_official_add_query, chroma_official_persistence, chroma_official_metadata_filter |
| 3 | 5 | chroma_official_embedding_functions, langgraph_official_stategraph, langgraph_official_nodes_edges, langgraph_official_conditional_edges, langgraph_official_checkpoint_memory |
| 4 | 4 | langgraph_official_tool_calling, openai_official_chat_completions, openai_official_structured_outputs, openai_official_streaming |

---

## 五、质量门禁

详见 `docs/enterprise_kb_v1/text_dom_capture_quality_gate.md`。

---

## 六、失败处理策略

| 场景 | 处理 |
|------|------|
| 页面不可访问 | `fetch_status=failed`，跳过本条 |
| 主题不匹配 | 人工审查，`doc_status=topic_mismatch` |
| 空内容 | raw.html < 500 bytes 判为 FAIL |
| 表格丢失 | extraction_warning，不阻塞 |
| Code block 丢失 | extraction_warning |
| 动态内容缺失 | MCP Playwright 重试，仍失败 → `fetch_status=js_required` |
| URL 跳转异常 | 记录 final_url，域名变更 > 1 次则人工审查 |

---

## 七、排除项

| source_id | 原因 |
|-----------|------|
| qwen_official_openai_compatible_api | `needs_manual_review`，text_capture 禁用 |
| qwen_official_model_parameters | `needs_manual_review`，text_capture 禁用 |

---

## 八、不执行清单

本阶段 (Phase 3G) 是 dry-run plan：

| 操作 | 状态 |
|------|:--:|
| 抓取任何 URL | ❌ |
| 生成 raw.html / normalized.md | ❌ |
| 截图 | ❌ |
| 创建 Chroma / embedding / index | ❌ |
| 修改 registry / allowlist | ❌ |
| 迁移 experiment | ❌ |
