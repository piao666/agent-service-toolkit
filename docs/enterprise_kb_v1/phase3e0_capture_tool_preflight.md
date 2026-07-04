# Phase 3E0 采集工具预检

> 版本: v1-draft | 时间: 2026-07-04 | 状态: preflight_check

---

## 一、预检结果

| 工具/库 | 用途 | 状态 |
|----------|------|------|
| Python 3.12 | 运行时 | ✅ 可用 (3.12.10) |
| requests | HTTP GET 网页 | ❌ 未安装 |
| beautifulsoup4 (bs4) | HTML 解析 | ❌ 未安装 |
| playwright | 浏览器渲染 + 截图 | ❌ 未安装 |
| chromium / chrome | 浏览器引擎 | ❌ 未找到 |
| Firecrawl CLI | 远程抓取 + Markdown | ❌ 未安装 |
| Pillow | 图像处理 / tile 切分 | ❌ 未安装 |

---

## 二、Text/DOM 采集候选方案

### 方案 A：Python requests + bs4（本地轻量）

- `pip install requests beautifulsoup4 html2text`
- 优点：零外部依赖、无需 API key、可离线
- 缺点：不处理 JS 渲染的页面（SPA/docs 站可能缺内容）
- 适用性：fastapi.tiangolo.com 为静态 HTML ✅；docs.trychroma.com 和 docs.langchain.com 需验证是否为客户端渲染

### 方案 B：Firecrawl scrape API

- 需 `FIRECRAWL_API_KEY` 和 Firecrawl SDK
- 优点：处理 JS 渲染、自动转 Markdown、抓取质量高
- 缺点：依赖外部 API、需认证
- 适用性：通用 ✅

**建议**：Phase 3E1 先用方案 A 尝试 fastapi.tiangolo.com（确认静态渲染成功），再根据结果决定是否需要方案 B。

---

## 三、Visual Screenshot 采集候选方案

### 方案 A：Playwright + Chromium（本地渲染）

- `pip install playwright && playwright install chromium`
- 优点：全功能浏览器渲染、full-page screenshot、JS 执行
- 缺点：Chromium 下载 ~300MB，首次安装耗时长
- 适用性：通用 ✅

### 方案 B：Pillow 仅做 tile 切分（不截图）

- 如果已有 PNG 来源（如 Firecrawl screenshot API 或手动截图），用 Pillow 做 tile
- `pip install Pillow`
- 优点：轻量
- 缺点：仍需外部截图来源

**建议**：Phase 3E1 尝试 Playwright。如果 Chromium 安装失败或不可接受，降级为 Text-only（跳过 visual capture），并在实验报告中记录原因。

---

## 四、Phase 3E1 降级策略

| 条件 | 降级方案 |
|------|----------|
| requests/bs4 不可用 | 安装后再执行（轻量依赖，无理由不安装） |
| Playwright/Chromium 不可用 | Visual capture 降级为 not_rendered；Phase 3E1 仅执行 Text/DOM capture |
| Firecrawl CLI 不可用 | 使用方案 A（requests+bs4）替代 |
| 全部文本工具不可用 | **Phase 3E1 中止**，记录原因，等待依赖安装 |

**硬约束**：不允许因工具不可用而自动安装大型依赖（Playwright/Chromium ~300MB）。
安装必须经人工确认。

---

## 五、建议 Phase 3E1 执行顺序

```
1. pip install requests beautifulsoup4 html2text  ← 轻量，可直接执行
2. python 脚本 GET 3 个 URL → raw.html → normalized.md
3. pip install playwright && playwright install chromium  ← 需人工确认后执行
4. 截图 3 个页面 → full_page.png → tile
5. 质量评估 → 报告
```

如果步骤 3 未获确认，Phase 3E1 仅执行步骤 1-2 和 5（Text-only 实验）。
