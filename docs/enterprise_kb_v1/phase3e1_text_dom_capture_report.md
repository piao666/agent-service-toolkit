# Phase 3E1 Text/DOM Evidence-Driven Rebaseline 报告

> 时间: 2026-07-04 21:00 UTC+8 | 审计脚本: phase3e1_text_dom_audit.py
> 所有统计来自 `phase3e1_text_dom_audit.json`。算子检查使用 Python re.escape + 精确 token 边界。

## 一、抓取结果

| sample | URL | HTTP | HTML | Markdown | headings | code | tables | quality |
|--------|-----|------|------|----------|----------|------|--------|---------|
| S1 | fastapi.tiangolo.com/tutorial/middleware/... | 200 | 105KB | 4KB | 5 | 3 | 0 | **pass** |
| S2 | docs.trychroma.com/docs/querying-collections/metad... | 200 | 1430KB | 6KB | 7 | 14 | 1 | **pass** |
| S3 | docs.langchain.com/oss/python/langgraph/graph-api... | 200 | 2438KB | 47KB | 45 | 37 | 1 | **pass** |

### S1 — fastapi_official_middleware
- ✅ `@app.middleware("http")` 代码块完整保留（3 个 fenced 块）
- ✅ request / response / call_next 上下文全部出现在正文中
- ✅ middleware 执行顺序章节保留
- ✅ 标题层级 H1-H3 完整（5 个标题）
- 结构风险: **低**。静态 HTML，纯文本解析保真度高

### S2 — chroma_official_metadata_filter
- ✅ 14 个 fenced code blocks
- ✅ 1 个表格
- ✅ 标题层级 H2-H3 完整（7 个标题）
- Operator exact token 检查：
  - `$eq`: raw_html_exact=True, normalized_md_exact=True
  - `$ne`: raw_html_exact=False, normalized_md_exact=False
  - `$gt`: raw_html_exact=True, normalized_md_exact=True
  - `$lt`: raw_html_exact=False, normalized_md_exact=False
  - `$gte`: raw_html_exact=True, normalized_md_exact=True
  - `$lte`: raw_html_exact=True, normalized_md_exact=True
  - `$in`: raw_html_exact=True, normalized_md_exact=True
  - `$nin`: raw_html_exact=True, normalized_md_exact=True
  - `$and`: raw_html_exact=True, normalized_md_exact=True
  - `$or`: raw_html_exact=True, normalized_md_exact=True
  - `$contains`: raw_html_exact=True, normalized_md_exact=True
  - `$not_contains`: raw_html_exact=True, normalized_md_exact=True
- Content coverage notes:
  - S2: $ne not present in captured page content (raw or md)
  - S2: $lt not present in captured page content (raw or md)
- 结构风险: **低-中**。JS Tab 代码语言变体可能仅捕获默认。格式已标准化。

### S3 — langgraph_official_stategraph
- ✅ 37 个 fenced code blocks 覆盖 Python/JS 示例
- ✅ 45 个标题（H2-H4）完整保留
- ✅ 1 个表格保留
- ✅ 长页面 ~47KB 无截断
- 结构风险: **中**。长页面视觉层级在 Markdown 中扁平化

## 二、纯 Text/DOM 结构丢失风险

| 风险 | 严重度 | 表现 |
|------|--------|------|
| 代码块格式 | 低 | 已标准化为 fenced ``` |
| Tab 切换代码块 | 中 | S2 (Chroma) JS Tab 多语言变体可能仅捕获默认 |
| 页面布局扁平化 | 中 | S3 45 headings 在文本中无视觉层级区隔 |
| 链接上下文 | 低 | 跨页引用链接保留 |

## 三、建议

### 进入 Phase 3E1-B Screenshot sidecar 实测？

**建议：进入。**

理由：
1. 3 个页面 Text/DOM 全部 pass，基础格式门禁已通过。
2. raw.html 和 normalized.md 的 operator exact-token 检查已经可信。
3. S2 存在 content coverage note：$ne 和 exact $lt 未出现在捕获内容中（$lt 仅作为 $lte 的一部分出现，exact token 检查正确地将其排除）。需要通过 Screenshot sidecar 观察官方页面可视内容是否存在折叠、tab 或视觉结构差异。
4. S3 是长页面（45 headings），Markdown 扁平化后视觉层级信息可能丢失，适合用 Screenshot sidecar 做交叉验证。

---
*本报告所有数字来自 phase3e1_text_dom_audit.json。Operator 检查使用 Python re.escape + 精确 token 边界。*
