# 文档状态策略

> 版本: v1-draft | 状态: policy | 最后更新: 2026-07-04

---

## 一、doc_status 定义

| status | 说明 | allowed_for_answer | 检索行为 |
|--------|------|--------------------|---------|
| `implemented` | 已实现并经过验证的当前行为 | ✅ 可设为 true | 正常检索 |
| `policy` | 工程规范/策略，优先级高于具体实现 | ✅ 可设为 true | 优先检索 |
| `draft` | 草稿中，内容可能不完整或不准确 | ❌ 不可为 true | 检索但标注 [DRAFT] |
| `planned` | 计划中，尚未开始或仅有规划 | ❌ 不可为 true | 不检索 |
| `deprecated` | 已废弃，仅保留作为历史记录 | ❌ 不可为 true | 不检索 |
| `legacy_derived` | 从旧工作区提炼，需再审核确认 | ❌ 不可为 true | 检索但标注 [LEGACY] |

---

## 二、answer_scope 定义

| scope | 说明 | 适用 doc_status |
|-------|------|----------------|
| `current_behavior` | 描述当前系统的实际行为（如 settings 默认值、pipeline 流程） | implemented |
| `technical_reference` | 外部技术文档的技术参考（如 FastAPI Path Parameters 用法） | implemented |
| `engineering_policy` | 团队工程规范（如 API Key 管理策略、模型选择策略） | policy |
| `troubleshooting` | 故障排查流程和已知问题 | implemented, draft |
| `future_plan` | 计划中的功能，不可作为当前行为回答 | planned |

---

## 三、状态转换规则

```
                  ┌──────────┐
                  │ planned  │  ← 新 source 默认状态
                  └────┬─────┘
                       │ 准入审核通过
                  ┌────▼─────┐
                  │  draft    │  ← 内容书写中
                  └────┬─────┘
                       │ 内容完成 + 人工审核
            ┌──────────┼──────────┐
       ┌────▼─────┐       ┌──────▼──────┐
       │  policy   │       │ implemented │
       └──────────┘       └──────┬──────┘
                                 │ 功能变更/废弃
                           ┌─────▼─────┐
                           │ deprecated │
                           └───────────┘
```

---

## 四、关键约束

1. **planned 不可作为答案** — `answer_scope=future_plan` 的文档在回答时必须注明"此功能尚未实现"
2. **draft 必须标注** — 检索结果中 draft 文档前标注 `[DRAFT]`
3. **legacy_derived 必须标注** — 检索结果中标注 `[LEGACY — 待审核]`
4. **deprecated 不检索** — 从检索索引中排除
5. **policy 优先于 implemented** — 当 policy 和 implemented 冲突时，policy 为准
