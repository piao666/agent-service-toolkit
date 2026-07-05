# Phase 3F 正式采集策略决策

> 版本: v1 | 时间: 2026-07-05 | 阶段: Phase 3F (策略决策，非正式采集)
> 依赖: Phase 3E1-A (Text/DOM) + Phase 3E1-B1 (Screenshot) + Phase 3E1-C (对比分析)

---

## 一、决策依据

### 1.1 Phase 3E1-A Text/DOM 结果

| 样本 | headings | code blocks | tables | links | MD 大小 | 质量 |
|------|:--:|:--:|:--:|:--:|------|:--:|
| S1 FastAPI | 5 | 3 | 0 | 6 | 4.8 KB | pass |
| S2 Chroma | 7 | 14 | 1 | 4 | 7 KB | pass |
| S3 LangGraph | 45 | 37 | 1 | 81 | 47 KB | pass |

**结论**: Text/DOM 对 3 类官方文档页面均成功捕获全部语义内容。代码块、表格、标题层级在 Markdown 中保留完整。S2 的 $ne/$lt exact token 缺失经确认为页面源内容中不存在，非抓取失败。

### 1.2 Phase 3E1-B1 Screenshot Sidecar 结果

| 样本 | 尺寸 | 大小 | tiles | 门禁 |
|------|------|------|:--:|:--:|
| S1 FastAPI | 1285×3458 | 419 KB | 6 | PASS |
| S2 Chroma | 1285×7911 | 685 KB | 14 | PASS |
| S3 LangGraph | 1285×32616 | 3,879 KB | 60 | PASS |

**结论**: MCP Playwright 全页截图可行。3/3 通过全部 6 项通用门禁（非空白、无遮挡、无错误、内容可见、分辨率≥1280、PNG 有效）。

### 1.3 Phase 3E1-C 对比分析结论

| 样本 | visual_sidecar_value | 理由 |
|------|:--:|------|
| S1 | **low** | Text/DOM 已完整覆盖短教程页面 |
| S2 | **medium** | Visual 确认表格和 Tab 结构，核心语义 Text/DOM 已覆盖 |
| S3 | **high** | 45 headings 在 Markdown 中扁平化，Visual 保留原始 DOM 层级 |

**推荐策略**: `keep_visual_sidecar_as_evidence`

---

## 二、正式采集策略决策

### 决策 1: 主线采集 — Text/DOM 为主

**决策**: ✅ **正式采集主线继续以 Text/DOM 为主通道。**

理由:
- 3/3 样本 Text/DOM 质量 pass，语义内容完整
- 代码块、表格、标题层级均成功保留
- Text/DOM 是轻量、可离线、零外部依赖的通道

### 决策 2: Visual Sidecar 定位

**决策**: ✅ **Visual sidecar 保留为 evidence（辅助证据），不进入正式 retrieval 通道。**

理由:
- S3 (high) 证明了长文档页面的 visual 价值，但这是结构补足而非语义替代
- Visual assets 默认不用于回答生成（`allowed_for_answer: false`）
- Visual sidecar 作为独立的 evidence 文件与 text chunk 关联，不参与 embedding 检索

### 决策 3: Visual Embedding / PixelRAG-style Index

**决策**: ❌ **暂不做 visual embedding / PixelRAG-style index。**

理由:
- 3 样本实验规模不足以支撑引入 VLM 依赖的决策
- Visual sidecar 当前定位为 evidence（人工审查/调试用），不是 retrieval source
- PixelRAG 概念仅作为设计参考，当前不声称已集成

### 决策 4: 19 条 Verified Source 正式采集方案

**决策**: ✅ **允许进入下一阶段：设计 19 条 verified source 的 Text/DOM 正式采集方案。**

前置条件:
- 基于 Phase 3A allowlist 中已标记 `text_capture.enabled: true` 的 19 条 source
- 每条 source 采用 Phase 3E1-A 验证过的 requests + bs4 + html2text 方案
- 先设计方案和 dry-run plan，不直接执行批量采集

### 决策 5: Screenshot Sidecar 适用页面类型

**需要 screenshot sidecar 的页面类型**:

| 类型 | 判定指标 | 示例 |
|------|----------|------|
| 长页面 | normalized.md > 20KB 或 heading > 20 | S3 LangGraph (47KB, 45 headings) |
| 表格密集页面 | table_count ≥ 2 | — |
| 代码块与说明强相关页面 | code_block_count > 10 且存在多语言 Tab | S2 Chroma (14 code blocks, JS Tab) |
| 动态 Tab / 复杂布局页面 | 原始 HTML 含 tab/accordion/collapse 组件 | S2 Chroma (Python/TS/Rust tabs) |

**不需要 screenshot sidecar 的页面类型**:

| 类型 | 判定指标 | 示例 |
|------|----------|------|
| 短页面 | normalized.md < 10KB 且 heading < 10 | S1 FastAPI (4.8KB, 5 headings) |
| Text/DOM 已完整覆盖 | heading/code/table 全部保留且无结构丢失 | S1 FastAPI |

### 决策 6: 成本约束

| 约束项 | 阈值 |
|--------|------|
| 单页截图体积上限 | 5 MB |
| 单页 tile 数量上限 | 30 |
| Visual sidecar 默认状态 | `enabled: false`（按 source 类型按需启用） |
| 浏览器依赖 | MCP Playwright（无本地安装） |

---

## 三、不执行清单

本阶段 (Phase 3F) 是策略决策，以下操作均未执行：

| 操作 | 状态 |
|------|:--:|
| 抓取新 URL | ❌ 未执行 |
| Crawl 整站 | ❌ 未执行 |
| 重新截图 | ❌ 未执行 |
| 创建 Chroma / FAISS / embedding / index | ❌ 未执行 |
| 修改 source_registry.yaml | ❌ 未修改 |
| 修改 official_docs_allowlist.yaml | ❌ 未修改 |
| 启用任何 source | ❌ 未启用 |
| 迁移 experiment 产物到 raw_sources | ❌ 未迁移 |
| 进入 chunking / indexing | ❌ 未进入 |
| Git commit / push | ❌ 未执行 |

---

## 四、下一阶段建议

| 阶段 | 内容 | 前置条件 |
|------|------|----------|
| Phase 3G | 19 条 verified source Text/DOM 正式采集 dry-run plan | Phase 3F 审批通过 |
| Phase 3H | 正式 Text/DOM 采集执行 | Phase 3G dry-run 通过 |
| Phase 3I | Chunking + 入库 Chroma | Phase 3H 采集完成 |
| Phase 3J | Visual sidecar 扩展（按需，仅符合条件的页面） | Phase 3I 完成后评估 |
