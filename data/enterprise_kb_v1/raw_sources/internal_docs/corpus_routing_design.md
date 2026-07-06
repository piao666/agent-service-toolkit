---
source_id: internal_corpus_routing_design
title: "Dual-Corpus Auto Routing 规则与实现方式"
domain: runtime_retrieval
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

# Corpus Auto Routing 规则与实现

## 一、route_mode 三种模式

`src/rag/corpus_router.py` 的 `detect_route_mode()` 函数根据 query 内容自动决定路由模式：

| route_mode | 触发条件 | 检索行为 |
|-----------|---------|---------|
| `official_only` | query 只含外部技术术语（Chroma, FastAPI, LangGraph, OpenAI, Pydantic 等） | 仅查 official_docs bge-m3 索引 |
| `internal_only` | query 含项目内部关键词（本项目, Phase, HPC, corpus_router, 代码摘要 等）且无外部技术术语 | 仅查 internal_engineering_docs bge-m3 索引 |
| `dual` | query **同时**包含外部技术信号词和内部项目信号词 | 同时查两个索引，各取 top3，合并结果 |

## 二、dual routing 判断条件

当 query 满足以下**两个条件同时成立**时，触发 dual routing：

**条件 A — 官方信号**: query 包含以下任一关键词：
- Chroma, FastAPI, LangGraph, OpenAI, Pydantic
- middleware, dependency injection, metadata filtering
- structured outputs, StateGraph, collection, embedding function
- request body, streaming, tool call, field validator

**条件 B — 内部信号**: query 包含以下任一关键词：
- structured retrieval, 检索设计, 本项目, corpus_router
- corpus routing, routing 规则, auto routing
- trace, 检索链路, rag pipeline, agent graph
- internal corpus, 内部语料, 代码摘要, 检索评测

**条件 A 和 B 同时满足 → route_mode = dual**

## 三、为什么 mixed query 要查双库

1. **信息互补**: 外部文档回答 "Chroma metadata filtering 怎么用"，内部文档回答 "本项目的 structured retrieval 如何在 Chroma 上实现"
2. **citation 完整性**: 回答需要同时引用外部 API 文档和内部设计文档
3. **避免路由错误**: 单一 corpus 路由在混合 query 上容易丢一半答案

## 四、实现代码位置

- `src/rag/corpus_router.py` — `route_corpus()` / `detect_corpus()` / `detect_route_mode()`
- `src/service/service.py` — `POST /api/enterprise-kb/retrieval/search` 和 `POST /api/enterprise-kb/rag/answer` 端点中调用
- `src/rag/traceable_rag_answer.py` — `generate_traceable_rag_answer()` 调用 corpus_router 决定检索目标

## 五、target_corpora 记录规则

- route_mode=official_only → target_corpora: ["official_docs"]
- route_mode=internal_only → target_corpora: ["internal_engineering_docs"]
- route_mode=dual → target_corpora: ["official_docs", "internal_engineering_docs"]

trace JSON 中必须记录实际的 `target_corpora` 数组，用于 downstream citation 溯源。
