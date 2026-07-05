# Phase 3E1-B Screenshot Sidecar 预检与执行计划

> 版本: v1 | 时间: 2026-07-05 | 阶段: Phase 3E1-B0
> 状态: ready_for_B1

---

## 一、环境预检结果

| 组件 | 版本/路径 | 状态 |
|------|-----------|------|
| Python | 3.12.10 | ✅ |
| Pillow | 12.3.0 | ✅ 已安装 |
| Playwright (本地) | — | ❌ 未安装 |
| MCP Playwright | plugin_playwright_playwright | ✅ **可用** |
| Chrome | C:/Program Files/Google/Chrome/Application/chrome.exe | ✅ |
| Edge | C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe | ✅ |
| experiments/ gitignore | data/enterprise_kb_v1/experiments/ | ✅ 已忽略 |
| visual/ 目录 | 不存在 | — B1 会创建 |
| 现有截图 | 0 个 | — 无冲突 |
| Registry 修改 | (clean) | ✅ 未修改 |
| Allowlist 修改 | — | ✅ 未修改 |

### 关键发现：MCP Playwright 绕过本地安装约束

Phase 3E0 预检时 Playwright 标记为 ❌ 未安装，且 Chromium 下载 ~300MB 被列为需人工确认的硬约束。**本轮发现 MCP Playwright 插件在当前会话中可用**（`mcp__plugin_playwright_playwright__*` 工具族），包括 `browser_navigate`、`browser_take_screenshot`、`browser_snapshot` 等。可直接通过 MCP 协议驱动远端浏览器完成截图，无需本地 `pip install playwright`。

---

## 二、B1 截图策略

### 2.1 主方案：MCP Playwright full_page screenshot

```
MCP browser_navigate(URL) → 等待页面加载 → browser_take_screenshot(fullPage=true) → full_page.png
```

对 3 个样本依次执行：
1. `browser_navigate` 到目标 URL
2. `browser_wait_for` 等待关键文本出现（确认 JS 渲染完成）
3. `browser_take_screenshot(fullPage=true, type="png")` → 保存为 `full_page.png`
4. Pillow 解析 PNG 尺寸，计算 tile 数量

### 2.2 Tile 策略：full_page + optional tiles

| 条件 | 策略 |
|------|------|
| 页面高度 ≤ 2160px (2×1080) | 仅 full_page，不切 tile |
| 页面高度 > 2160px | full_page + viewport_tiles（每 1080px 切一个 tile，50% 重叠） |

预计：
- **S1** (fastapi middleware): 短页面，~1500px → 仅 full_page
- **S2** (chroma metadata filtering): 中等，~2500px → full_page + ~3 tiles
- **S3** (langgraph graph API): 长页面，~8000px+ → full_page + ~10 tiles

### 2.3 降级方案

| 条件 | 降级 |
|------|------|
| MCP Playwright 不可用 | 尝试本机 Chrome CDP (`--remote-debugging-port`) |
| Chrome CDP 不可用 | 使用 Edge CDP |
| 全部浏览器不可用 | Visual capture 降级为 `not_rendered`，B1 只输出 Text/DOM 对比报告 |
| full_page 失败 | 回退为 viewport 单页截图 |

---

## 三、visual_metadata.json Schema

每条样本独立一个 `visual_metadata.json`，放在 `experiments/phase3d_multimodal/visual/{S}/` 下。

```json
{
  "sample_id": "S1",
  "source_id": "fastapi_official_middleware",
  "origin_url": "https://fastapi.tiangolo.com/tutorial/middleware/",
  "capture_channel": "visual_screenshot",
  "capture_time": "2026-07-05T15:30:00+08:00",
  "capture_method": "mcp_playwright_chromium",
  "capture_status": "rendered",
  "artifact_path": "experiments/phase3d_multimodal/visual/S1/",
  "evidence_type": "page_screenshot",
  "full_page": {
    "file": "full_page.png",
    "dimensions": {"width": 1280, "height": 1520},
    "size_bytes": 245000
  },
  "tiles": {
    "count": 0,
    "policy": "viewport_tiles_1080px_50pct_overlap",
    "viewport_height": 1080,
    "files": []
  },
  "quality_gate": {
    "overall": "PASS",
    "checks": {
      "not_blank": true,
      "no_obscured": true,
      "no_cookie_banner": true,
      "content_visible": true,
      "s2_table_visible": null,
      "s3_structure_visible": null
    },
    "notes": []
  }
}
```

### 字段说明

| 字段 | 类型 | 说明 |
|------|------|------|
| `capture_method` | string | `mcp_playwright_chromium` — 通过 Claude Code MCP Playwright 插件驱动 |
| `capture_status` | enum | `not_rendered` / `rendered` / `tiled` / `failed` |
| `full_page.dimensions` | object | Pillow 读取的实际像素尺寸 |
| `full_page.size_bytes` | int | PNG 文件字节数 |
| `tiles.policy` | string | 切分策略描述 |
| `quality_gate.overall` | enum | `PASS` / `PASS_WITH_LIMITATIONS` / `FAIL` |
| `quality_gate.checks` | object | 逐项门禁结果（sample-specific 检查对不适用样本为 null） |

---

## 四、截图质量门禁

### 4.1 通用门禁（全部 3 样本）

| 编号 | 门禁 | 检测方法 | 阈值 |
|------|------|----------|------|
| G1 | 非空白图 | Pillow 像素方差分析，白色像素占比 < 95% | PASS if white_ratio < 0.95 |
| G2 | 无遮挡 | 截图顶部 150px 区域是否存在大面积纯色块（cookie banner） | PASS if top_band_entropy > threshold |
| G3 | 无加载失败 | 页面标题不含 "404"/"Error"/"Page not found" | PASS if title OK |
| G4 | 内容可见 | body text 长度 > 100 字符（通过 browser_snapshot 验证） | PASS if snapshot text > 100 |
| G5 | 分辨率达标 | full_page.width ≥ 1280px | PASS if width ≥ 1280 |
| G6 | 文件有效 | PNG header 完整，Pillow 可打开 | PASS if Image.open() 成功 |

### 4.2 S2 专项门禁

| 编号 | 门禁 | 检测方法 |
|------|------|----------|
| S2-G1 | 表格可见 | browser_snapshot 中检测到 table 元素 |
| S2-G2 | Operator 文本可见 | snapshot 中包含 "$eq" / "$gte" / "$in" 等可见文本 |

### 4.3 S3 专项门禁

| 编号 | 门禁 | 检测方法 |
|------|------|----------|
| S3-G1 | 长页面结构 | full_page.height > 3000px（确认非截断） |
| S3-G2 | 标题层级可见 | snapshot 中 H1/H2/H3 数量 ≥ Text/DOM 的 80% |
| S3-G3 | 代码块区域 | tile 覆盖到代码密集区域（含 "StateGraph" / "add_node" 等关键字） |

### 4.4 综合判定

| 判定 | 条件 |
|------|------|
| ✅ PASS | 全部通用门禁通过 + 全部专项门禁通过 |
| ⚠️ PASS_WITH_LIMITATIONS | 通用门禁全通过，专项门禁 1 项失败（非阻塞性） |
| ❌ FAIL | 任一通用门禁失败 |

---

## 五、样本执行计划

### S1 — fastapi_official_middleware

- URL: `https://fastapi.tiangolo.com/tutorial/middleware/`
- Text/DOM 已有: raw.html (105KB), normalized.md (4KB), 5 headings, 3 code blocks, 0 tables
- 截图策略: full_page only (预计短页面)
- 专项门禁: 无（S1 无 table，结构简单）
- 关键观察点: middleware 代码块在截图中是否完整可见

### S2 — chroma_official_metadata_filter

- URL: `https://docs.trychroma.com/docs/querying-collections/metadata-filtering`
- Text/DOM 已有: raw.html (1430KB), normalized.md (6KB), 7 headings, 14 code blocks, **1 表格**
- 截图策略: full_page + tiles
- 专项门禁: 表格可见、operator 文本可见
- 关键观察点: JS Tab 代码语言变体（Python/JS）在截图中是否全部展开或仅默认 Tab

### S3 — langgraph_official_stategraph

- URL: `https://docs.langchain.com/oss/python/langgraph/graph-api`
- Text/DOM 已有: raw.html (2438KB), normalized.md (47KB), 45 headings, 37 code blocks, **1 表格**
- 截图策略: full_page + tiles（长页面，预计 8000px+）
- 专项门禁: 长页面结构、标题层级、代码块区域
- 关键观察点: 45 个标题的视觉层级在截图中是否比 Markdown 扁平化更易读

---

## 六、不做的清单（硬约束）

| 操作 | 是否执行 |
|------|----------|
| 抓取新 URL | ❌ 不执行 |
| crawl 整站 | ❌ 不执行 |
| 修改 source_registry.yaml | ❌ 不修改 |
| 修改 official_docs_allowlist.yaml | ❌ 不修改 |
| 创建 Chroma / FAISS / embedding / index | ❌ 不创建 |
| 安装 PixelRAG | ❌ 不安装 |
| 安装新 Python 依赖 | ❌ 不安装（Pillow 已安装） |
| git commit / push | ❌ 不执行 |
| git add | ❌ 不执行 |

---

## 七、B1 执行步骤

```
1. MCP browser_navigate(S1_URL) → browser_wait_for → browser_take_screenshot → full_page.png
2. Pillow 解析 S1 full_page.png → 写入 visual_metadata.json
3. MCP browser_navigate(S2_URL) → browser_wait_for → browser_take_screenshot → full_page.png
4. Pillow 解析 S2 full_page.png → 切 tile → 写入 visual_metadata.json
5. MCP browser_navigate(S3_URL) → browser_wait_for → browser_take_screenshot → full_page.png
6. Pillow 解析 S3 full_page.png → 切 tile → 写入 visual_metadata.json
7. 质量门禁逐项检查 → quality_gate 结果写入 visual_metadata.json
8. 生成 B1 报告 → ZIP 打包
```

---

## 八、B0 结论

| 判定项 | 结果 |
|--------|------|
| 截图能力 | ✅ MCP Playwright 可用 |
| 图像处理 | ✅ Pillow 12.3.0 |
| 浏览器后备 | ✅ Chrome + Edge 双后备 |
| 目录隔离 | ✅ experiments/ 已 gitignore |
| Registry 安全 | ✅ 未修改 |
| **是否满足进入 Phase 3E1-B1** | ✅ **满足，无阻塞项** |
