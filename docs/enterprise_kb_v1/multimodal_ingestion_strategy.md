# 多模态采集策略

> 版本: v1-draft | 状态: draft | 最后更新: 2026-07-04

---

## 一、为什么纯文本解析不够

官方文档页面的信息密度不仅体现在纯文本中。以下结构信息可能被纯 Markdown 解析丢失：

| 丢失类型 | 示例 | 影响 |
|----------|------|------|
| **表格** | API 参数表、配置项矩阵、版本兼容表 | Markdown 表格解析后行列对齐丢失，LLM 可能错误理解列对应关系 |
| **流程图/架构图** | Mermaid 图、序列图、组件图 | 纯文本无法表达视觉拓扑 |
| **页面布局** | 侧边栏 vs 正文、代码注释 vs 代码块的关联位置 | 页面中"代码+右栏注释"的经典文档布局被扁平化 |
| **代码块相对位置** | 多语言 Tab 切换的代码示例（Python/JS/cURL 并列） | 三种语言版本被解析为连续文本，失去"同一功能的不同语言实现"的上下文 |
| **截图型信息** | 配置界面截图、CLI 输出截图、性能图表 | 截图中的 UI 元素名称、菜单路径全丢失 |

**结论**：只依赖 Text/DOM 通道可能在某些复杂官方文档页面上降低 RAG 回答精度。引入 sidecar visual 通道作为辅助，但不替代文本主通道。

---

## 二、双通道架构

### 2.1 Text/DOM 主通道（默认）

```
verified URL → Firecrawl/DOM capture → raw_markdown → clean
→ normalized_markdown → chunk → text embedding → Chroma
```

- **职责**：获取页面文字、代码块、链接等语义内容
- **输出**：Markdown chunks → text-based embedding → Chroma 向量索引
- **状态**：Phase 3D 启动后首次执行，当前 not_fetched

### 2.2 Visual Screenshot Sidecar 通道（可选，辅助）

```
verified URL → browser render → full-page screenshot
→ tile segmentation → visual embedding (pipeline TBD)
→ visual tile index (separate from text index)
```

- **职责**：保留页面视口结构，辅助 LLM 理解表格布局、流程图位置、代码/注释关联
- **输出**：Visual tile chunks → visual embedding → 独立的 visual tile 索引
- **状态**：Phase 3D 只做 3 页面小样本实验。当前 not_rendered，visual_capture.enabled=false

### 2.3 双通道互不替代

| 通道 | 默认状态 | 回答权重 | 索引位置 |
|------|----------|----------|----------|
| Text/DOM | 主通道，默认启用 | 主要回答依据 | Chroma text collection |
| Visual Screenshot | sidecar，默认禁用 | 辅助上下文字段，不作为答案主依据 | 独立 visual tile 索引 |

---

## 三、检索时的多模态融合（后续设计）

Phase 3D 实验将探索：
1. Text retrieval → top-k text chunks（标准 RAG 流程）
2. 对应的 source page → visual tiles（按 page 关联 visual sidecar）
3. LLM/VLM 在回答时可参考 visual context 补充表格/布局理解

**当前（Phase 3C0）不实现任何融合逻辑。**

---

## 四、适用范围

| 来源类型 | Text/DOM | Visual Sidecar | 理由 |
|----------|----------|---------------|------|
| external_official (19 verified) | ✅ | 可选实验 | 官方文档可能含复杂表格/图表 |
| Qwen needs_manual_review | ❌ 暂不抓取 | ❌ 暂不渲染 | URL 待人工确认 |
| internal_project | ✅ | ❌ 不需要 | 内部文档不含复杂截图 |

---

## 五、Phase 3D 小样本实验计划（不属本轮范围）

- 从 19 条 verified URL 选 3 页做 visual capture
- 评估 visual sidecar 是否在表格/代码块理解上改善 RAG 质量
- 如果无显著改善 → visual sidecar 保留为可选但默认关闭
- 如果有显著改善 → 扩展 visual capture 到更多 URL
