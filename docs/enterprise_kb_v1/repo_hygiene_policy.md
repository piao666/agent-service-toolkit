# 仓库卫生策略

本文档定义企业知识库 RAG 项目的仓库卫生规范，包括 `.gitignore` 配置、允许/禁止提交的内容、大文件管理、Phase 归档约定和输出包管理。

---

## 1. .gitignore 完整清单

以下是最小必要忽略规则集，按类别组织。此清单应被视为强制规范，新成员加入项目时第一件事就是确认 `.gitignore` 已正确配置。

### 知识库数据（体积大、不可 diff）

```gitignore
# 原始采集文档
raw_sources/
data/enterprise_kb_v1/raw_sources/

# 文档切分产物
chunks/
data/enterprise_kb_v1/chunks/

# Chroma 向量数据库持久化
storage/
chroma_data/
*.sqlite3
*.sqlite3-journal
*.sqlite3-wal

# 模型权重文件
models/
*.bin
*.safetensors
*.onnx
*.pth
*.ckpt
*.pt
```

### 敏感信息

```gitignore
# 环境变量（含 API Key）
.env
.env.*
!.env.example
!.env.template

# 凭证文件
*_api_key*
*_API_KEY*
*credentials*.json
*secret*
*.pem
*.key
```

### 操作系统与编辑器

```gitignore
# Windows
Thumbs.db
Desktop.ini
$RECYCLE.BIN/

# macOS
.DS_Store
.AppleDouble
.LSOverride

# Linux
.directory

# IDE
.vscode/
.idea/
*.swp
*.swo
*~
```

### 打包与临时文件

```gitignore
# 打包文件
*.zip
*.tar.gz
*.tar.bz2
*.7z
*.rar

# 临时文件
*.tmp
*.temp
*.log
*.cache
__pycache__/
*.py[cod]
*$py.class
*.egg-info/
dist/
build/
```

### 评测产出（代码保留，运行结果忽略）

```gitignore
# 评测结果
eval_results/*.jsonl
eval_results/*.csv
!eval_results/.gitkeep

# 评测报告
reports/*.html
reports/*.pdf
!reports/.gitkeep

# Trace 文件
traces/*.jsonl
!traces/.gitkeep
```

### Python 项目标准

```gitignore
# 虚拟环境
venv/
.venv/
env/
.env/

# Jupyter
.ipynb_checkpoints/
*.ipynb  # 如果希望提交 notebook，移除此行

# Pytest
.pytest_cache/
htmlcov/
.coverage
coverage.xml
```

---

## 2. 不允许提交的内容

以下内容**绝对禁止**进入 Git 仓库。如果已经误提交，需立即用 `git rm --cached` 移除并更新 `.gitignore`。

| 类别 | 具体内容 | 原因 |
|------|----------|------|
| **原始文档** | PDF、DOCX、HTML 采集文件 | 体积大（单文件可达 100 MB），不可 diff，含版权内容 |
| **切分产物** | `chunks/*.jsonl` | 由原始文档自动生成，不需要版本管理 |
| **向量数据库** | `storage/` 目录下所有文件 | 二进制格式，体积大，可重建 |
| **模型权重** | `models/` 下所有文件 | 体积极大（GB 级），应通过 HuggingFace 下载 |
| **打包文件** | `*.zip`、`*.tar.gz` | 不应在仓库内传递文件 |
| **环境变量** | `.env`（含真实 API Key） | 安全风险 |
| **凭证** | SSH Key、API Key 文件 | 安全风险 |
| **IDE 配置** | `.vscode/`、`.idea/` | 个人偏好，不具项目通用性 |
| **评测结果** | `eval_results/*.jsonl`、`*.csv` | 体积大，且可能泄露知识库内容 |
| **评测报告** | PDF/HTML 报告 | 体积大，应由 CI 产出 |

### 如果已经误提交

```bash
# 从 Git 跟踪中移除，但保留本地文件
git rm --cached -r raw_sources/
git rm --cached -r storage/
git rm --cached -r models/
git rm --cached *.zip

# 更新 .gitignore 后提交
git add .gitignore
git commit -m "chore: 清理误提交的大文件/敏感数据，更新 .gitignore"
```

对于已经进入 Git 历史的敏感数据（如 API Key），必须使用 `git filter-branch` 或 `BFG Repo-Cleaner` 清理整个历史，并轮换泄露的密钥。

---

## 3. 允许提交的内容

以下内容**可以且应该**纳入版本管理。

| 类别 | 具体内容 | 提交条件 |
|------|----------|----------|
| **源代码** | `src/` 下所有 Python 文件 | 通过 `ruff check` 和 `mypy` |
| **配置文件模板** | `.env.example`、`settings.yaml.template` | 不含真实密钥，含注释说明每个配置项 |
| **source_registry** | `source_registry.yaml` | 经过人工审核确认字段完整 |
| **文档** | `docs/` 下所有 `.md` 文件 | 内容准确且经过审核 |
| **评测代码** | `scripts/enterprise_kb_v1/eval_*.py` | 可复现，输出路径用环境变量 |
| **评测数据** | `data/eval_cases/*.json` | 不含敏感信息（短 preview 可接受） |
| **测试代码** | `tests/` 下所有文件 | 全部通过 `pytest` |
| **CI 配置** | `.github/workflows/*.yml` 等 | 不含硬编码密钥 |
| **项目配置** | `pyproject.toml`、`CLAUDE.md` | 与代码一同维护 |

### 提交前检查清单

- [ ] 所有新增文件都在正确的目录下
- [ ] 不包含硬编码的绝对路径（如 `E:/RAG/...`）
- [ ] 不包含真实 API Key 或个人凭证
- [ ] 代码通过 `ruff check src/` 无错误
- [ ] 如果是评测脚本，确保可以在 HPC 上直接运行
- [ ] 如果是文档，确保内容准确且无过期信息

---

## 4. 大文件管理策略

### 定义

任何**超过 10 MB** 的文件视为大文件，需要特殊处理。

### 策略分级

| 文件大小 | 处理方式 |
|----------|----------|
| < 1 MB | 正常提交（代码、配置、小文档） |
| 1-10 MB | 评估是否可以拆分或压缩后提交 |
| 10-100 MB | 禁止提交，存储到 `A/` 目录并记录清单 |
| > 100 MB | 禁止提交（GitHub 硬限制），存储到 `A/` 目录 |

### 大文件存储位置

```
E:\RAG\A\
├── raw_sources/         # 原始采集文档（不入 Git）
├── model_weights/       # 模型权重备份（不入 Git）
├── hpc_packages/        # HPC 运行包（不入 Git）
├── reports/             # 评测报告（不入 Git）
└── data_archive/        # 历史数据归档（不入 Git）
```

### Git LFS 评估

当前项目**不使用 Git LFS**，原因：
1. 项目文件体积总体可控（代码 < 10 MB，评测数据 < 5 MB）
2. GitHub LFS 有存储和带宽配额限制
3. 大文件使用 `A/` 目录 + HPC 存储双副本策略已足够

如果未来需要版本管理大型二进制文件，再评估 Git LFS。

---

## 5. Phase 归档约定

### 目录结构

```
agent-service-toolkit-clean/
├── docs/
│   └── enterprise_kb_v1/
│       ├── phase_0_setup.md
│       ├── phase_4A_corpus.md
│       ├── phase_4B_index.md
│       ├── phase_4C_eval.md
│       ├── phase_4D_multi_hop.md
│       ├── phase_4E_trace_citation.md
│       ├── phase_4F_internal_docs.md
│       ├── phase_4G_hpc_eval.md
│       ├── phase_4H_production.md
│       ├── failure_patterns.md
│       ├── hpc_evaluation_lessons.md
│       ├── retrieval_debug_cases.md
│       └── repo_hygiene_policy.md
```

### 每个 Phase 必须产出的文档

| 文档类型 | 必需性 | 内容要求 |
|----------|--------|----------|
| Phase 规划 (plan) | 必需 | 目标、范围、产出物、验收标准 |
| Phase 执行记录 (log) | 必需 | 关键操作步骤、遇到的问题、解决方式 |
| Phase 产出报告 (report) | 按需 | 数据指标、分析结论、后续建议 |

### 命名规范

```
phase_{编号}_{简短描述}_{类型}.md

示例:
phase_4C_eval_plan.md
phase_4C_eval_report.md
phase_4F_internal_docs_log.md
```

---

## 6. 输出包到 A/ 目录

### A/ 目录用途

`E:\RAG\A\` 是项目的**输出/归档目录**，不参与运行、不纳入 Git。

### A/ 目录结构

```
E:\RAG\A\
├── hpc_packages/             # 上传到 HPC 的打包文件
│   └── hpc_eval_YYYYMMDD.tar.gz
├── eval_results/             # 从 HPC 拉回的评测结果
│   ├── retrieval_eval_bge_m3.jsonl
│   ├── retrieval_eval_qwen3.jsonl
│   └── ab_comparison.csv
├── reports/                  # 生成的报告
│   └── phase_4C_eval_report.pdf
├── raw_sources_backup/       # 原始采集文档备份
├── data_archive/             # 历史数据归档
└── README.md                 # A/ 目录内容说明
```

### 操作约定

1. 本地产出（脚本、配置）→ 提交到 Git（如果符合允许范围）
2. HPC 运行包 → 打包到 `A/hpc_packages/`，上传后本地可删除
3. HPC 结果 → 拉回到 `A/eval_results/`，分析后可删除原始文件（保留分析报告）
4. 评测报告 → 生成到 `A/reports/`，PDF/HTML 不提交 Git，关键结论写入 Phase 文档
5. 临时文件 → 放到 `A/tmp/`，定期清理

---

## 7. Chroma 持久化数据的生命周期

### 数据位置

- **本地**：`E:\RAG\agent-service-toolkit-clean\storage\chroma_enterprise_kb_v1\`（仅用于 smoke test）
- **HPC**：`~/jupyterlab/RAG/agent-service-toolkit-clean/storage/chroma_enterprise_kb_v1\`（主数据）

### 生命周期阶段

| 阶段 | 操作 | 触发条件 |
|------|------|----------|
| **创建** | `collection = client.create_collection(...)` + `collection.add(docs)` | 首次构建语料库 |
| **增量更新** | `collection.add(new_docs)` | 新增 source 或更新现有 source |
| **全量重建** | 删除 collection + 重新创建 | 切换 embedding 模型、修改切分策略、Chroma 大版本升级 |
| **备份** | 复制整个 `persist_dir` 目录 | 大版本更改前、重大评测前 |
| **清理** | 删除 `persist_dir` 目录 | 确认数据不再需要或需要释放磁盘空间 |

### 重建触发条件

以下任一条件满足时，必须全量重建 Chroma collection：
1. 切换 embedding 模型（维度变化或语义空间变化）
2. 修改 chunk 切分参数（`chunk_size`、`chunk_overlap`）
3. 修改 metadata schema（新增/重命名/删除字段）
4. Chroma 大版本升级且数据不兼容
5. 发现数据损坏（SQLite 文件损坏、UUID 目录丢失）

### 重建流程

```bash
# 1. 备份当前数据
cp -r storage/chroma_enterprise_kb_v1 storage/chroma_enterprise_kb_v1.backup_YYYYMMDD

# 2. 删除旧数据
rm -rf storage/chroma_enterprise_kb_v1

# 3. 重新运行构建脚本
python scripts/enterprise_kb_v1/build_index.py

# 4. 验证
python scripts/enterprise_kb_v1/verify_index.py

# 5. 确认无误后删除备份（可选）
rm -rf storage/chroma_enterprise_kb_v1.backup_YYYYMMDD
```

### 本地 vs HPC 的 Chroma 数据

| 位置 | 用途 | 数据完整度 | 更新频率 |
|------|------|-----------|----------|
| 本地 | smoke test（单条验证） | 仅 10-20 条 chunk | 很少更新 |
| HPC | 正式评测 | 全部 chunk（1117+ 条） | 每次语料变更后重建 |

本地 Chroma 数据**不应**与 HPC 同步。本地只保留最小子集用于代码正确性验证。

---

## 8. 仓库健康检查命令

### 一键检查脚本

```bash
#!/bin/bash
# 仓库卫生一键检查，放在项目根目录运行

echo "=== 仓库卫生检查 ==="

# 1. 检查是否有大文件被跟踪
echo "1. 大文件检查 (>10MB):"
git ls-files -z | xargs -0 -I{} du -h "{}" 2>/dev/null | sort -rh | head -5

# 2. 检查是否误提交了忽略目录
echo "2. 忽略目录中的已跟踪文件:"
for dir in raw_sources chunks storage models; do
    tracked=$(git ls-files "$dir/" 2>/dev/null | wc -l)
    if [ "$tracked" -gt 0 ]; then
        echo "  警告: $dir/ 中有 $tracked 个文件被 Git 跟踪，应移除"
    fi
done

# 3. 检查 .env 是否提交
echo "3. 敏感文件检查:"
if git ls-files .env 2>/dev/null | grep -q .env; then
    echo "  严重: .env 被 Git 跟踪! 立即移除并轮换密钥!"
else
    echo "  .env 未被跟踪 --- 正常"
fi

# 4. 检查 .gitignore 中是否包含所有关键规则
echo "4. .gitignore 覆盖检查:"
for pattern in "raw_sources/" "chunks/" "storage/" "models/" "*.zip" ".env"; do
    if grep -qF "$pattern" .gitignore 2>/dev/null; then
        echo "  $pattern --- 已覆盖"
    else
        echo "  $pattern --- 缺失!"
    fi
done

echo "=== 检查完成 ==="
```

### 定期执行

- **每次提交前**：运行 `git status` 确认没有误加入的大文件
- **每个 Phase 结束时**：运行完整检查脚本
- **PR Review 时**：检查 diff 中是否有不该提交的文件
