# Source Registry 规范

> 版本: v1-draft | 状态: policy | 最后更新: 2026-07-04

---

## 一、概述

`source_registry.yaml` 是企业知识库 v1 的**唯一准入入口**。
任何内容在入库前必须在此注册，否则不能进入 ingestion pipeline。

### 核心原则

- **不扫描目录自动入库** — 目录结构仅用于存储，不驱动入库逻辑
- **enabled=false 不可入库** — 注册 ≠ 入库；必须显式改为 `enabled: true`
- **人工审核必经** — 外部 URL 须白名单准入，内部文档须人工核对

---

## 二、source_id 命名规则

```
{domain_prefix}_{topic}_{scope}
```

| 段 | 规则 | 示例 |
|----|------|------|
| domain_prefix | 来源领域缩写 | `fastapi`, `chroma`, `langgraph`, `internal` |
| topic | 主题关键词 (snake_case) | `routing`, `collection`, `stategraph`, `runtime_snapshot` |
| scope | 可选范围限定 | `official`, `internal`, `policy` |

**命名约束：**
- 全小写，snake_case
- 不含版本号（版本信息在 `version_policy` 字段）
- 不含旧工作区实验编号
- 唯一性由人工维护

---

## 三、字段说明

### 标识字段

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `source_id` | string | ✅ | 全局唯一标识，遵循命名规则 |
| `title` | string | ✅ | 人类可读标题 |
| `domain` | string | ✅ | 知识领域，用于检索路由 |
| `source_type` | enum | ✅ | 来源类型: `external_official` / `internal_project` / `policy` / `runbook` |
| `doc_type` | enum | ✅ | 文档格式: `web_markdown` / `internal_markdown` / `policy_markdown` / `runbook_markdown` / `openapi_json` / `config_template` / `code_markdown` |
| `authority_level` | enum | ✅ | 权威级别: `official` / `internal_current_snapshot` / `internal_authoritative` / `internal_policy` / `legacy_derived`。旧称 `authoritative`/`derived` 已弃用，分别对应 `official`/`legacy_derived` |

### 控制字段

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `enabled` | bool | ✅ | `true` 才允许 ingest |
| `allowed_for_answer` | bool | ✅ | 是否允许作为答案依据 |
| `answer_scope` | enum | — | `current_behavior` / `technical_reference` / `engineering_policy` / `troubleshooting` / `future_plan` |
| `doc_status` | enum | ✅ | `implemented` / `policy` / `draft` / `planned` / `deprecated` / `legacy_derived` |

### 路径和版本

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `origin_url` | string | — | 外部文档原始 URL。`url_status=verified` 时写入已验证的最终官方页面 URL；`url_status=needs_manual_review` 时为 null，candidate_url 作为候选入口页保留。内部文档可为 null。**禁止写入 TODO 占位符** |
| `local_path` | string | ✅ | raw/normalized/chunks 的根路径 |
| `version_policy` | enum | ✅ | `latest_stable` / `pinned_version` / `continuous_track` |
| `chunk_policy` | object | ✅ | 分块策略配置 |

### 审计字段

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `owner` | string | ✅ | 负责人/团队 |
| `last_verified` | date | — | 最后人工审核日期 |
| `notes` | string | — | 审核备注、待办事项 |

### 采集通道字段（Phase 3C0 新增，external_official 必填）

**适用范围**：以下字段对 `source_type=external_official` **必填**。对 `internal_project` / `policy` / `runbook` 可选（不适用 visual_capture）。

**安全约束**：`url_status=needs_manual_review` 的 source 必须设置 `text_capture.enabled=false`、`retrieval_channels=[]`。只有 `url_status=verified` 且 `enabled=true` 的 source 才允许进入 text/visual 抓取流程。

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `text_capture` | object | ext_official ✅ | Text/DOM 主通道配置 |
| `text_capture.enabled` | bool | ext_official ✅ | 默认 true（needs_manual_review 时强制 false） |
| `text_capture.method` | string | ext_official ✅ | 抓取方式：`firecrawl_or_dom` |
| `text_capture.status` | string | ext_official ✅ | `not_fetched` / `fetched` / `normalized` / `chunked` / `indexed` |
| `visual_capture` | object | ext_official ✅ | Visual screenshot sidecar 配置 |
| `visual_capture.enabled` | bool | ext_official ✅ | 默认 false |
| `visual_capture.method` | string | ext_official ✅ | 渲染方式：`pixelshot_candidate` |
| `visual_capture.status` | string | ext_official ✅ | `not_rendered` / `rendered` / `tiled` / `embedded` / `indexed` |
| `visual_capture.tile_policy` | string | ext_official ✅ | 切分策略：`viewport_tiles` |
| `visual_capture.allowed_for_answer` | bool | ext_official ✅ | 视觉资产是否可作为回答依据（默认 false） |
| `retrieval_channels` | list | ext_official ✅ | 可用检索通道：`text` + 可选 `visual_optional`。needs_manual_review 时为空列表 `[]` |

### 字段区分说明

**source_type** (来源分类) — 回答"这个文档从哪来"：
- `external_official`: 外部官方文档 (如 FastAPI 官网)
- `internal_project`: 项目内部生成 (如代码快照)
- `policy`: 团队工程规范
- `runbook`: 故障排查手册

**doc_type** (文档格式) — 回答"这个文档是什么格式"：
- `web_markdown`: 从网页抓取并转为 Markdown
- `internal_markdown`: 内部人工撰写或代码生成的 Markdown
- `policy_markdown`: 策略文档 (Markdown)
- `runbook_markdown`: 排查手册 (Markdown)
- `openapi_json`: OpenAPI 规范 JSON
- `config_template`: 配置模板 (如 .env.example)
- `code_markdown`: 代码片段 + 自然语言说明

**answer_scope** (回答用途) — 回答"这个文档可以用来回答什么问题"：
- `current_behavior`: 当前系统实际行为
- `technical_reference`: 外部技术参考
- `engineering_policy`: 工程规范
- `troubleshooting`: 故障排查
- `future_plan`: 计划中的功能

---

## 四、准入流程

```
发现候选 → 写入 source_registry (enabled=false)
         → 人工审核 URL/内容/权限
         → enabled=true
         → ingest pipeline
```

### 外部文档额外要求

- URL 必须在白名单域名内
- 确认 robots.txt 允许抓取
- 确认内容许可（license 检查）

### 内部文档额外要求

- 必须由代码事实生成 → 人工校正
- 关联 git commit hash（可追溯）
- 不包含真实 API Key / 密码

---

## 五、doc_status 状态转换

```
planned → draft → policy → implemented
                        ↘ deprecated
legacy_derived (独立状态，不从其他状态转换而来)
```

- `planned`: 计划中，不可入库
- `draft`: 草稿中，可入库但 `allowed_for_answer=false`
- `policy`: 已确定为规范，优先于 `implemented` 回答
- `implemented`: 已实现并验证
- `deprecated`: 已废弃，保留在 registry 但不再检索
- `legacy_derived`: 从旧工作区提炼，标记来源但不自动入库（与其他状态并行，不参与标准状态转换流）
