# Visual Sidecar Policy

> 版本: v1 | 时间: 2026-07-05 | 阶段: Phase 3F 决策输出
> 依赖: Phase 3E1-B1 (Screenshot 实测) + Phase 3E1-C (对比分析)

---

## 一、定位

Visual sidecar 是 enterprise_kb_v1 外部官方文档的可选辅助证据通道。它是 **证据 (evidence)**，不是 **检索源 (retrieval source)**。

| 属性 | 值 |
|------|-----|
| 默认状态 | `visual_capture.enabled: false` |
| 参与 retrieval | 否 |
| 参与 answer generation | 否 (`allowed_for_answer: false`) |
| 用途 | 人工审查、调试、chunk 位置确认、跨通道交叉验证 |

---

## 二、启用条件

### 自动启用 (建议，需人工确认)

| 条件 | 阈值 |
|------|------|
| 页面长度 | normalized.md > 20 KB **或** heading_count > 20 |
| 表格密度 | table_count ≥ 2 |
| 代码块复杂度 | code_block_count > 10 **且** 存在多语言 Tab 组件 |
| 布局复杂度 | 原始 HTML 含 `<tab>` / `<accordion>` / `<collapse>` 组件 |

### 不启用

| 条件 | 阈值 |
|------|------|
| 短页面 | normalized.md < 10 KB **且** heading_count < 10 |
| Text/DOM 完整覆盖 | heading/code/table 全部保留，无结构丢失警告 |

### 手动启用

任何 source 可通过设置 `visual_capture.enabled: true` 手动启用，不受自动条件限制。

---

## 三、字段规范

每条 external_official source 的 visual_capture 字段：

```yaml
visual_capture:
  enabled: false               # 默认关闭
  method: mcp_playwright_chromium
  status: not_rendered
  tile_policy: viewport_tiles_1080px_50pct_overlap
  allowed_for_answer: false    # 不进入回答生成
  quality_gate: not_evaluated
  visual_sidecar_value: not_evaluated   # none / low / medium / high
  capture_conditions:
    page_length_category: unknown       # short / medium / long
    has_tables: false
    has_complex_layout: false
    text_dom_sufficient: unknown
```

---

## 四、存储规范

```
data/enterprise_kb_v1/raw_sources/official_docs/{source_id}/
  └── v1/
      ├── text/                  # Text/DOM markdown (主通道)
      └── visual/                # Visual sidecar (可选)
          ├── full_page.png
          ├── tiles/
          │   ├── {source_id}_tile_000.png
          │   └── ...
          ├── snapshot.txt
          └── visual_metadata.json
```

Visual 资产与 text 资产绑定同一 fetch session（同一次 capture），版本号对齐。

---

## 五、成本约束

| 约束项 | 阈值 | 超出时处理 |
|--------|------|-----------|
| 单页 full_page.png | ≤ 5 MB | 超过则压缩至 JPEG quality=85 |
| 单页 tile 数量 | ≤ 30 | 超过则增大 tile 高度至 2160px |
| 总 visual 存储 | 不设硬上限 | 按 source 数量线性增长，定期审查 |
| 截图工具 | MCP Playwright | 不安装本地 Chromium |

---

## 六、生命周期

```
not_rendered → rendered → tiled → [embedded] → [indexed]
                                     ↑            ↑
                                Phase 3J+    Phase 4+ (未来)
```

当前 3 样本实验阶段停留在 `tiled`。正式采集后按 source 逐个推进。

---

## 七、与 PixelRAG 的边界

- PixelRAG 概念仅作为设计参考，当前**不声称已集成**。
- Visual embedding (VLM) 不在当前 scope。
- 如果未来需要 visual-aware retrieval，需先完成独立的 visual embedding 实验（Phase 4+）。

---

## 八、审查与例外

- 每批次正式采集完成后，审查 visual sidecar 的启用比例。
- 如果启用比例 > 50%，重新评估"默认关闭"策略。
- 单个 source 可通过 source_registry 手动覆盖 policy。
