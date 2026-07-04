---
source_id: internal_agent_graph_current
title: "当前 Agent Graph 节点与状态流转 (内部文档)"
domain: internal_engineering
source_type: internal_project
doc_type: internal_markdown
authority_level: internal_current_snapshot
doc_status: draft
allowed_for_answer: false
answer_scope: current_behavior
code_reference: >
  src/agents/enterprise_rag_agent.py (legacy),
  src/agents/enterprise_rag_graph.py (custom_graph),
  src/agents/enterprise_tools.py
last_verified: null
notes: >
  草案阶段，基于 2026-07-04 代码快照。描述两条 graph 链路的真实节点和状态定义。
---

# 当前 Agent Graph 节点与状态流转

## 一、两条 Graph 链路概览

系统通过 `ENTERPRISE_AGENT_GRAPH_MODE` 环境变量在 endpoint 层切换：

| 模式 | State 类型 | 入口模块 | 状态 |
|------|-----------|----------|------|
| `legacy` | `EnterpriseRagState` (MessagesState) | `enterprise_rag_agent.py` | 稳定 baseline |
| `custom_graph` | `EnterpriseRAGGraphState` (TypedDict) | `enterprise_rag_graph.py` | 可观测调试 |

## 二、Legacy Graph 详解

### 2.1 State 定义

```python
class EnterpriseRagState(MessagesState, total=False):
    query: str
    rewritten_query: str
    should_retrieve: bool
    guard_reason: str | None
    retrieval: dict[str, Any]
    draft_answer: str
    model_debug: dict[str, Any]
    memory_debug: dict[str, Any]
    verifier_debug: dict[str, Any]
```

### 2.2 节点序列（线性，无条件分支）

```
START → guard_input → route_need_retrieval → rewrite_query
       → retrieve → answer_synthesis → verify_evidence
       → fallback_or_finish → END
```

### 2.3 各节点职责

| 节点 | 职责 | 调用 LLM |
|------|------|----------|
| `guard_input` | 提取最新 HumanMessage 为 query，空查询设置 guard_reason="empty_query" | 否 |
| `route_need_retrieval` | 判断空查询/闲聊，设置 should_retrieve=False | 否 |
| `rewrite_query` | 规范化查询，可选 session memory 上下文拼接 | 否 |
| `retrieve` | 调用 `enterprise_knowledge_retriever_func()` 获取 sources+context | 否 |
| `answer_synthesis` | 构建 SystemMessage + HumanMessage(context)，调用 `get_model().ainvoke()` 生成答案 | **是** |
| `verify_evidence` | 若 `evidence_verifier_mode != "off"`，运行 rule-based evidence check | 否 |
| `fallback_or_finish` | 写入 session memory，组装最终 AIMessage（含 answer + sources + debug metadata） | 否 |

### 2.4 工具调用

Legacy graph 不使用 LangGraph tool-calling 机制。检索通过 `enterprise_knowledge_retriever_func()` 直接调用，不经过 LLM 的 tool_choice 决策。

## 三、Custom Graph 详解

### 3.1 State 定义

```python
class EnterpriseRAGGraphState(TypedDict, total=False):
    query: str
    session_id: str | None
    top_k: int
    return_sources: bool
    model: Any | None
    query_type: str | None
    planner_debug: dict[str, Any]
    sub_queries: list[str]
    contextual_query: str | None
    memory_debug: dict[str, Any]
    retrieved_sources: list[dict[str, Any]]
    retrieval_debug: dict[str, Any]
    ranked_sources: list[dict[str, Any]]
    answer: str
    model_debug: dict[str, Any]
    fallback: dict[str, Any]
    citations: list[dict[str, Any]]
    verifier_debug: dict[str, Any]
    judge_debug: dict[str, Any]
    graph_debug: dict[str, Any]
    final_response: dict[str, Any]
    structured_answer: dict[str, Any]
```

### 3.2 节点序列（含条件路由）

```
START → query_classifier ─┬─→ clarification_response ─┐
                          ├─→ safe_response ──────────┤
                          └─→ memory_rewriter          │
                                 ↓                     │
                              planner ─┬─→ clarification_response
                                       ├─→ safe_response
                                       ├─→ retriever ──┐
                                       └─→ multi_hop_retriever ──┐
                                                                  ↓
                                                               ranker
                                                                  ↓
                                                          answer_generator
                                                                  ↓
                                                          evidence_verifier
                                                                  ↓
                                                               judge
                                                                  ↓
                                                          final_response
                                                                  ↓
                                                                END
```

### 3.3 各节点职责

| 节点 | 职责 | 调用 LLM |
|------|------|----------|
| `query_classifier` | `infer_graph_query_type()` 推断查询类型（semantic_qa / code_api_config / citation_required / ambiguous / unsupported / smalltalk / memory_follow_up），设置 route | 否 |
| `memory_rewriter` | `contextualize_query_with_memory()` 对 follow-up 查询做上下文拼接 | 否 |
| `planner` | `plan_query()` 生成 debug 计划。debug_only 模式不改变路由 | 否 |
| `retriever` | 调用 `_default_retriever()` → `enterprise_knowledge_retriever_func()` | 否 |
| `multi_hop_retriever` | 多跳检索：对主查询+子查询分别检索，合并去重。默认关闭 | 否 |
| `ranker` | 按 `relevance_score` 降序排列 sources | 否 |
| `answer_generator` | 三种路径：(1) source_catalog structured answer 已启用 → 跳过 LLM；(2) `_real_answer_generator()` → `get_model().ainvoke()`；(3) fake model 时使用注入 answer | **是**（structured 路径除外） |
| `evidence_verifier` | `verify_answer_grounding()` rule-based check | 否 |
| `judge` | `judge_answer_rule_based()` rule-based diagnosis | 否 |
| `clarification_response` | 生成澄清询问（中文/英文自适应） | 否 |
| `safe_response` | 生成不支持/闲聊的安全回退 | 否 |
| `final_response` | 写入 memory，组装 final_response dict（含 answer / sources / citations / debug 全量字段） | 否 |

### 3.4 条件路由函数

| 函数 | 判断逻辑 |
|------|----------|
| `route_after_classifier` | ambiguous → clarification；unsupported/smalltalk → safe；其余 → memory_rewriter |
| `route_after_planner` | 类似 classifier 路由 + multi_hop 判断（需 `planner_mode=active` 且 `multi_hop_mode=rule_based`） |
| `route_after_verifier` | 始终 → judge |

### 3.5 Answer Generator 的三种路径

`answer_generator_node` 中的优先级：

1. **structured_answer 已启用**：使用 source_catalog 的预构建答案，不调用 LLM。graph_debug 中 `answer_generator = "source_catalog_structured_answer"`
2. **fake model**：`_real_answer_generator()` 中检测 `FakeModelName.FAKE`，`calls_real_llm = False`。使用 FakeListChatModel
3. **真实 LLM**：调用 `get_model().ainvoke()`，`calls_real_llm = True`。失败时回退到 `build_safe_fallback_answer()`

## 四、graph_debug 字段

两种 graph 模式都输出 debug 信息，custom_graph 更加详细：

```python
{
    "graph_mode": "custom_graph",        # 或 "legacy"
    "nodes_executed": ["query_classifier", "memory_rewriter", ...],
    "route": "normal" | "clarification" | "safe_response",
    "calls_llm": bool,                   # 是否调用 LLM
    "calls_real_llm": bool,              # 是否调用真实 LLM（非 fake）
    "writes_chroma": bool,               # 是否写入 Chroma（当前始终 False）
    "planner": {                         # planner 子 debug
        "planner_type": "simple",
        "requires_multi_hop": bool,
        "sub_queries": [...],
    },
    "multi_hop": {                       # multi_hop 子 debug
        "enabled": bool,
        "sub_queries": [...],
        "merged_source_count": int,
    },
    "judge": {                           # judge 子 debug
        "judge_mode": "rule_based_fallback",
        "verdict": "pass" | "fail" | "needs_review",
    },
}
```

## 五、answer_generator 的可注入替换

`build_enterprise_rag_graph()` 接受 `retriever` 和 `answer_generator` 两个可选的 `Callable` 参数。可在不修改源码的情况下注入自定义检索/回答逻辑：

```python
graph = build_enterprise_rag_graph(
    retriever=custom_retriever_func,
    answer_generator=custom_answer_func,
)
```
