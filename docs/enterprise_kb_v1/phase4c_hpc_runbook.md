# Phase 4C HPC Runbook

> 版本: v1 | 适用: HPC JupyterLab Terminal

---

## 1. 目录映射

| 本地 | HPC |
|------|-----|
| `E:\RAG\A` | `~/RAG/A` |
| `E:\RAG\agent-service-toolkit-clean` | `~/RAG/agent-service-toolkit-clean` |

- `~/RAG/A`: 本地/HPC 互传目录（审查包、结果 ZIP）
- `~/RAG/agent-service-toolkit-clean`: 完整项目源码目录

---

## 2. 初始化 HPC 目录

```bash
mkdir -p ~/RAG/A
mkdir -p ~/RAG/agent-service-toolkit-clean
mkdir -p ~/RAG/agent-service-toolkit-clean/{data,scripts,docs,storage,logs,hpc_results}
```

## 3. 上传项目源码

1. 从本地下载 `enterprise_kb_v1_project_source_for_hpc.zip`
2. 通过 JupyterLab 上传到 `~/RAG/A/`
3. 解压：
```bash
cd ~/RAG/agent-service-toolkit-clean
unzip -o ~/RAG/A/enterprise_kb_v1_project_source_for_hpc.zip
```

## 4. 验证关键文件

```bash
ls ~/RAG/agent-service-toolkit-clean/data/enterprise_kb_v1/source_registry/source_registry.yaml
ls ~/RAG/agent-service-toolkit-clean/data/enterprise_kb_v1/source_registry/official_docs_allowlist.yaml
ls ~/RAG/agent-service-toolkit-clean/scripts/enterprise_kb_v1/hpc_phase4c_*.py
```

## 5. GPU 检测

```bash
nvidia-smi
python -c "import torch; print(torch.cuda.is_available()); print(torch.cuda.get_device_name(0))"
```

如果 `cuda_available=False`，立即停止，不在 CPU 上跑。

## 6. 运行 Preflight

```bash
cd ~/RAG/agent-service-toolkit-clean
python scripts/enterprise_kb_v1/hpc_phase4c_preflight.py
```

检查输出: `~/RAG/A/phase4c_hpc_env_preflight.json`

## 7. 运行 Embedding A/B

```bash
cd ~/RAG/agent-service-toolkit-clean
python scripts/enterprise_kb_v1/hpc_phase4c_run_embedding_ab.py
```

结果: `~/RAG/A/phase4c_hpc_results/phase4c_hpc_embedding_ab_results.json`

## 8. 运行 RAG Answer Eval

```bash
cd ~/RAG/agent-service-toolkit-clean
python scripts/enterprise_kb_v1/hpc_phase4c_run_retrieval_context_eval.py
```

## 9. 打包结果

```bash
cd ~/RAG/agent-service-toolkit-clean
python scripts/enterprise_kb_v1/hpc_phase4c_collect_results.py
```

输出: `~/RAG/A/enterprise_kb_v1_phase4c_hpc_results.zip`

## 10. 下载回本地

通过 JupyterLab 下载 `~/RAG/A/enterprise_kb_v1_phase4c_hpc_results.zip` 到本地 `E:\RAG\A\`。
