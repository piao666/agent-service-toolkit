# Evidence Verifier V2 校准报告

> 日期: 2026-06-25
> 版本: v2_weighted_rule_based
> 不调用 LLM，不修改 retrieval / prompt / agent graph 执行流程。

## 1. 旧 V1 低分原因

V1 verifier 使用简单的 `matched_terms / important_terms` 比率评分，存在以下问题：

| 问题 | 影响 |
|---|---|
| 中文 2-4 字滑动窗口碎片过多 | answer 中大量无意义碎片（"根据检索"、"的步骤如下"、"声明字段"）涌入 important_terms |
| 代码变量误伤 | `app.post()`、`create_item`、`name`、`price`、`async`、`def` 被视为重要术语 |
| 所有 term 等权重 | 核心技术词（FastAPI、Pydantic）和示例变量（item、name）权重相同 |
| 仅用 content_preview | 截断的预览文本可能缺少关键术语 |
| 无来源质量判断 | 来源正确但表述不同时仍判 LOW |

典型误判：FastAPI 问题 sources 已经全是 `fastapi_docs`，title 是 `Request Body - FastAPI`，但大量代码变量未在 source 文本中匹配到，导致 `grounding_score < 0.30`。

## 2. V2 修复

### 2.1 文本归一化

`_normalize_evidence_text()` 使用 `unicodedata.normalize("NFKC")` 统一全角半角字符，lowercase，统一标点为空格。

### 2.2 三级术语分类

| 级别 | 权重 | 内容示例 |
|---|---|---|
| **critical** (关键) | 0.65 | FastAPI、Request Body、Pydantic、BaseModel、RAG、LoRA、enterprise_rag_pipeline |
| **support** (辅助) | 0.25 | JSON、Swagger UI、检索、生成、知识库、向量库 |
| **example** (示例) | 0.10 | 代码变量：item、name、price、str、float、async、def、app.post |

### 2.3 停用词与碎片过滤

排除无意义中文短语：
- "根据检索"、"检索到的"、"当前上下文"、"的步骤如下"、"定义一个继承自"、"并在其中"、"声明字段"、...
- 2 字普通中文碎片 + 代码变量级别 token

### 2.4 加权评分

```
critical_score = matched_critical / total_critical
support_score = matched_support / total_support
example_score = matched_example / total_example (example 为 0 时不惩罚)

final_score = 0.65 * critical_score + 0.25 * support_score + 0.10 * example_score
```

阈值:
- HIGH >= 0.70
- MEDIUM >= 0.35
- LOW < 0.35

### 2.5 Source quality gate

FastAPI gate:
- query/answer 包含 FastAPI / Request Body / Pydantic / BaseModel
- source_id_sequence 包含 fastapi_docs
- source relevance_score max >= 0.60
- 满足以上条件时至少 MEDIUM

RAG gate:
- sources 包含 enterprise_rag_pipeline
- critical_terms 命中 RAG / retrieval / generation 中至少 2 个
- 满足时至少 MEDIUM

System retrieval gate:
- sources 包含 enterprise_rag_pipeline 或 enterprise_agent_overview
- 满足时至少 MEDIUM

### 2.6 Corpus gap guardrail

如果 query/answer 包含 LoRA / PEFT / QLoRA / Low-Rank / 低秩等信号词，但 sources 不包含任何相关术语：
- grounding_status 强制 LOW
- diagnosis = "corpus_gap: LoRA/PEFT/QLoRA/低秩来源缺失"

### 2.7 状态与分数一致性校准

V2 区分 `raw_grounding_score` 与 UI 展示用的 `grounding_score`：

- `raw_grounding_score`：纯术语覆盖得分，用于调试和诊断；
- `grounding_score` / `calibrated_grounding_score`：结合 source quality gate 后的展示分；
- 当 `source_quality_gate=high` 时，展示分会提升到 HIGH 区间，避免出现 HIGH 状态低于 MEDIUM 分数的情况；
- 当 `source_quality_gate=medium` 时，展示分至少进入 MEDIUM 区间；若原始分已达到 HIGH 阈值，则状态同步升级为 HIGH；
- `corpus_gap_detected=True` 的场景优先级最高，LoRA 等语料缺口不会被 gate 升分。

### 2.8 更完整的 source text

`_source_full_text()` 优先取 `content` / `page_content` / `text` 字段（常用于传递完整文档内容），回退到 `content_preview`。

## 3. 验证结果

| 测试用例 | grounding_status | gate | score | source_unknown | 语料缺口 |
|---|---|---|---|---|---|
| FastAPI Request Body | **HIGH** | high | 0.537 | 0 | 否 |
| RAG 是什么 | **MEDIUM** | medium | 0.361 | 0 | 否 |
| 系统检索 | **MEDIUM** | medium | 0.379 | 0 | 否 |
| LoRA 作用 | **LOW** | low | 0.000 | 0 | **是** |

## 4. 保守边界

- LoRA 没有来源时**不升分**（corpus_gap 强制 LOW）
- RAG/系统检索没有命中正确来源时**不升分**
- 仍然是 **rule-based verifier**，不是 LLM judge
- 不修改 retrieval 主逻辑、Agent graph、prompt、Chroma
- 不修改 `src/service/service.py`、`src/rag/retriever.py`、`src/agents/enterprise_tools.py`

## 5. Streamlit 修复

- 勾选"显示高级调试信息"后新问题也立即显示高级调试（修复 checkbox state 丢失 bug，改为 `st.rerun()` 统一渲染流程）
- "已匹配术语"和"未支持术语"默认折叠（`expanded=False`）
- V2 三级术语分类展示（关键/辅助/示例）
- 中文文案更新：LOW 不再使用绝对表述
