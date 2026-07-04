# 知识库准入策略

> 版本: v1-draft | 状态: policy | 最后更新: 2026-07-04

---

## 一、准入六要素

每一份入库文档必须满足以下 6 个要素，任一项不满足则拒绝入库：

| # | 要素 | 要求 | 验证方式 |
|---|------|------|---------|
| 1 | **来源明确** | 有 origin_url 或明确的内部来源（git commit/文档作者） | source_registry 字段 |
| 2 | **类型明确** | doc_type 必须在枚举内，不可为 unknown | source_registry 字段 |
| 3 | **用途明确** | answer_scope 必须在枚举内 | source_registry 字段 |
| 4 | **权限明确** | 外部文档须 license 允许；内部文档须确认不包含敏感信息 | 人工审核 |
| 5 | **状态明确** | doc_status 不能是 unknown | source_registry 字段 |
| 6 | **可追溯** | 能追溯到原始来源和审核记录 | source_registry + git log |

---

## 二、外部文档准入

### 白名单规则

- 只有 `source_registry.yaml` 中 `source_type=external_official` 且 `enabled=true` 的 URL 才允许抓取
- 禁止抓取白名单外的任何 URL
- 禁止 crawl 整站后直接入库（必须人工圈定章节范围）

### 审核流程

```
1. 提名人将候选 URL + 理由写入 source_registry (enabled=false)
2. 审核人确认:
   - robots.txt 允许
   - 内容 license 允许
   - 与已有 source 无 >50% 语义重叠
   - 章节范围合理（非整站 crawl）
3. enabled=true
4. Firecrawl 抓取指定 URL
5. 保存 raw → 人工 spot-check → normalized → chunk
```

### 禁止事项

- ❌ 禁止 crawl 整站
- ❌ 禁止抓取付费墙/登录墙内容
- ❌ 禁止抓取明确标注 "不可转载" 的内容
- ❌ 禁止用 Context7 作为主语料源（仅作版本核验）

---

## 三、内部文档准入

### 生成规则

- 从代码事实（settings.py、graph 定义、pipeline 流程）自动生成草稿
- **必须经人工校正**后才能入库

### 校正要求

- 确认描述与当前代码行为一致
- 移除所有真实 API Key / 密码 / 内部 IP 地址
- 用自然语言描述，不抄录源码
- 关联 git commit hash

---

## 四、旧工作区内容处理

旧工作区内容**不允许原样入库**。只允许提炼为：

| 提炼产出 | 说明 | 示例 |
|---------|------|------|
| **runbook** | 故障排查流程 | "检索返回空 → 检查 collection 是否存在 → 检查 embedding 维度是否匹配" |
| **failure pattern** | 已知失败模式 | "中文查询 + 英文文档时 relevance_score 偏低" |
| **eval case** | 评测用例 | core_eval_30 中的用例 |
| **policy lesson** | 工程教训 | "默认 Chroma 路径不应使用硬编码，必须通过 env 配置" |

**禁止：**
- ❌ 直接复制旧评测 JSONL/JSON/CSV
- ❌ 直接复制旧 manifest / chunk 文件
- ❌ 直接复制旧 report / forensic / audit 文档

---

## 五、拒绝模板

不满足准入条件的 source，在 source_registry 的 `notes` 字段中记录拒绝原因：

```yaml
notes: >
  REJECTED 2026-07-04: 来源不明确，无法确认原始 URL。
  建议：联系原作者确认来源后再提。
```
