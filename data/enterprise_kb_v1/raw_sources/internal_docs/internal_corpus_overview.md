---
source_id: internal_corpus_overview
title: "Internal Engineering Corpus 概览与源文件分类"
domain: project_positioning
source_type: internal_engineering_docs
doc_type: internal_markdown
authority_level: internal_current_snapshot
doc_status: active
allowed_for_answer: false
answer_scope: project_engineering_reference
enabled: false
corpus: internal_engineering_docs
version: v1
owner_phase: phase4fh
---

# Internal Engineering Corpus 概览

## 一、internal corpus 包含哪些源文件类别

Internal engineering corpus 包含 **5 大类别**，共 32+ 个源文件：

### A. 项目治理与定位文档 (8 个)
描述知识库的设计哲学、准入规则、评测标准和运行策略：
- `kb_positioning.md` — 知识库 v1 定位
- `kb_admission_policy.md` — 知识库准入策略
- `source_registry_spec.md` — Source Registry 规范
- `document_status_policy.md` — 文档状态策略
- `evaluation_standard.md` — 评测标准
- `ingestion_pipeline.md` — Ingestion Pipeline 设计
- `legacy_usage_policy.md` — 旧工作区使用策略
- `demo_scenarios.md` — Demo 场景设计

### B. 系统架构文档 (5 个)
描述当前系统实现状态的快照文档：
- `current_system_snapshot.md` — 系统模块与边界
- `rag_pipeline_current.md` — RAG 查询链路与检索架构
- `config_reference_current.md` — 关键配置参考
- `agent_graph_current.md` — Agent Graph 节点与状态流转
- `project_extension_guide_draft.md` — 项目扩展指南草案

### C. Phase 3/4 阶段文档 (8 个)
记录从语料采集到 embedding 决策的完整工程历史：
- Phase 3F-3J: 采集策略、capture plan、batch report、evidence audit、promotion
- Phase 4C: HPC Runbook
- Phase 4D: bge-m3 Default Embedding Decision
- Phase 4E: Runtime Retrieval Verification

### D. 代码摘要文档 (7 个)
关键源码文件的结构化摘要（非全文），每个包含 module_purpose、key_functions、config_dependency、runtime_risk：
- `config.py` — RAG 配置单例
- `official_docs_retriever.py` — official_docs 检索包装器
- `service.py` — FastAPI 入口与所有 API 端点
- `schema.py` — Pydantic 请求/响应模型
- `hpc_phase4c_run_embedding_ab.py` — 4 模型 embedding A/B 评测
- `runtime_retrieval_smoke.py` — Phase 4E smoke test
- `api_retrieval_smoke.py` — Phase 4E1 API smoke test

### E. 失败案例与工程经验 (4 个)
从开发过程中沉淀的可复用知识：
- `failure_patterns.md` — 10 个真实失败案例
- `hpc_evaluation_lessons.md` — HPC 评测经验
- `retrieval_debug_cases.md` — 检索排错手册
- `repo_hygiene_policy.md` — 仓库卫生策略

## 二、internal corpus 与 official_docs 的关系

- **official_docs**: 外部权威技术文档（Chroma/FastAPI/LangGraph/OpenAI/Pydantic）
- **internal_engineering_docs**: 本项目工程文档，描述项目自身的架构、决策和经验
- 两者通过 `corpus_router.py` (route_corpus/auto routing) 统一路由
- 默认 `enabled=false, allowed_for_answer=false`（仅 eval/demo，不进入生产回答链路）

## 三、检索方式

使用 `POST /api/enterprise-kb/retrieval/search`，设置 `corpus=internal_engineering_docs`。
或使用 `POST /api/enterprise-kb/rag/answer`，设置 `corpus=auto` 自动路由。
