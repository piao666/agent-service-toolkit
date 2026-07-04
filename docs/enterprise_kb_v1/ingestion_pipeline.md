# Ingestion Pipeline 设计

> 版本: v1-draft | 状态: planned | 最后更新: 2026-07-04

---

## 一、流水线概览

```
source_registry.yaml (enabled=true)
        │
        ▼
  [fetch] ──→ raw_sources/{source_id}/{version}/
        │
        ▼
  [normalize] ──→ normalized/{source_id}/*.md
        │
        ▼
  [chunk] ──→ chunks/{source_id}/chunks.jsonl
        │
        ▼
  [embed + index] ──→ Chroma (storage/chroma_enterprise_kb_v1)
        │
        ▼
  [manifest] ──→ manifests/{build_id}/*.jsonl
```

---

## 二、外部文档抓取流程

### Step 1: 候选发现

- Exa 搜索或人工推荐候选 URL
- 初步判断：是否在 domain 白名单内、内容是否与 source_registry 已有 source 重复

### Step 2: 人工审核

- 确认 URL 内容与 `source_registry.yaml` 中的描述一致
- 确认 robots.txt / license 允许
- 圈定抓取章节范围（**禁止全站 crawl**）
- 将审核结果写入 source_registry 的 `notes`

### Step 3: 抓取

- Firecrawl 抓取指定的 URL 列表
- 保存到 `data/enterprise_kb_v1/raw_sources/{source_type}/{source_id}/`
- 文件命名: `{章节}_{页码}.md`

### Step 4: 清洗

- 移除导航栏、侧边栏、页脚
- 移除广告和推广链接
- 保留代码块和表格
- 统一为 Markdown 格式

### Step 5: 分块

- 按 Markdown 标题层级分块（`##` / `###`）
- chunk_size: 1024 tokens
- chunk_overlap: 200 tokens
- 保留 chunk 与 source 的映射关系

### Step 6: 入库

- `python scripts/enterprise_ingest.py --data-dir data/enterprise_kb_v1 --persist-dir ./storage/chroma_enterprise_kb_v1 --collection-name enterprise_kb_v1`
- 入库后记录 manifest

---

## 三、内部文档生成流程

### Step 1: 代码扫描

- 自动扫描 `src/settings.py`、`src/rag/`、`src/agents/` 等核心模块
- 提取配置项、数据流、类/函数签名

### Step 2: 草稿生成

- LLM 辅助生成自然语言描述
- 格式：`{配置项}: {当前默认值} — {作用说明}`

### Step 3: 人工校正

- 确认描述与代码行为一致
- 移除敏感信息
- 写入 `data/enterprise_kb_v1/raw_sources/internal_docs/`

### Step 4: 入库

- 同外部文档的 normalize → chunk → index 流程

---

## 四、Context7 使用边界

Context7 用于：

- ✅ 核验外部官方文档的最新版本号
- ✅ 确认 API 签名是否与文档一致
- ✅ 补充缺失的 API reference 细节

Context7 禁止用于：

- ❌ 作为主语料源直接入库
- ❌ 批量生成语料后不经审核直接 ingest
- ❌ 替代人工对官方文档原文的审核

---

## 五、禁止事项

1. ❌ **禁止全站 crawl** — 必须人工圈定抓取章节
2. ❌ **禁止自动目录扫描入库** — 必须通过 source_registry 准入
3. ❌ **禁止批量 LLM 生成语料** — 内部文档必须基于代码事实 + 人工校正
4. ❌ **禁止重复入库** — 每次 ingest 前检查 manifest 是否有未变化的 source
