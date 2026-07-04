# Visual RAG Sidecar 设计

> 版本: v1-draft | 状态: draft | 最后更新: 2026-07-04

---

## 一、目标

为 enterprise_kb_v1 的外部官方文档建立可选的视觉辅助索引通道。参考 PixelRAG 思路（将页面渲染为截图/tile 保留视觉结构），但不将 PixelRAG 写为已集成能力。

### 核心原则

- Visual sidecar 是**辅助通道**，不替代 Text/DOM 主通道
- 视觉资产**默认不用于回答**
- 仅在实验验证有效后才扩展到生产使用
- 所有 visual_capture 默认 disabled

---

## 二、参考思路：PixelRAG 核心概念

PixelRAG 的核心思想：

1. **页面渲染**：将文档页面渲染为完整截图（full-page screenshot）
2. **Tile 分割**：将截图按视口大小或语义边界切分为 tiles
3. **Visual embedding**：使用 VLM（Vision-Language Model）对每个 tile 生成 visual embedding + caption
4. **混合检索**：text embedding + visual embedding 联合检索
5. **VLM 增强生成**：在答案合成时，如果检索到的 chunk 有关联 visual tile，VLM 可参考 tile 图像补充理解

**当前不将 PixelRAG 写为已实现能力。Phase 3D 实验前，这些概念仅作为设计参考。**

---

## 三、Visual Sidecar 字段定义

每条 external_official source 新增以下字段：

```yaml
text_capture:
  enabled: true
  method: firecrawl_or_dom
  status: not_fetched

visual_capture:
  enabled: false
  method: pixelshot_candidate
  status: not_rendered
  tile_policy: viewport_tiles
  allowed_for_answer: false

retrieval_channels:
  - text
  - visual_optional
```

### 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `text_capture.enabled` | bool | Text/DOM 抓取是否启用（默认 true） |
| `text_capture.method` | string | 抓取方式：`firecrawl_or_dom` |
| `text_capture.status` | string | `not_fetched` / `fetched` / `normalized` / `chunked` / `indexed` |
| `visual_capture.enabled` | bool | Visual capture 是否启用（默认 false） |
| `visual_capture.method` | string | 渲染方式：`pixelshot_candidate` |
| `visual_capture.status` | string | `not_rendered` / `rendered` / `tiled` / `embedded` / `indexed` |
| `visual_capture.tile_policy` | string | 切分策略：`viewport_tiles` （按视口高度切分） |
| `visual_capture.allowed_for_answer` | bool | 视觉资产是否可作为答案依据（默认 false） |
| `retrieval_channels` | list | 可用检索通道：`text` + `visual_optional` |

---

## 四、存储与索引设计（草案，未实现）

### 4.1 存储规划

```
data/enterprise_kb_v1/raw_sources/official_docs/{source_id}/
  ├── v1/
  │   ├── text/           # Text/DOM markdown
  │   │   ├── page_01.md
  │   │   └── page_02.md
  │   ├── screenshots/    # Full-page PNG
  │   │   ├── page_01_full.png
  │   │   └── page_02_full.png
  │   └── tiles/          # Segmented tiles
  │       ├── page_01_tile_001.png
  │       └── ...
  ├── normalized/
  └── chunks/
```

### 4.2 索引规划

- Text chunks → Chroma text collection（现有）
- Visual tiles → 独立 visual Chroma collection（新），embedding 由 VLM/visual encoder 生成
- tile ↔ source_id ↔ text_chunk 的映射表

---

## 五、风险与限制

| 风险 | 说明 | 缓解措施 |
|------|------|----------|
| **存储膨胀** | 每页全屏截图 2-5MB，tile 后 10-20 个 tile/page | Phase 3D 仅 3 页面实验；后续按需扩展 |
| **VLM 依赖** | Visual embedding 和 visual-aware 答案合成依赖 VLM | 不替代文本通道；visual channel 默认关闭 |
| **索引复杂度** | 需要维护 text 和 visual 两套索引及跨索引映射 | 仅实验阶段探索；如复杂度过高则保持 text-only |
| **截图一致性** | 不同时间截取的页面可能有内容变化 | 截图与 markdown 绑定同一 fetch session |
| **冷启动延迟** | 首次截图+VLM embedding 耗时远大于纯文本 | 仅 on-demand 触发，不加入实时查询路径 |
| **ROI 不明** | visual channel 的检索质量提升尚未验证 | Phase 3D 小样本实验后再决策是否扩展 |

---

## 六、Phase 3D 实验计划（预定义）

| 实验参数 | 值 |
|----------|-----|
| 实验页面数 | 3 |
| 来源 | 从 19 条 verified external_official 中选取 |
| 评估维度 | 表格理解准确率、代码块引用的 API 签名正确率、布局依赖型问题的回答质量 |
| 判定标准 | 如果 visual sidecar 在 2/3 页面上改善回答则进入 Phase 3E 扩展；否则保持 visual_capture.enabled=false |

---

## 七、与 PixelRAG 的差异

本文档参考了 PixelRAG 的思路但存在以下关键差异：

1. **PixelRAG 是 end-to-end implementation**：本文档只定义 sidecar 接口和字段，不实现
2. **不声称已集成**：代码库中无 PixelRAG 相关依赖或模块
3. **双通道隔离**：visual channel 默认不参与检索，需要显式启用
4. **评估先行**：未经验证不启用
