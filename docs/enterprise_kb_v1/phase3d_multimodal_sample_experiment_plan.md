# Phase 3D 多模态小样本采集实验方案

> 版本: v1-draft | 状态: draft | 最后更新: 2026-07-04

---

## 一、实验目标

从 19 条 verified 外部官方文档中选择 3 个分层样本，设计 Text/DOM + Visual Screenshot 双通道采集实验方案。验证：

1. Markdown/Text 解析是否丢失表格、流程图、布局、代码块位置等结构信息
2. Screenshot tile 是否能补足纯文本丢失的结构信息
3. 是否值得正式引入 visual sidecar（ROI 评估）
4. 双通道是否会引入不可接受的存储、性能、依赖成本

---

## 二、实验边界

| 范围 | 说明 |
|------|------|
| **Phase 3D** | 只设计实验方案。不抓取、不截图、不 embedding、不 Chroma |
| **Phase 3E** | 执行采集（经人工确认后） |
| **样本数** | 3（分层采样，覆盖 3 个 domain） |
| **采集方式** | Text: 候选 Firecrawl scrape；Visual: 候选 browser render + tile |
| **正式入库** | 不进入。实验产物放在 experiments/ 目录，独立于 formal pipeline |

---

## 三、为什么只选 3 个样本

1. **先验后扩**：在不确定视觉收益前投入全量（19 条）不可接受
2. **domain 覆盖**：3 个样本覆盖 api_backend / vector_database / agent_orchestration 三个核心域
3. **风险可控**：存储（3 页 × 可能 10-20 tiles/page × 2-5MB = <150MB 实验预算）
4. **代表性足够**：一个域的文档页面通常共享相同的布局模板，3 个域的结果可外推

---

## 四、样本选择

| sample_id | source_id | domain | URL | 代表风险 |
|-----------|-----------|--------|-----|----------|
| S1 | fastapi_official_middleware | api_backend | https://fastapi.tiangolo.com/tutorial/middleware/ | 代码块 + request/response 处理链路 + middleware 执行顺序 |
| S2 | chroma_official_metadata_filter | vector_database | https://docs.trychroma.com/docs/querying-collections/metadata-filtering | 过滤语法 + 嵌套 JSON + 参数结构 + 操作符表格 |
| S3 | langgraph_official_stategraph | agent_orchestration | https://docs.langchain.com/oss/python/langgraph/graph-api | 长页面标题层级 + State/Nodes/Edges 概念 + 代码上下文 |

### S1 选择理由 — fastapi_official_middleware

- FastAPI middleware 文档以 `@app.middleware("http")` 为核心，覆盖 request → response → call_next 链路
- **Text 风险**：代码块与 request/response 上下文的关联在扁平 markdown 中可能断裂；多个 middleware 的执行顺序列表可能被扁平化
- **Visual 价值**：截图可保留代码块 + 周边说明文字的空间关系。CORS 仅作为跨页链接/提示出现，不承担表格验证角色

### S2 选择理由 — chroma_official_metadata_filter

- Chroma metadata filtering 文档：操作符语法 → 嵌套过滤 JSON → 代码示例 → 参数结构表格
- **Text 风险**：复杂 JSON 过滤语法在 markdown 中缩进/嵌套层级可能错乱；操作符矩阵表格可能变形
- **Visual 价值**：截图保留原始语法高亮、缩进、表格对齐。S2 是主要结构化验证样本

### S3 选择理由 — langgraph_official_stategraph

- LangGraph Graph API 文档覆盖 StateGraph、State、Nodes、Edges、Conditional edges、代码示例、Visualization 链接
- **Text 风险**：长页面标题层级（H1-H4）密集，markdown 中概念段落边界可能模糊；State/Nodes/Edges 的概念上下文在文本中可能分散
- **Visual 价值**：页面截图保留长文档的 section 边界和代码块的上下文位置。不假设页面包含流程图/概念图

---

## 五、各通道验证目标

### 5.1 Text/DOM 通道

| 验证项 | 方法 |
|--------|------|
| 标题层级完整性 | 对比 normalized.md 的 H1-H4 层级是否与页面一致 |
| 代码块完整性 | 检查代码块是否包含 import、函数签名、关键逻辑行 |
| 表格转 Markdown 正确性 | 手动对比原始页面表格与 markdown 表格的列对列 |
| 列表/步骤顺序 | 检查 `1.` `2.` 等有序列表是否完整保留 |
| 页面噪声控制 | 检查 normalized.md 中侧边栏/导航/页脚是否已被移除 |

### 5.2 Visual Screenshot 通道

| 验证项 | 方法 |
|--------|------|
| 全页覆盖 | 检查 full-page screenshot 是否覆盖页面顶到底 |
| Tile 编号稳定性 | 检查 tile 的命名/编号是否为 {sample_id}_tile_{N}.png |
| 表格可见性 | 放大 tile 图片确认表格线、对齐、内容可读 |
| 代码/注释布局 | 确认代码块与右侧注释（如有）的相对位置在截图中可见 |
| 干扰排除 | 确认截图中无 cookie banner / 浮层弹窗遮挡 |

### 5.3 Cross-channel 对齐

| 验证项 | 方法 |
|--------|------|
| chunk→tile 映射 | 对 text chunk 标注对应 tile 编号 |
| metadata 一致性 | 确认 text metadata 和 visual metadata 中 source_id/url/capture_time 一致 |
| traceability | 确认能从 chunk 回溯到 source_id + sample_id + tile |

---

## 六、质量门禁

| 门禁 | 条件 |
|------|------|
| Text 通过 | 标题层级保留 ≥90%，代码块完整，表格可读 |
| Visual 通过 | 全页覆盖，tile 可映射到页面区域，无截断 |
| Cross-channel 通过 | chunk→tile 映射成立，metadata 一致 |
| 成本通过 | 单页截图 <5MB，tile 总数 <20/page，无 GPU 依赖 |

### 失败判定标准

| 失败类型 | 标准 |
|----------|------|
| Text 失败 | 标题丢失 >20% 或代码块截断 >30% |
| Visual 失败 | 截图截断或 tile 编号混乱 |
| Cross-channel 失败 | chunk→tile 映射断裂 |
| 成本失败 | 单页 >20MB 或 tile >50/page |

### 不进入正式入库的条件

- 任何通道失败判定标准触发
- visual sidecar 在 1/3 样本上改善幅度 <10%
- visual sidecar 引入的存储/延迟开销超过基准 50%

---

## 七、预期产物（Phase 3E 生成，本轮不创建）

参见 `phase3d_expected_artifact_contract.md`

---

## 八、后续流程

```
Phase 3D (本轮) — 实验方案设计
Phase 3E (下次) — 人工确认 → 执行 3 样本采集 → 质量评估
Phase 3F (后续) — 根据 Phase 3E 结果决定 visual sidecar 是否扩至更多 URL
```
