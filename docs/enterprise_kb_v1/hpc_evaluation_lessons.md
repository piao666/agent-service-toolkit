# HPC 评测经验教训

本文档记录在企业知识库 RAG 项目中使用 HPC（高性能计算）环境进行 embedding 评测的经验教训，涵盖连接配置、硬件规格、环境管理、评测流程和最佳实践。

---

## 1. HPC 连接配置

### SSH 连接参数

| 参数 | 值 |
|------|-----|
| **地址** | `172.18.101.241` |
| **端口** | `22371` |
| **域名** | `hpc.cuc.edu.cn` |
| **用户名** | `u202520081000097` |
| **SSH Key** | `C:/Users/34904/.ssh/id_ed25519` |

### 连接命令

```bash
# SSH 登录
ssh -i "C:/Users/34904/.ssh/id_ed25519" u202520081000097@172.18.101.241 -p 22371

# SCP 上传文件
scp -i "C:/Users/34904/.ssh/id_ed25519" -P 22371 <local_file> u202520081000097@172.18.101.241:~/jupyterlab/RAG/A/

# SCP 拉回结果
scp -i "C:/Users/34904/.ssh/id_ed25519" -P 22371 u202520081000097@172.18.101.241:~/jupyterlab/RAG/A/<result_file> E:/RAG/A/
```

### 经验教训

- **SSH Key 权限**：Windows 下 OpenSSH 对私钥权限敏感，若连接失败先检查 `icacls` 权限（仅当前用户可读）
- **端口非标准**：22371 不是标准 SSH 端口，所有工具调用都要显式指定 `-P 22371`（SCP 大写 P，SSH 小写 p）
- **连接稳定性**：HPC 有空闲断开策略，长任务必须使用 `nohup` 或 `tmux`/`screen` 保持会话
- **免密登录**：配置 SSH Key 后无需每次输入密码，但首次连接需确认 host key

---

## 2. L40 GPU 硬件规格

### GPU 详情

| 属性 | 值 |
|------|-----|
| **型号** | NVIDIA L40 |
| **显存 (VRAM)** | 11 GB |
| **CUDA 版本** | 12.4 |
| **驱动版本** | 550.x |

### 对 embedding 任务的影响

- **11 GB VRAM** 足以加载大多数 sentence-transformers 模型（bge-m3 约 2.2 GB，qwen3-embedding-0.6b 约 1.2 GB）
- **batch size 上限**：bge-m3 在 max_seq_len=8192 时，batch_size=32 约占用 8-9 GB VRAM；batch_size=64 约 10-11 GB（接近上限，有 OOM 风险）
- **不支持 FP16 推理加速**：sentence-transformers 默认 FP32，bge-m3 在 L40 上编码 1117 条 chunk（约 800 token/chunk）耗时约 2-4 分钟
- **多模型并行不可行**：11 GB 不足以同时加载 2 个 embedding 模型做并行评测，必须串行

### 经验教训

- **batch_size 不要设满**：留 1-2 GB 余量给 PyTorch 内部缓存和 CUDA context
- **OOM 后的恢复**：GPU OOM 后必须重启 Python 进程释放显存，仅 `torch.cuda.empty_cache()` 不够
- **监控显存**：每个 encoding 任务前用 `nvidia-smi` 确认空闲显存 >= 模型大小 + 2 GB

---

## 3. CPU 与 内存规格

| 属性 | 值 |
|------|-----|
| **CPU** | AMD EPYC 9354, 64 核 |
| **RAM** | 24 GB |
| **Python 版本** | 3.10.8 |
| **PyTorch** | 2.6.0+cu124 |

### 经验教训

- **24 GB RAM 是瓶颈**：加载 1117 条 chunk 的全文（每条约 1-2 KB）仅占用几十 MB，但 Chroma 索引构建过程中的临时数据结构可能占用数 GB。大语料需分批处理
- **64 核 CPU**：对 embedding 任务帮助有限（GPU 做编码，CPU 只做数据预处理），但 Chroma 索引构建和检索评测可使用多进程加速
- **Python 3.10**：部分新库需要 `from __future__ import annotations`，注意兼容性

---

## 4. Python 环境隔离

### Conda 环境

```bash
# 激活环境
/opt/conda/envs/py310/bin/python --version
# 输出: Python 3.10.8

# 运行脚本的标准方式
cd ~/jupyterlab/RAG/agent-service-toolkit-clean
/opt/conda/envs/py310/bin/python scripts/enterprise_kb_v1/<script>.py
```

### 关键依赖版本

| 包 | 版本 | 备注 |
|----|------|------|
| `torch` | 2.6.0+cu124 | CUDA 12.4 支持 |
| `sentence-transformers` | 3.x | embedding 模型加载 |
| `chromadb` | 0.5.x | 向量存储 |
| `transformers` | 4.x | HuggingFace 模型后端 |

### 经验教训

- **不要用系统 Python**：`/usr/bin/python` 缺少 torch、transformers 等关键包
- **不要随意 `pip install`**：conda 环境中 pip 安装可能导致依赖冲突，优先用 `conda install`
- **PyTorch CUDA 版本**：`cu124` 表示 CUDA 12.4，与 HPC 的驱动版本匹配。如果本地和 HPC 的 CUDA 版本不一致，`torch` 需要分别安装对应版本
- **移植性**：本地 Windows 和 HPC Linux 的 `sentence-transformers` 模型输出可能因浮点精度有微小差异（<1e-5），不影响评测结论

---

## 5. 模型路径约定

### 标准路径

```
~/jupyterlab/models/
├── bge-small-zh-v1.5/       # 本地 smoke test 用（已经部署到本地）
├── bge-m3/                  # 最终选定的默认 embedding 模型
├── qwen3-embedding-0.6b/   # A/B 评测对比模型
├── multilingual-e5-base/    # 备选多语言模型
├── bge-reranker-base/       # Reranker（仅记录，未用于评测）
└── Qwen3-Reranker_0.6B/    # Reranker（仅记录，未用于评测）
```

### 模型加载代码示例

```python
from sentence_transformers import SentenceTransformer
import os

model_root = os.path.expanduser("~/jupyterlab/models")
model = SentenceTransformer(os.path.join(model_root, "bge-m3"), device="cuda")
```

### 经验教训

- **统一模型根目录**：避免每个脚本各自硬编码模型路径，使用环境变量 `ENTERPRISE_MODEL_ROOT` 或配置文件集中管理
- **模型下载**：HPC 可能无外网访问能力（或需代理），模型权重需通过本地下载后 SCP 上传
- **模型命名**：目录名保持与 HuggingFace model card 一致，避免自定义别名造成混淆

---

## 6. Embedding A/B 评测流程

### 标准流程（6 步）

```
1. 本地准备脚本和评测数据 → 打包
2. SCP 上传到 HPC: ~/jupyterlab/RAG/A/
3. HPC 解压并运行评测脚本
4. 监控 GPU 使用率和任务进度
5. 结果打包并 SCP 拉回到本地: E:/RAG/A/
6. 本地分析评测结果，决策模型选择
```

### 具体步骤

```bash
# 步骤 1-2: 本地打包上传
cd E:/RAG/agent-service-toolkit-clean
tar -czf E:/RAG/A/hpc_eval_package.tar.gz scripts/enterprise_kb_v1/eval_embedding_ab.py data/
scp -i "C:/Users/34904/.ssh/id_ed25519" -P 22371 E:/RAG/A/hpc_eval_package.tar.gz u202520081000097@172.18.101.241:~/jupyterlab/RAG/A/

# 步骤 3: HPC 运行（通过 SSH 或 tmux 会话）
ssh -i "C:/Users/34904/.ssh/id_ed25519" u202520081000097@172.18.101.241 -p 22371
cd ~/jupyterlab/RAG/A/
tar -xzf hpc_eval_package.tar.gz
nohup /opt/conda/envs/py310/bin/python scripts/enterprise_kb_v1/eval_embedding_ab.py > eval_output.log 2>&1 &

# 步骤 4: GPU 监控
watch -n 1 nvidia-smi

# 步骤 5: 结果拉回（本地执行）
scp -i "C:/Users/34904/.ssh/id_ed25519" -P 22371 u202520081000097@172.18.101.241:~/jupyterlab/RAG/A/eval_results/* E:/RAG/A/eval_results/

# 步骤 6: 本地分析
python scripts/enterprise_kb_v1/analyze_ab_results.py --input E:/RAG/A/eval_results/
```

### A/B 评测输出格式

每个 model 输出一个 JSONL 文件，每行一个 case：

```json
{
  "case_id": "core_001",
  "query": "如何在 Chroma 中创建 collection？",
  "expected_source_ids": ["chroma_guide"],
  "retrieved_source_ids": ["chroma_guide", "langchain_docs", "chroma_api"],
  "retrieved_scores": [0.92, 0.78, 0.65],
  "hit": true,
  "reciprocal_rank": 1.0,
  "model_name": "bge-m3",
  "headings": ["Chroma > Getting Started > Create Collection"],
  "text_previews": ["To create a collection in Chroma, use the..."]
}
```

### 评判指标

| 指标 | 计算方式 | 期望阈值 |
|------|----------|----------|
| `hit_rate` | `hit=true 的 case 数 / 总 case 数` | >= 0.80 |
| `MRR` | `mean(1 / rank_of_first_hit)` | >= 0.70 |
| `avg_rank` | `mean(first_hit_rank)` | <= 3.0 |
| `p95_rank` | 95th percentile of first_hit_rank | <= 5 |

### 经验教训

- **评测脚本必须幂等**：同一个模型跑两次结果应该完全一致（固定随机种子）
- **每轮评测后清理 Chroma 数据**：避免上一轮数据残留影响下一轮
- **不要用 root 跑**：Chroma 的 SQLite 后端在 root 权限下可能有权限问题
- **长任务必须 nohup + 日志**：SSH 断开后任务被 kill 是最常见的 HPC 翻车场景

---

## 7. 本地与 HPC 协作 Workflow

### 明确分工

| 操作 | 本地 (Windows CPU) | HPC (Linux GPU) |
|------|-------------------|-----------------|
| 代码编写 | 全部 | 无需 |
| 语料准备 | 全部（文档解析、切分配置） | 无需 |
| Smoke test | 单条 encode 验证 | 无需 |
| Embedding 索引构建 | **禁止** | 全部 |
| Chroma collection 创建 | **禁止** | 全部 |
| 检索评测 (retrieval eval) | **禁止** | 全部 |
| 结果分析 | 全部（pandas 分析、可视化） | 无需 |
| 报告撰写 | 全部 | 无需 |

### 本地到 HPC 传输的文件类型

| 传输方向 | 文件类型 | 大小 |
|----------|----------|------|
| 本地 → HPC | Python 脚本 (`.py`) | < 100 KB |
| 本地 → HPC | 评测数据 (`.json`, `.yaml`) | < 1 MB |
| 本地 → HPC | 语料 chunk 文件 (`.jsonl`) | 1-10 MB |
| HPC → 本地 | 评测结果 (`.jsonl`) | 1-5 MB |
| HPC → 本地 | 日志文件 (`.log`) | < 1 MB |
| HPC → 本地 | Trace 文件 (`.jsonl`) | 1-5 MB |

### 经验教训

- **不要传输大文件**：模型权重（GB 级）一次性部署到 HPC 后不再移动，本地和 HPC 各保留独立副本
- **传输前压缩**：文本文件压缩率高（10:1），`tar.gz` 显著加速传输
- **传输后校验**：用 `md5sum` 验证文件完整性，避免传输中断导致的数据损坏
- **目录结构镜像**：保持本地和 HPC 的目录结构一致（`E:\RAG\A` 对应 `~/jupyterlab/RAG/A`），减少路径转换心智负担

---

## 8. GPU 显存跟踪与管理

### 监控命令

```bash
# 实时监控 (每秒刷新)
watch -n 1 nvidia-smi

# 单次查询
nvidia-smi --query-gpu=memory.used,memory.total,utilization.gpu --format=csv

# 查询进程占用
nvidia-smi --query-compute-apps=pid,used_memory --format=csv
```

### batch size 策略

| 模型 | 显存占用 | 推荐 batch_size | 编码 1117 chunks 耗时 |
|------|----------|-----------------|----------------------|
| bge-small-zh-v1.5 | ~0.5 GB | 64 | ~1 分钟 |
| bge-m3 | ~2.2 GB | 32 | ~3 分钟 |
| qwen3-embedding-0.6b | ~1.2 GB | 64 | ~2 分钟 |
| multilingual-e5-base | ~1.0 GB | 64 | ~2 分钟 |

### 经验教训

- **batch_size 优先选 2 的幂**：GPU 计算单元对 2 的幂大小的矩阵乘法有优化
- **batch_size 不是越大越好**：超过某个值后 GPU 利用率不再提高，反而增加显存压力
- **显存泄漏排查**：多次 encoding 后显存持续增长 → 检查是否有 tensor 未释放或 dataloader 未正确关闭
- **混合精度 (FP16)**：如果支持且精度损失可接受，FP16 可以减少约 40% 显存占用，但 sentence-transformers 默认不启用

---

## 9. bge-m3 最终选择理由

### 候选模型对比

| 维度 | bge-m3 | qwen3-embedding-0.6b | bge-small-zh-v1.5 | multilingual-e5-base |
|------|--------|---------------------|-------------------|----------------------|
| 参数量 | 567M | 600M | 24M | 278M |
| 向量维度 | 1024 | 1536 | 512 | 768 |
| 中文支持 | 优秀 | 良好 | 优秀 | 中等 |
| hit_rate (22 cases) | **0.86** | 0.82 | 0.73 | 0.77 |
| MRR (22 cases) | **0.79** | 0.77 | 0.65 | 0.70 |
| 显存占用 | 2.2 GB | 1.2 GB | 0.5 GB | 1.0 GB |
| 编码速度 | 基准 | 1.5x 快 | 3x 快 | 1.3x 快 |

### 选择理由

1. **中文检索质量最优**：`hit_rate=0.86`，`MRR=0.79`，均在 4 个模型中排第一。qwen3 虽然接近（MRR 仅差 0.02），但在 per-case 分析中 bge-m3 对中文技术术语的语义匹配更稳定
2. **向量维度适中**：1024 维比 qwen3 的 1536 维少 33%，Chroma 索引体积和检索延迟都更小
3. **社区生态成熟**：BGE 系列在中文 NLP 社区有广泛验证，文档和最佳实践丰富。Qwen3-Embedding 较新（2025 年发布），社区案例较少
4. **性价比**：显存占用 2.2 GB 在 L40 的 11 GB 内完全可接受，不会因为 batch size 限制影响吞吐。bge-small 虽然更快更小，但检索质量差距不可接受（hit_rate 低 0.13）
5. **多语言能力**：bge-m3 原生支持中英混合检索，适合本项目知识库中英文混排的特点

---

## 10. HPC 常见问题排查

| 问题 | 可能原因 | 解决方法 |
|------|----------|----------|
| SSH 连接被拒 | IP/端口错误或密钥未加载 | 检查 `~/.ssh/config`，确认端口 22371 |
| `nvidia-smi` 看不到 GPU | 驱动未加载或容器无 GPU 访问 | 联系 HPC 管理员挂载 GPU |
| `torch.cuda.is_available()` 返回 False | PyTorch 是 CPU 版本 | 重装 `torch` 的 CUDA 版本 |
| Chroma collection 创建失败 | 磁盘满或 SQLite 权限问题 | 检查 `~/jupyterlab/` 磁盘空间，不用 root |
| 脚本运行到一半被 kill | SSH 断开或 OOM killer | 用 `nohup` + `&` 或 `tmux`，监控 RAM 使用 |
| encoding 结果全为 0 向量 | 模型加载失败，fallback 到随机 | 检查模型路径是否存在，验证 `model.encode(["test"])` |
| GPU 利用率 0% 但脚本在跑 | 代码未将模型移到 GPU | 检查 `device="cuda"` 参数 |
