# 失败案例模式与根因分析

本文档记录企业知识库 RAG 系统开发过程中遇到的 10 个真实失败案例，每个案例包含根因、症状、修复方案和教训，作为后续 Phase 的决策参考。

---

## 1. expected_source / expected_source_ids 字段不匹配导致 hit_rate=0

### 根因
评测用例（eval case）使用 `expected_source` 字段名存储期望来源，而检索结果的 metadata 使用 `source_id` 字段名。两套命名体系不一致，导致匹配逻辑永远返回 False。

### 症状
- `hit_rate` 报告为 0.0，但人工检查检索结果发现质量正常
- 所有 22 个评测 case 的 hit 计数均为 0
- MRR 同样为 0.0

### 修复
1. 在 eval schema 层统一使用 `expected_source_ids`（数组），放弃单值 `expected_source`
2. 新增 `_resolve_source()` 兼容函数，自动从 metadata 中提取 `source_id`、`source`、`origin_url` 等多种可能的字段名
3. 在 build 评测数据时做 schema 归一化：所有导入的 case 强制包含 `expected_source_ids` 字段

### 教训
**跨系统字段命名必须在 spec 层统一。** 评测系统（eval）与检索系统（retriever）之间的数据契约应在设计阶段用显式的 schema 定义固定，不能依赖"字段名差不多"的隐含假设。每个新增字段都应有对应的单元测试验证端到端匹配。

---

## 2. JS redirect shell 导致 LangGraph 内容缺失

### 根因
LangGraph 官方文档站使用客户端 JavaScript 重定向（SPA 模式），直接用 HTTP GET 或标准 HTML fetch 只能拿到空壳页面（`<div id="root"></div>` + JS bundle），实际文档内容在浏览器端渲染后才出现。

### 症状
- 知识库中 4 个 langgraph source 的 chunk 内容为 0-50 字符
- RAG 回答 LangGraph 相关问题时完全无法引用文档内容
- 对应的 `text_preview` 在 trace 中显示为空或仅含页面标题

### 修复
1. 切换采集工具：从直接 HTTP fetch 改为 Firecrawl `/scrape` 的 `render` 模式（启用 JS 渲染）
2. 对于已知 SPA 站点，使用 SSR 版本 URL（如 `https://langchain-ai.github.io/langgraph/ssr/...`）作为替代采集源
3. 如果上述两者都不可行，则从该 source 的 GitHub markdown 源文件直接采集

### 教训
**采集前必须做 precheck_screenshot_sidecar 验证内容完整性。** 每个新 source 加入知识库前，必须对第一页采集结果做内容长度检查（≥200 字符）和关键段落抽样，不一致的来源应立即标记为 `ingest_status: failed` 并报告原因。

---

## 3. YAML anchor / alias 污染 source metadata

### 根因
`source_registry.yaml` 中使用了 YAML 的 anchor (`&id001`) 和 alias (`*id001`) 特性来减少重复配置。PyYAML 在解析 alias 节点时，会将 anchor 节点的 dict 与 alias 节点的局部 key 做合并（merge），这个合并行为在某些 PyYAML 版本中会产生副作用：alias 节点修改了 anchor 节点的内部 dict，导致后续引用同一 anchor 的 source 拿到了被污染的 metadata。

### 症状
- 多个 source 的 `origin_url` 字段出现错误值（被其他 source 的 URL 覆盖）
- `source_type` 字段同样被跨 source 污染
- 问题间歇性出现，取决于 YAML 文件中 key 的排列顺序

### 修复
1. 禁用所有 YAML anchor/alias：每个 source 独立定义全部字段，不使用 `&anchor` / `*alias` 引用
2. 添加 CI 检查：对 `source_registry.yaml` 做 lint，检测并拒绝 anchor/alias 语法
3. 在 `source_registry.yaml` 文件头部添加注释 `# 禁止使用 YAML anchor/alias，每个 source 必须独立定义`

### 教训
**YAML 高级特性在简单配置文件中是风险源。** Anchor/alias 是为减少重复而生的语法糖，但在需要精确字段控制的配置文件中，它们引入了隐式的引用语义和版本依赖。简单重复比聪明的复用更安全。

---

## 4. code block extraction 丢失导致语料质量下降

### 根因
Markdown 解析器（splitter 中的 code fence 检测逻辑）未正确处理以下两种边界情况：
1. 缩进代码块（4 空格缩进，无 fence 标记）
2. 嵌套 code fence（外层用 ```` ``` ````，内层用 `~~~`）

导致这些代码块在切分时被当作普通段落处理，切分边界可能断在代码中间，使代码片段不完整或完全丢失。

### 症状
- 部分技术文档 chunk 缺少代码示例
- RAG 回答 API 用法问题时不能引用代码，只能给出文字描述
- chunk 质量 audit 中发现 `code_block_count` 远低于源文档实际代码块数量

### 修复
1. 增强 markdown splitter 的 code fence 状态机：
   - 添加缩进代码块检测（连续 4 空格缩进行）
   - 支持嵌套 fence（fence 开始后直到匹配的结束 fence，中间不再触发新的 fence 检测）
2. 在 chunk 切分后增加保护逻辑：如果检测到未闭合的 code fence，强制将切分点移到 fence 闭合之后
3. 添加 `code_block_count` 字段到 chunk metadata，用于后续 audit

### 教训
**Chunk 质量 audit 必须检查 code_block_count。** 技术文档的代码示例是最有价值的信息之一，如果切分器吞掉了代码块，整个知识库的实用价值直接减半。自动化质量门禁应包含"代码块保留率"指标。

---

## 5. per-case debug 不完整导致 embedding A/B 不可信

### 根因
Phase 4C 早期版本的 embedding A/B 对比脚本只输出聚合总分（`hit_rate`、`MRR`），没有输出每个 case 的详细检索结果（per-case debug JSONL）。当两个模型的聚合分数接近时（如 qwen3 和 bge-m3 的 MRR 相差不到 0.02），无法判断差异是系统性优势还是个别 case 的噪声。

### 症状
- qwen3-embedding-0.6b 和 bge-m3 在某些 case 上表现逆转（A 胜 B、B 胜 A 交替出现）
- 聚合分数无法解释为什么出现逆转
- 选型决策缺乏可审查的证据链

### 修复
强制输出 88 行 per-case debug（22 cases x 4 models），每行包含：
- case_id、query_text
- 期望 source_ids
- 实际检索到的 top-k source_ids（k=5）
- hit 标记、reciprocal_rank
- 每个结果的 score、source_id、heading_path、text_preview（前 128 字符）

这些 debug 行直接写入 JSONL 文件，可被 pandas 加载分析。

### 教训
**Aggregate metrics 不能替代 per-case debugging。** 聚合分数告诉你"整体好不好"，per-case 数据告诉你"为什么好/不好"。在模型选型场景中，per-case 对比是唯一能建立因果链条的方法 —— 否则两个模型总分接近时你只能抛硬币。

---

## 6. raw_sources / chunks / storage / models 未忽略导致仓库污染

### 根因
`.gitignore` 文件在项目初期不完整，缺少以下关键目录的忽略规则：
- `raw_sources/`（原始采集的大文档，体积可达数百 MB）
- `chunks/`（切分后的中间产物）
- `storage/`（Chroma 持久化数据）
- `models/`（本地嵌入模型权重文件）
- `*.zip`、`*.tar.gz`（打包文件）

### 症状
- `git push` 失败（单文件超过 GitHub 100MB 限制）
- 仓库体积爆炸（clone 耗时数分钟）
- 二进制文件、模型权重进入版本历史，事后清理极为困难

### 修复
在 `.gitignore` 中明确添加以下规则：
```gitignore
# 知识库数据
raw_sources/
chunks/
storage/
data/enterprise_kb_v1/chunks/
data/enterprise_kb_v1/raw_sources/

# 模型权重
models/
*.bin
*.safetensors
*.onnx

# 环境与密钥
.env
*.env.local
*_api_key*
*_API_KEY*

# 打包文件
*.zip
*.tar.gz
*.7z

# 评测产物（保留代码，忽略输出）
eval_results/*.jsonl
eval_results/*.csv
```

### 教训
**Repo hygiene 策略必须在 Phase 0 就设计好。** 等数据已经进入 Git 历史再补 `.gitignore`，需要 `git filter-branch` 或 `BFG Repo-Cleaner` 清理历史，成本远高于从一开始就配置好忽略规则。

---

## 7. RAG answer eval 与 retrieval context eval 命名混淆

### 根因
Phase 4C 同时存在两个评测脚本：
- `retrieval_context_eval.py`：只测检索质量（hit_rate、MRR），不涉及 LLM 生成
- `rag_answer_eval.py`：测完整 RAG 回答质量（citation 准确性 + answer 质量）

两个脚本名称相似，团队在讨论和报告中混淆了两者。

### 症状
- 会议中用 "retrieval context eval 的 hit_rate 达到 85%" 声称 "RAG answer 评测通过"
- 实际上 `rag_answer_eval` 尚未执行，citation 验证完全没做
- 利益相关方对"评测通过"的含义产生了错误认知

### 修复
1. 明确区分命名：
   - **检索评测（Retrieval Eval）**：只测 `hit_rate`、`MRR`，确认"检索系统有没有把相关文档排在前面"
   - **RAG 回答评测（RAG Answer Eval）**：测 `citation_accuracy`、`answer_faithfulness`、`answer_relevance`，确认"最终回答是否基于检索结果且准确"
2. 在报告模板中强制标注评测类型（哪种 eval、测什么、不测什么）
3. 两个评测的输出文件使用不同前缀：`retrieval_eval_*` vs `answer_eval_*`

### 教训
**Eval 类型命名必须自解释。** 当两个 eval 都涉及 RAG 时，它们的名称必须一眼能区分"测检索"还是"测回答"。如果类型名称需要额外解释，命名就是失败的。

---

## 8. bge-small 本地低效，HPC 上 bge-m3 / qwen3 A/B 后选择 bge-m3

### 根因
本地开发环境是 CPU-only（16 核，无 CUDA GPU），`sentence-transformers` 只能跑 CPU 推理。bge-small-zh-v1.5 模型编码 1117 个 chunk 在本地需要数小时，完全阻塞迭代流程。

### 症状
- 本地跑一次完整的 embedding 索引构建需要 3-6 小时
- workflow 严重堵塞，一天只能验证 1-2 个修改
- CPU 风扇全程满载，开发机无法同时做其他工作

### 修复
1. 将所有 embedding 操作迁移到 HPC GPU（NVIDIA L40, 11GB VRAM）
2. 本地只做代码编写、语料修复、脚本准备、HPC 运行包打包
3. 在 HPC 上完成 bge-m3 vs qwen3-embedding-0.6b 的 A/B 评测后，选定 bge-m3 作为默认模型
4. 本地保留 bge-small 仅用于 smoke test（单条 encode 验证代码正确性）

### 教训
**硬件约束必须在架构设计阶段明确。** CPU-only 环境下，embedding 模型的任何批量操作都是不可行的。如果项目初期就明确"本地只做代码开发，所有重计算走 HPC"，可以节省数天的无效等待时间。

---

## 9. trace 缺 origin_url / heading_path / text_preview 导致无法支撑 citation

### 根因
Phase 4E 初版 trace schema 只有 10 个字段：
`[query, retrieved_doc_ids, retrieved_scores, rank, source_ids, chunk_ids, content_lengths, retrieval_latency_ms, model_name, timestamp]`

这些字段仅覆盖检索性能分析，不包含生成 citation 所需的关键信息。

### 症状
Phase 4E1 尝试从 trace 中生成 citation 时发现：
- 没有 `origin_url`，无法生成"来源：xxx"的可点击链接
- 没有 `heading_path`，无法生成"来自 xxx 章节"的上下文引用
- 没有 `text_preview`，无法验证 citation 引用的内容是否与原文一致

### 修复
将 trace schema 从 10 字段扩充到 13 字段，新增：
- `origin_urls`：来源文档的原始 URL 列表
- `heading_paths`：文档层级路径（H1 > H2 > H3）
- `text_previews`：检索结果的前 256 字符预览

向后兼容：旧版本 trace 文件缺少新字段时填充 `null`，不影响已有分析脚本。

### 教训
**Trace schema 必须从下游消费方反推设计。** 设计 trace 时不能只想"检索需要什么字段"，而应该从最终消费方出发：citation 生成需要什么、评测需要什么、调试需要什么。schema 设计的最佳实践是：先写出消费方代码，再回填 trace 输出。

---

## 10. core_029 失败反映 official_docs 不足以回答项目级 RAG 调参问题

### 根因
`official_docs` 语料库仅包含外部技术文档（LangChain 官方文档、Chroma 文档、sentence-transformers README 等），不含本项目自身的工程决策和调参经验。

### 症状
评测 case `core_029` 的问题是："为什么 bge-m3 被选为默认 embedding？"，预期答案是"经过 HPC 上 bge-m3 vs qwen3 A/B 评测后的性价比决策"。
- `official_docs` 语料库中完全没有这个信息（外部文档不会记录本项目为什么选某个模型）
- 检索结果虽然返回了 bge-m3 的技术文档，但 hit_rate 为 0（不包含决策理由）
- 此类"为什么选择 X"的项目级问题在 22 个 eval case 中有 3 个无法在 `official_docs` 中找到答案

### 修复
1. 构建 `internal_engineering_docs` 语料库（Phase 4F 执行），收录：
   - 本项目所有 Phase 的技术报告和决策记录
   - embedding A/B 评测结果和分析
   - 架构设计文档和 trade-off 讨论
2. 将 `internal_engineering_docs` 与 `official_docs` 合并为统一知识库
3. 新增 3 个 eval case 验证内部文档的检索质量

### 教训
**外部文档不能替代内部工程经验语料。** 企业知识库的真正价值不在于重复外部文档已有内容，而在于编码组织内部的决策理由、调参经验、踩坑记录。这些"为什么"类知识是外部文档永远无法提供的。

---

## 案例维度速查表

| 编号 | 类别 | 严重性 | Phase | 是否可自动检测 |
|------|------|--------|-------|----------------|
| 1 | Schema 不一致 | 高 | 4C | 是（单元测试） |
| 2 | 采集质量问题 | 高 | 4B | 是（内容长度检查） |
| 3 | 配置污染 | 中 | 4B | 是（YAML lint） |
| 4 | 切分质量 | 中 | 4B | 是（code_block_count） |
| 5 | 评测不完整 | 中 | 4C | 是（debug JSONL 行数检查） |
| 6 | 仓库污染 | 高 | 0 | 是（.gitignore CI） |
| 7 | 命名混淆 | 中 | 4C | 否（需人工审查） |
| 8 | 硬件约束 | 中 | 4B | 否（需架构决策） |
| 9 | Schema 不完整 | 中 | 4E | 是（schema 字段数检查） |
| 10 | 语料覆盖不足 | 中 | 4F | 是（eval hit_rate 监控） |
