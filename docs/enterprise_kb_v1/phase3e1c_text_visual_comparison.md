# Phase 3E1-C Text/DOM vs Visual Screenshot 对比分析计划

> 版本: v1 | 时间: 2026-07-05 | 阶段: Phase 3E1-C
> 输入: Phase 3E1-A (Text/DOM) + Phase 3E1-B1 (Visual Screenshot)

---

## 一、分析目标

基于已有的 3E1-A Text/DOM 产物和 3E1-B1 Screenshot sidecar 产物，逐样本比较两条通道的证据质量，判断 visual sidecar 是否值得保留。

---

## 二、分析维度

| 维度 | Text/DOM 检查 | Visual 检查 |
|------|--------------|------------|
| 标题层级 | heading_count_by_level 是否完整 | headings_visible 是否保留原始嵌套 |
| 代码块 | code_block_count + 上下文完整性 | code_blocks_visible + 布局中的位置 |
| 表格 | table_count + markdown 可解析性 | table_visible + 视觉行列对齐 |
| 链接 | link_count | 无直接对应（链接是文本属性） |
| Operator 覆盖 (S2) | exact token 检查 | snapshot 中是否可见 |
| 长页面结构 (S3) | 45 headings 线性排列 | long_page_structure_visible |
| 页面布局 | 扁平化 Markdown | 原始 DOM 渲染层级 |

---

## 三、visual_sidecar_value 判定标准

| 值 | 条件 |
|----|------|
| `high` | Visual 提供 Text/DOM 无法捕获的关键信息（布局层级、代码上下文、导航结构） |
| `medium` | Visual 提供互补价值，但 Text/DOM 已覆盖核心语义 |
| `low` | Text/DOM 已充分覆盖，Visual 不增加额外语义 |
| `none` | Visual 通道失败或无产物 |

---

## 四、策略选项

| 策略 | 触发条件 |
|------|----------|
| `text_only_sufficient` | 3/3 样本 visual_sidecar_value ∈ {none, low} |
| `keep_visual_sidecar_as_evidence` | ≥2/3 样本 visual_sidecar_value ∈ {medium, high} |
| `consider_visual_index_later` | ≥2/3 样本 visual_sidecar_value = high 且成本可接受 |

---

## 五、硬约束

- 不抓新 URL
- 不重新截图
- 不创建 Chroma / FAISS / embedding / index
- 不修改 registry / allowlist
- 不提交、不 push
