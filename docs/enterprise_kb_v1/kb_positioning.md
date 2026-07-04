# 企业知识库 v1 定位

> 版本: v1-draft | 状态: policy | 最后更新: 2026-07-04

---

## 一、知识库定位

**企业 AI 应用工程知识库** — 为内部 Agent + RAG 系统提供准确、可追溯、
受版本控制的工程知识。

### 是什么

- 外部权威技术文档的精炼版（FastAPI、Chroma、LangGraph 等）
- 内部工程规范与项目运行时快照
- 从历史问题中沉淀出的 runbook 和 eval case

### 不是什么

- ❌ 通用 AI 课程库（不收录课程讲义、作业、PPT）
- ❌ 网页爬虫大杂烩（不爬站后直接入库）
- ❌ 旧评测报告归档（旧 phase/forensic/audit report 不入库）
- ❌ LLM 训练语料（不是用来微调模型的）

---

## 二、内容来源

### 2.1 外部权威技术文档

- 白名单 URL 准入（写入 source_registry 后生效）
- Exa/人工搜索发现候选 → 人工审核 → 写入 registry → Firecrawl 抓取
- Context7 仅用于版本/API 核验，不作为主语料源

### 2.2 内部工程规范与项目快照

- 项目配置文件说明（settings.py、.env.example 的行为语义）
- RAG pipeline 数据流文档
- Agent graph 节点职责说明
- 必须由代码事实生成后经人工校正，不可直接抄录源码

### 2.3 Runbook 和 Eval Case

- 从历史故障和评测中提炼的 runbook（不直接导入旧评测数据）
- eval case 从 core_eval_30 起步，逐步扩充

---

## 三、工作区边界

| 工作区 | 路径 | 用途 |
|--------|------|------|
| **生产工作区** | `E:\RAG\agent-service-toolkit-clean` | 代码、配置、KB v1 语料和文档 |
| **旧工作区（只读）** | `E:\Woker` | 历史参考，不可直接导入 |

### 旧工作区使用原则

- 旧工作区只读，不移动、不修改、不删除
- 旧语料、旧评测、旧 report **不允许直接复制**到新知识库
- 旧工作区内容仅可提炼为 runbook / failure pattern / eval case / policy lesson
- 提炼时必须改写为通用表述，不带旧路径、旧文件名、旧实验编号

---

## 四、设计原则

1. **Source Registry 驱动** — 所有内容必须注册在 source_registry.yaml，不允许扫描目录自动入库
2. **enabled=false 默认** — 新 source 默认不参与检索，须经准入审核
3. **doc_status 显式** — 每条文档标记 implemented/policy/draft/planned/deprecated/legacy_derived
4. **可追溯** — 外部文档原 URL + 抓取日期，内部文档关联 git commit
5. **最小可用** — v1 首期聚焦 4 类来源 × 30 条 core eval，不追求全量
