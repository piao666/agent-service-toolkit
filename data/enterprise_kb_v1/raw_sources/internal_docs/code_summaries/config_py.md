---
source_id: internal_code_summary_config_py
title: "src/rag/config.py 代码摘要"
domain: runtime_retrieval
source_type: internal_engineering_docs
doc_type: code_summary
authority_level: internal_current_snapshot
doc_status: active
allowed_for_answer: false
answer_scope: current_behavior
enabled: false
corpus: internal_engineering_docs
version: v1
owner_phase: phase4fh
---

# src/rag/config.py 代码摘要

## 模块概述 (module_purpose)
全项目 RAG 配置的单一来源 (Single Source of Truth)。基于 pydantic-settings，所有 `ENTERPRISE_*` / `RAG_*` 前缀环境变量集中管理。模块级单例 `rag_settings = RagSettings()` 被所有 RAG 模块直接导入。

## 关键类与函数 (key_functions_or_classes)
| 类/函数 | 签名 | 说明 |
|----------|------|------|
| `RagSettings` | `class RagSettings(BaseSettings)` | 25 个字段的 pydantic-settings 类，含 8 个计算属性 |
| `rag_settings` | 模块级单例 | `RagSettings()` 实例，全局唯一来源 |
| `local_embedding_model_path` | `@property → Path` | 三档路径解析：自定义路径 → ROOT/bge-m3 → 默认 |
| `chroma_collection_name` | `@property → str` | ENTERPRISE_CHROMA_COLLECTION 优先，否则 CHROMA_COLLECTION_NAME |

## 关键常量
| 名称 | 值 | 用途 |
|------|-----|------|
| `DEFAULT_LOCAL_EMBEDDING_MODEL_PATH` | `./models/bge-m3` | bge-m3 模型路径 |
| `DEFAULT_CHROMA_COLLECTION_NAME` | `enterprise_kb_v1_official_docs_bge_m3` | official_docs 默认 collection |
| `DEFAULT_INTERNAL_CHROMA_COLLECTION_NAME` | `enterprise_kb_v1_internal_engineering_bge_m3` | Phase 4F internal corpus collection |
| `CHROMA_INTERNAL_PERSIST_DIR` | `./storage/chroma_enterprise_kb_v1_internal_bge_m3` | Phase 4F internal persist |

## 输入/输出 (inputs_outputs)
- **输入**: `.env` 文件 + 环境变量 (ENTERPRISE_AGENT_GRAPH_MODE, ENTERPRISE_RAG_POLICY_MODE, ENTERPRISE_CHROMA_COLLECTION 等)
- **输出**: `rag_settings` 单例 → 被 `embeddings.py`, `vector_store.py`, `retriever.py`, `official_docs_retriever.py` 等消费

## 配置依赖 (config_dependency)
- 依赖: `pydantic-settings`, `python-dotenv`
- 被依赖: 所有 `src/rag/*.py` 模块通过 `from rag.config import rag_settings` 读取配置

## 运行时风险 (runtime_risk)
1. **相对路径陷阱**: `CHROMA_PERSIST_DIR` 和 `LOCAL_EMBEDDING_MODEL_PATH` 为相对路径，依赖 CWD。在 uvicorn / HPC 不同目录启动时可能解析错误。
2. **.env 覆盖**: extra="ignore" 意味着无效环境变量静默忽略，不会报错。
3. **计算属性缓存**: pydantic BaseSettings 的 @property 不缓存，每次访问都重新计算路径。

## 与检索/RAG 的关系 (relation_to_retrieval_or_rag)
所有检索函数的默认参数均来自 `rag_settings`。切换 corpus (official_docs / internal_engineering_docs) 依赖此处的 `CHROMA_PERSIST_DIR` / `CHROMA_INTERNAL_PERSIST_DIR` 配置对。

## 代码尺寸
- 行数: ~130
- 字段数: 25
- 计算属性: 8
