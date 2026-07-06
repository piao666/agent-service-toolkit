---
source_id: internal_code_summary_official_docs_retriever_py
title: "src/rag/official_docs_retriever.py 代码摘要"
domain: runtime_retrieval
source_type: internal_engineering_docs
doc_type: code_summary
enabled: false
allowed_for_answer: false
corpus: internal_engineering_docs
version: v1
owner_phase: phase4fh
---

# src/rag/official_docs_retriever.py 代码摘要

## 模块概述
Phase 4E runtime retrieval 包装器。提供配置验证和 official_docs bge-m3 检索的对外 API。直接复用 `rag.retriever.retrieve()`。lazy import 设计确保本地（无 langchain）环境下 import 不崩溃。

## 关键函数
| 函数 | 签名 | 说明 |
|------|------|------|
| `validate_runtime_config()` | `→ dict` | 三档验证：local_config_values_pass + hpc_runtime_resources_pass + overall |
| `official_docs_retrieve()` | `(query, top_k) → dict` | 检索 + trace，返回 results + 13 字段 trace |
| `_get_collection_count_direct()` | `(persist_dir, collection_name) → int\|None` | chromadb 直连计数，不触发 langchain 导入链 |

## 输入/输出
- **输入**: query (str), top_k (int, 默认 5)
- **输出**: `{"results": [...], "trace": {13 fields}}` — results 含 chunk_id/source_id/score/text_preview 等

## 配置依赖
- `rag_settings.CHROMA_PERSIST_DIR`, `rag_settings.chroma_collection_name`, `rag_settings.RAG_DEFAULT_TOP_K`

## 运行时风险
1. **lazy import 延迟**: `retrieve()` 首次调用才加载 bge-m3 模型（GPU 3-5s），API 首请求延迟高
2. **langchain 依赖**: 实际检索需要完整 langchain 栈，本地轻量环境不可用

## 与检索/RAG 的关系
Phase 4E/4H 所有 official_docs 检索的唯一切入点。`corpus_router.py` 路由到 internal 时使用对称的 `internal_engineering_retriever.py`。
