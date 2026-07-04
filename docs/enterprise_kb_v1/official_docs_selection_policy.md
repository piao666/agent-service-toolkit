# 外部官方文档选取策略

> 版本: v1-draft | 状态: policy | 最后更新: 2026-07-04

---

## 一、核心原则

### 1.1 首版限定——只允许官方文档

企业知识库 v1 的外部知识源**仅收录官方文档**。不收录以下类型：

- ❌ 博客文章（Medium、Dev.to、个人技术博客）
- ❌ 社区论坛（StackOverflow、Reddit、GitHub Issues/Discussions）
- ❌ 教程站（Real Python、GeeksforGeeks、W3Schools、菜鸟教程）
- ❌ 视频平台（YouTube、Bilibili）
- ❌ 第三方聚合站（如某个人的 Awesome-xxx 列表）
- ❌ 非官方翻译/镜像

**理由**：官方文档是 API 行为的事实来源（source of truth）。非官方来源可能存在信息滞后、不准确、或与官方版本冲突。v1 阶段优先建立可靠的知识基础层。

### 1.2 禁止全站 Crawl

**禁止**对任何域名执行全站 crawl。原因：

1. **法律合规**：全站 crawl 可能违反目标网站的 robots.txt 和 ToS
2. **信噪比**：官方文档站通常包含大量非技术页面（blog、changelog、community），全站 crawl 会引入噪声
3. **成本控制**：全站 crawl 消耗大量带宽和存储，而有效信息只集中在少数核心章节
4. **维护性**：选择性抓取使每个 source 的更新策略和版本追踪更清晰

**替代方案**：通过 allowlist 明确每个 source 的 candidate_url，抓取范围限定在指定的页面/章节。

### 1.3 工具分工

| 工具 | 用途 | 限制 |
|------|------|------|
| **Exa / WebSearch** | 仅用于**发现候选 URL**。如需要确认某官方文档的组织结构，可用 web search 查找入口页 | 不可作为主语料源。不可直接入库 |
| **Firecrawl** | 仅用于**抓取已审核 allowlist URL**。抓取前 URL 必须通过人工审核确认可合法抓取 | 不可抓取 allowlist 之外的 URL |
| **Context7** | 仅用于**版本/API 核验**。如确认 API 参数名称、默认值、版本变更 | 不可作为主语料源。内容不直接入库 |

### 1.4 两阶段准入

外部文档必须经过两阶段才能入库：

```
Phase A: official_docs_allowlist.yaml
  → 候选 URL 登记 (url_status=candidate_unverified)
  → 人工审核 URL 合法性、许可、范围
  → url_status → verified

Phase B: source_registry.yaml
  → 候选 source 可在 Phase A 审核期间以 disabled 状态同步登记到 source_registry
  → 但抓取和入库仍需等待 url_status=verified
  → 只有 url_status=verified、fetch_status=ready、enabled=true 的 source 才允许 Firecrawl 抓取并进入 ingestion pipeline
  → 入库后 allowed_for_answer 方可设为 true
```

**关键约束**：
- 未审核 URL（`url_status=candidate_unverified`）**不允许 Firecrawl 抓取**
- 未在 allowlist 中的 URL **不允许抓取**
- `enabled=false` 的 source **不允许作为答案依据**
- `allowed_for_answer=false` 的 source 检索结果仅用于 debug，不可呈现给用户

---

## 二、审核清单

每条 allowlist 条目的人工审核必须确认：

1. **robots.txt**：目标 URL 路径未被 `Disallow`
2. **ToS/License**：内容许可允许用于 RAG 知识库
3. **URL 有效性**：candidate_url 页面确实存在，内容确实覆盖 selection_reason 描述的主题
4. **抓取范围**：该 URL 页面覆盖的章节范围是否足够（是否需要拆分为多个 source）
5. **版本匹配**：文档版本与项目使用的库版本是否兼容

---

## 三、维护策略

| 策略 | 说明 |
|------|------|
| 版本追踪 | 库大版本更新时（如 FastAPI 0.100 → 0.110），需人工复查 allowlist URL 是否仍有效 |
| 增量新增 | 每轮迭代最多新增 10 条外部 source，避免一次性膨胀 |
| 废弃处理 | 外部文档下线或迁移时，对应 source 标记 `doc_status=deprecated` |
