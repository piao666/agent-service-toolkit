# Phase 3E0 Dry-Run 预执行计划

> 版本: v1-draft | 状态: dry_run_plan | 最后更新: 2026-07-04

---

## 一、Dry-Run 目标

对 Phase 3D 选择的 3 个样本生成逐样本的预期采集动作、产物路径、质量检查点和失败回滚条件。本轮不执行实际采集。

---

## 二、样本

| sample_id | source_id | origin_url |
|-----------|-----------|------------|
| S1 | fastapi_official_middleware | https://fastapi.tiangolo.com/tutorial/middleware/ |
| S2 | chroma_official_metadata_filter | https://docs.trychroma.com/docs/querying-collections/metadata-filtering |
| S3 | langgraph_official_stategraph | https://docs.langchain.com/oss/python/langgraph/graph-api |

---

## 三、逐样本 Dry-Run 计划

### S1 — fastapi_official_middleware

**Text/DOM 预期采集动作**：
1. HTTP GET `https://fastapi.tiangolo.com/tutorial/middleware/`
2. 提取正文 HTML（排除 nav/sidebar/footer）
3. html2text / markdownify 转为 Markdown

**Visual Screenshot 预期采集动作**：
1. headless browser 打开 URL，等待加载完成
2. full-page screenshot → `S1_full_page.png`
3. viewport 高度 ~1080px 切 tile → `S1_tile_001.png` ...

**预期产物（Phase 3E1 创建）**：
```
experiments/phase3d_multimodal/text_dom/S1/
  raw.html, normalized.md, text_metadata.json
experiments/phase3d_multimodal/visual/S1/
  full_page.png, tiles/S1_tile_*.png, visual_metadata.json
```

**质量检查点**：
- [ ] `@app.middleware("http")` 代码块完整
- [ ] request/response/call_next 上下文保留
- [ ] middleware 注册和执行顺序列表完整
- [ ] 标题 H1-H3 全保留
- [ ] 截图无截断

**失败回滚条件**：
- 代码块截断 >30% → S1 Text FAIL
- 截图截断或 tile 编号混乱 → S1 Visual FAIL
- 截图体积 >20MB → 超出预算

---

### S2 — chroma_official_metadata_filter

**Text/DOM 预期采集动作**：
1. HTTP GET `https://docs.trychroma.com/docs/querying-collections/metadata-filtering`
2. 提取正文（页面可能含代码 tabs，需保留所有语言变体）
3. 清洗为 Markdown

**Visual Screenshot 预期采集动作**：
1. headless browser 渲染（页面可能含 JS 加载的代码示例 tabs）
2. full-page screenshot + tile

**预期产物**：
```
experiments/phase3d_multimodal/text_dom/S2/
  raw.html, normalized.md, text_metadata.json
experiments/phase3d_multimodal/visual/S2/
  full_page.png, tiles/S2_tile_*.png, visual_metadata.json
```

**质量检查点**：
- [ ] 操作符表 ($eq/$ne/$gt/$lt/...) 列对齐正确
- [ ] 嵌套 JSON 过滤示例缩进层级可读
- [ ] 代码块语法高亮信息保留（至少在 visual channel）
- [ ] 表格表头保留

**失败回滚条件**：
- 嵌套 JSON 不可读 → S2 Text FAIL
- 操作符表错位 → S2 Visual 质量警告
- 截图缺损代码/表格区域 → S2 Visual PARTIAL

---

### S3 — langgraph_official_stategraph

**Text/DOM 预期采集动作**：
1. HTTP GET `https://docs.langchain.com/oss/python/langgraph/graph-api`
2. 长页面需确认 Markdown 标题层级是否完整（页面可能包含多层级 H2-H4）

**Visual Screenshot 预期采集动作**：
1. headless browser 渲染长页面
2. full-page screenshot（长页面截图可能很高）+ tile

**预期产物**：
```
experiments/phase3d_multimodal/text_dom/S3/
  raw.html, normalized.md, text_metadata.json
experiments/phase3d_multimodal/visual/S3/
  full_page.png, tiles/S3_tile_*.png, visual_metadata.json
```

**质量检查点**：
- [ ] H1-H4 标题完整，无越级/丢失
- [ ] State / Nodes / Edges / Conditional edges 概念段落边界清晰
- [ ] 代码块与前后文关联保留
- [ ] 长页面 tile 无断裂

**失败回滚条件**：
- 标题丢失 >20% → S3 Text FAIL
- 概念段落边界模糊 → S3 Text WARNING
- 长页面截图截断或 tile 编号出界 → S3 Visual FAIL

---

## 四、人工确认清单

Phase 3E1 执行前，人工必须确认以下全部项目：

- [ ] `phase3e0_dry_run_plan.md` 已通读
- [ ] `phase3e0_capture_tool_preflight.md` 已确认依赖状态
- [ ] 文本采集工具可用或替代方案已确定
- [ ] 截图工具可用或已同意降级为 Text-only
- [ ] 实验目录 `experiments/phase3d_multimodal/` 未预先存在
- [ ] source_registry 未被修改
- [ ] 确认仅采集 3 个 URL
- [ ] 签核：_____________ (日期: ________)
