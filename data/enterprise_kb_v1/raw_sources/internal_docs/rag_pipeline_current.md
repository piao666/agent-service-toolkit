---
source_id: internal_rag_pipeline_current
title: "当前 RAG 查询链路与检索架构 (内部文档)"
domain: internal_engineering
source_type: internal_project
doc_type: internal_markdown
authority_level: internal_current_snapshot
doc_status: draft
allowed_for_answer: false
answer_scope: current_behavior
code_reference: >
  src/rag/retriever.py, src/rag/retrieval_policy.py,
  src/rag/structured_retrieval.py, src/rag/evidence_verifier.py,
  src/rag/conversation_memory.py, src/rag/llm_judge.py,
  src/rag/planner.py, src/rag/vector_store.py,
  src/rag/embeddings.py, src/agents/enterprise_tools.py
last_verified: null
notes: >
  草案阶段，基于 2026-07-04 代码快照。描述当前 RAG pipeline 真实架构。
---

# 当前 RAG 查询链路

## 一、检索入口

### 1.1 工具函数入口

`src/agents/enterprise_tools.py` 中的 `enterprise_knowledge_retriever_func()` 是唯一检索入口。
被 legacy agent (`enterprise_rag_agent.py`) 的 `retrieve` 节点和 custom_graph (`enterprise_rag_graph.py`) 的 `retriever_node` 共同调用。

### 1.2 检索有效负载构建

`build_enterprise_retrieval_payload()` 是核心检索编排函数，按以下顺序执行：

1. **参数归一化**：`_normalize_top_k()` 校验 top_k（默认 5，上限 20）
2. **前置检查**：
   - embedding provider 必须为 `local`
   - 本地 embedding 模型路径必须存在
   - Chroma persist_dir 必须存在
   - collection 必须存在且 count > 0
3. **策略路由**：根据 `ENTERPRISE_RAG_POLICY_MODE` 选择检索函数：
   - `query_type_aware` → `retrieve_with_policy()`
   - `targeted_overlay` 或 structured 模式已启用 → `retrieve_with_overlay()`
   - 默认 → `retrieve()`（纯密集检索 baseline）
4. **结构化检索注入**：调用 `structured_retrieve()` + `materialize_structured_candidates()` 将 metadata/symbol 命中注入结果
5. **source_catalog patch**：feature-flag 控制，默认关闭

## 二、三大检索策略

### 2.1 baseline（`retrieve()`）

纯密集向量检索。流程：
1. `get_embedding_model()` → `HuggingFaceEmbeddings`（本地模型）
2. `get_vector_store()` → `Chroma`（持久化客户端）
3. `vector_store.similarity_search_with_score(query, k=top_k)`
4. `_apply_query_hints()`：对 FastAPI/LoRA 等外部技术查询的类型感知 boost/demote

### 2.2 query_type_aware（`retrieve_with_policy()`）

`decide_gated_retrieval_policy()` 根据 `infer_query_type()` 推断查询类型，选择对应策略：

| 查询类型 | 策略 | 触发条件 |
|----------|------|----------|
| exact_metadata_lookup | metadata_first | 查询含 source_id/doc_type 等字段名 |
| code_api_config | sparse_first_bm25 | 含 config/endpoint/schema 等代码术语 |
| short_keyword | sparse_first_bm25 | 短查询 + 含代码特征 |
| citation_required_query | citation_aware_evidence | 含"引用"/"出处"/"evidence"等 |
| ambiguous_query | clarification_first | 不启用（仅 debug） |
| 普通查询 | dense_sparse_fusion | 默认 |

策略结果通过 `_merge_unique_results()` 与 baseline 密集结果合并去重。

### 2.3 targeted_overlay（`retrieve_with_overlay()`）

永远保留 baseline dense retrieval。仅在 `decide_overlay()` 判断 ≥2 个强信号时叠加 metadata_overlay 或 sparse_overlay 的 score boost。非目标查询完全 baseline passthrough。

## 三、结构化检索

`ENTERPRISE_STRUCTURED_RETRIEVAL_MODE=metadata_symbol` 时启用。在 baseline 之后运行，不影响 baseline 结果：

- `structured_retrieve()`：按 source_id/doc_type/API path/函数名等精确匹配
- `materialize_structured_candidates()`：从 source catalog 的 metadata/symbol 索引中物化匹配 chunk
- 注入主结果集，去重后按 relevance_score 重排

## 四、Evidence Verifier

`src/rag/evidence_verifier.py` — 当前仅支持 `rule_based` 模式（`ENTERPRISE_EVIDENCE_VERIFIER_MODE=rule_based`）。

`verify_answer_grounding()` 输出：
- `grounding_score`: float（0-1）
- `grounding_status`: "well_grounded" | "partially_grounded" | "insufficient"
- `citation_coverage`: dict
- `matched_terms`: list[dict]
- `unsupported_terms`: list[str]

当 `safe_fallback_enabled=True` 且 grounding 不足时，`build_safe_fallback_answer()` 替换答案为安全回退。

## 五、会话记忆

`src/rag/conversation_memory.py` — `ENTERPRISE_MEMORY_MODE=buffer` 时启用。

- `MemoryStore`：进程内 `dict` 存储，按 session_id 隔离
- `contextualize_query_with_memory()`：对 follow-up 查询做简单的上下文拼接
- `max_turns=5`，`max_answer_chars=1000`（可配置）
- 服务重启后清空

## 六、LLM Judge

`src/rag/llm_judge.py` — `judge_answer_rule_based()`。
- 当前仅 `rule_based_fallback` 模式
- 检查：answer 是否为空、是否与 sources 内容有基础匹配、是否包含回退短语
- 输出 verdict: "pass" | "fail" | "needs_review"

## 七、Planner

`src/rag/planner.py` — `plan_query()`。
- `ENTERPRISE_PLANNER_MODE=debug_only`：只记录到 planner_debug，不改变路由
- `planner_type`: "simple" | "complex" | "multi_hop" | "ambiguous" | "unsupported"
- 注：`infer_graph_query_type()` 返回 "semantic_qa" 等查询类型，但 `plan_query()` 的 planner_type 使用独立的命名空间（simple/complex），两者不共享枚举
- 在 custom_graph 的 planner_node 中运行

## 八、检索的 fallback 路径

`build_enterprise_retrieval_payload()` 在以下情况触发 fallback：
- empty_query：查询为空
- invalid_top_k：top_k 非法
- unsupported_embedding_provider：非 local 嵌入
- embedding_model_path_missing：嵌入模型路径不存在
- chroma_persist_dir_missing：Chroma 持久化目录不存在
- chroma_collection_missing：collection 不存在
- chroma_collection_empty：collection 为空
- retrieval_error：向量查询/策略执行异常
- no_retrieval_hits：检索返回 0 条结果
