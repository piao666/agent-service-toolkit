# 评测标准

> 版本: v1-draft | 状态: policy | 最后更新: 2026-07-04

---

## 一、评测分层

| 层级 | 用例数 | 用途 | 阶段 |
|------|--------|------|------|
| **core_eval_30** | 30 | v1 首版验收 | Phase 1 (当前) |
| **regression_eval_50** | 50 | 回归 + 边界 | Phase 2 |
| **legacy_stress_eval** | — | 旧评测重放（非验收标准） | Phase 3 |

### 核心原则

- **core_eval_30 当前全部为 draft 状态** — 30 条用例均为蓝图草案，尚未经过人工逐条验证。Phase 1 完成后需逐条审核并改为 `verified` 状态方可作为正式验收集。
- **core_eval_30 为首版唯一验收标准** — 全部 verified 且 PASS ≥ 80% 即可发布 v1
- **旧大规模评测不能作为 v1 验收** — 旧评测针对旧语料/旧索引，不可直接迁移
- **每轮迭代最多新增 20 条 eval case** — 增量扩充，避免一次性膨胀
- **source_id 后续可拆分** — Phase 1 的 `expected_source_ids` 使用当前 source_registry 中已有的 coarse-grained source_id。后续若单个 source 覆盖范围过宽，可拆分为更细粒度 source（如 `chroma_official_collection` → `chroma_collection_crud` + `chroma_embedding_config`），对应 eval case 的 `expected_source_ids` 同步更新。Phase 1 只保留 draft 示例，不承诺最终 source 粒度。

---

## 二、Eval Case 格式

每条 eval case 必须包含：

```json
{
  "case_id": "core_001",
  "query": "FastAPI 如何处理请求体中的 Pydantic 模型验证？",
  "expected_domain": "api_backend",
  "expected_source_ids": ["fastapi_official_routing"],
  "required_answer_points": [
    "FastAPI 自动将请求体解析为 Pydantic 模型",
    "验证失败返回 422 Unprocessable Entity",
    "支持嵌套模型"
  ],
  "forbidden_phrases": [
    "不确定",
    "知识库中没有",
    "无法回答"
  ],
  "answer_type": "technical_reference",
  "status": "draft"
}
```

### 字段约束

| 字段 | 说明 | 约束 |
|------|------|------|
| `case_id` | 全局唯一标识 | 格式 `core_NNN` |
| `query` | 自然语言查询 | 中文首选，技术术语可用英文 |
| `expected_domain` | 预期命中的知识领域 | 须在 source_registry 的 domain 枚举内 |
| `expected_source_ids` | 预期命中的 source | 须在 source_registry 中存在 |
| `required_answer_points` | 答案必须覆盖的要点 | 至少 2 条，至多 6 条 |
| `forbidden_phrases` | 禁止出现的短语 | 至少 1 条 |
| `answer_type` | 答案类型 | 须在 answer_scope 枚举内 |
| `status` | 当前状态 | draft (蓝图) / verified (已人工验证) |

---

## 三、评分规则

### 单条评分

| 分数 | 条件 |
|------|------|
| ✅ **PASS** | 全部 required_answer_points 命中 + 无 forbidden_phrases + expected_domain 匹配 |
| ⚠️ **PARTIAL** | ≥50% required_answer_points 命中 + 无 forbidden_phrases |
| ❌ **FAIL** | <50% required_answer_points 或出现 forbidden_phrase |

### 整体通过标准

- core_eval_30: **PASS ≥ 80%** (24/30) 且 FAIL < 10% (≤3/30)
- regression_eval_50: **PASS ≥ 70%** (35/50) 且 FAIL < 15%

---

## 四、Eval Case 准入标准

- 必须能通过 source_registry 中已 enabled 的 source 回答
- 不能依赖尚未入库的 source
- 每 10 条 case 中至少包含 1 条**负面测试**（预期回答为"当前知识库无法确认"或类似）

---

## 五、评测流程

```
1. 人工撰写 eval case (status=draft)
2. 人工验证答案预期 (status=verified)
3. 运行自动化评测
4. 输出 results.jsonl + summary.json
5. bad case 分析 → 改进语料或修正 case
```
