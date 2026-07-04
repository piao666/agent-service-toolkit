# Phase 3D 执行护栏（Execution Guardrails）

> 版本: v1-draft | 状态: policy | 最后更新: 2026-07-04

---

## 一、适用范围

本护栏文档定义 **Phase 3E 之后** 多模态采集实验的执行约束。Phase 3D 当前阶段不执行任何采集。

---

## 二、样本范围约束

| # | 约束 | 理由 |
|---|------|------|
| 1 | **只允许**处理 `phase3d_sample_manifest.yaml` 中列出的 3 个样本 | 超出样本范围的 URL 不得进入实验 |
| 2 | **只允许**处理 `url_status=verified` 的 source | needs_manual_review / candidate_unverified 的 source 必须跳过 |
| 3 | **必须跳过** Qwen 两条 needs_manual_review source | 即使后续更新了 sample_manifest，只要 url_status 不是 verified 就跳过 |
| 4 | **不允许**全量抓取 19 条 verified URL | 实验阶段禁止批量抓取 |
| 5 | **不允许** crawl 整站 | 每个 source 只抓取指定的单个 candidate_url 页面 |

---

## 三、执行流程约束

### Step 1: Dry-run plan

- 对每个样本生成 dry-run plan，列出：
  - 将要使用的工具/方法
  - 预期文件产出
  - 预估文件大小
- **必须人工确认** dry-run plan 后才能执行

### Step 2: 执行采集

- 文本采集：仅对单个 candidate_url 执行
- 截图采集：仅对单个 candidate_url 执行 full-page screenshot
- 采集产物进入 `data/enterprise_kb_v1/experiments/phase3d_multimodal/`（实验目录）
- **禁止**进入正式 `raw_sources/official_docs/` 目录

### Step 3: 质量评估

- 对每个样本按 `phase3d_capture_quality_rubric.md` 评分
- 输出评分结果到 `experiments/phase3d_multimodal/reports/`

---

## 四、禁止行为

| # | 禁止 | 理由 |
|---|------|------|
| 1 | **禁止**将实验产物直接加入 Chroma | 实验产物与正式知识库隔离 |
| 2 | **禁止**自动 enable source | 即使实验通过，也需人工审批后才能改 enabled=true |
| 3 | **禁止**将截图直接嵌入回答 | visual tile 默认 allowed_for_answer=false |
| 4 | **禁止**将实验产物路径混入 source_registry 的 local_path | 实验产物有独立存储路径 |
| 5 | **禁止**在生产 RAG 查询链路中引用实验目录 | 实验索引与正式索引隔离 |
| 6 | **禁止**在未人工确认的情况下从实验阶段迁移到正式阶段 | 必须经过 Phase 3F 评审 |

---

## 五、安全回滚

如果实验过程中发生任何不可预期问题（如文件系统溢出、截图工具 crash、浏览器泄漏）：

1. **立即停止**实验
2. 清理 `experiments/phase3d_multimodal/` 下的临时产物
3. 不修改 `source_registry.yaml` 和 `official_docs_allowlist.yaml`
4. 在 `phase3d_multimodal_sample_experiment_plan.md` 中记录失败原因

---

## 六、从实验到正式的迁移条件

实验产物迁移到正式 ingestion pipeline 必须满足：

1. 全部 3 个样本通过质量门禁（PASS 或 PASS_WITH_LIMITATIONS）
2. 成本评估在可接受阈值内
3. 人工审核确认无数据质量问题
4. Phase 3F 评审通过
5. source_registry 中对应 source 的 `fetch_status` 和 `visual_capture.status` 由人工显式修改
