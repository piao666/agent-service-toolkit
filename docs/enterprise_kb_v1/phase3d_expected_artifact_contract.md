# Phase 3D 预期产物结构合约

> 版本: v1-draft | 状态: draft | 最后更新: 2026-07-04

---

## 一、重要声明

⚠️ **本文档描述的是 Phase 3E 执行采集后的预期目录结构。Phase 3D 当前不创建任何实验产物目录或文件。**

所有路径以 `data/enterprise_kb_v1/experiments/phase3d_multimodal/` 为根。

---

## 二、预期目录结构（Phase 3E 创建）

```
data/enterprise_kb_v1/experiments/phase3d_multimodal/
│
├── sample_manifest.yaml                        # 样本清单（来自 phase3d_sample_manifest.yaml）
│
├── text_dom/                                    # Text/DOM 通道
│   ├── S1/                                      # fastapi_official_middleware
│   │   ├── raw.html                              # 页面原始 HTML
│   │   ├── normalized.md                         # 清洗后 Markdown
│   │   └── text_metadata.json                    # 来源元数据
│   ├── S2/                                      # chroma_official_metadata_filter
│   │   ├── raw.html
│   │   ├── normalized.md
│   │   └── text_metadata.json
│   └── S3/                                      # langgraph_official_stategraph
│       ├── raw.html
│       ├── normalized.md
│       └── text_metadata.json
│
├── visual/                                      # Visual Screenshot 通道
│   ├── S1/
│   │   ├── full_page.png                        # 全页截图
│   │   ├── tiles/                               # 视口分块
│   │   │   ├── S1_tile_001.png
│   │   │   ├── S1_tile_002.png
│   │   │   └── ...
│   │   └── visual_metadata.json                 # tile→source 映射
│   ├── S2/
│   │   ├── full_page.png
│   │   ├── tiles/
│   │   └── visual_metadata.json
│   └── S3/
│       ├── full_page.png
│       ├── tiles/
│       └── visual_metadata.json
│
├── comparison/                                  # 双通道对比
│   ├── S1_channel_comparison.md
│   ├── S2_channel_comparison.md
│   └── S3_channel_comparison.md
│
└── reports/                                     # 实验报告
    └── phase3d_experiment_report.md
```

---

## 三、文件合约

### 3.1 raw.html

- 来源：Firecrawl scrape 或等价 DOM capture
- 保留原始 HTML 结构，不做清洗
- 不可作为答案依据

### 3.2 normalized.md

- 来源：raw.html 经清洗后生成
- 移除侧边栏、导航、页脚
- 保留代码块、表格、标题层级
- 可以进入后续 chunking 评估

### 3.3 text_metadata.json

```json
{
  "sample_id": "S1",
  "source_id": "fastapi_official_middleware",
  "origin_url": "https://fastapi.tiangolo.com/tutorial/middleware/",
  "capture_channel": "text_dom",
  "capture_time": "PHASE_3E_TBD",
  "capture_status": "not_captured",
  "artifact_path": "experiments/phase3d_multimodal/text_dom/S1/",
  "evidence_type": "web_page_text",
  "normalized_char_count": 0,
  "heading_count": {},
  "code_block_count": 0,
  "table_count": 0
}
```

### 3.4 full_page.png

- 来源：浏览器渲染 → 全页截图（headless Chrome/Puppeteer 或等价）
- 分辨率：viewport 宽度 ≥1280px
- 格式：PNG
- 不可作为答案依据

### 3.5 tiles/

- 来源：full_page.png 按视口高度（~1080px）切分
- 命名：{sample_id}_tile_{NNN}.png
- 不可作为答案依据

### 3.6 visual_metadata.json

```json
{
  "sample_id": "S1",
  "source_id": "fastapi_official_middleware",
  "origin_url": "https://fastapi.tiangolo.com/tutorial/middleware/",
  "capture_channel": "visual_screenshot",
  "capture_time": "PHASE_3E_TBD",
  "capture_status": "not_rendered",
  "artifact_path": "experiments/phase3d_multimodal/visual/S1/",
  "evidence_type": "page_screenshot",
  "tile_count": 0,
  "full_page_dimensions": {},
  "tile_policy": "viewport_tiles"
}
```

### 3.7 channel_comparison.md

- 对每个样本单独输出双通道对比
- 包含：text 结构缺失清单、visual 补充价值评估、是否建议启用 visual sidecar

---

## 四、关键约束

1. **实验产物不进入正式回答链路** — 不加入 Chroma 正式索引
2. **实验产物不入 source_registry** — 不更改任何 source 的 fetch_status 或 visual_capture.status
3. **Phase 3F 人工审核通过后**，才允许将 PASS 样本的实验产物迁移到正式 raw_sources 目录
4. **visual assets 默认不用于回答** — visual_capture.allowed_for_answer 保持 false
