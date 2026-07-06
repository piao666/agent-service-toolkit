# Phase 6F HPC Run Commands

## 前置条件

- HPC GPU 节点 (NVIDIA L40)
- Python: `/opt/conda/envs/py310/bin/python` (3.10.8, torch 2.6.0+cu124)
- bge-m3 Chroma 索引:
  - official_docs: `storage/chroma_enterprise_kb_v1_bge_m3/`
  - internal_engineering_docs: `storage/chroma_enterprise_kb_v1_internal_bge_m3/`
- bge-m3 模型: `~/jupyterlab/models/bge-m3/`

## Step 1: 同步文件到 HPC

```powershell
# 本地 PowerShell 执行
cd E:\RAG\agent-service-toolkit-clean

# 上传 eval cases
scp -i "C:/Users/34904/.ssh/id_ed25519" -P 22371 `
  data/enterprise_kb_v1/eval/phase6f_multichannel_retrieval_cases.jsonl `
  u202520081000097@172.18.101.241:~/jupyterlab/RAG/agent-service-toolkit-clean/data/enterprise_kb_v1/eval/

# 上传 HPC eval 脚本
scp -i "C:/Users/34904/.ssh/id_ed25519" -P 22371 `
  scripts/enterprise_kb_v1/run_phase6f_multichannel_retrieval_eval.py `
  u202520081000097@172.18.101.241:~/jupyterlab/RAG/agent-service-toolkit-clean/scripts/enterprise_kb_v1/

# 如有更新的 search_channels / orchestrator，一并上传
scp -i "C:/Users/34904/.ssh/id_ed25519" -P 22371 -r `
  src/rag/search_channels `
  u202520081000097@172.18.101.241:~/jupyterlab/RAG/agent-service-toolkit-clean/src/rag/

scp -i "C:/Users/34904/.ssh/id_ed25519" -P 22371 `
  src/rag/retrieval_orchestrator.py `
  src/rag/postprocess.py `
  src/rag/official_docs_retriever.py `
  src/rag/internal_engineering_retriever.py `
  u202520081000097@172.18.101.241:~/jupyterlab/RAG/agent-service-toolkit-clean/src/rag/
```

## Step 2: SSH 登录 HPC 并运行

```bash
# 连接 HPC
ssh -i "C:/Users/34904/.ssh/id_ed25519" u202520081000097@172.18.101.241 -p 22371

# HPC 上执行
cd ~/jupyterlab/RAG/agent-service-toolkit-clean
PYTHONPATH=$PWD/src /opt/conda/envs/py310/bin/python \
  scripts/enterprise_kb_v1/run_phase6f_multichannel_retrieval_eval.py
```

## Step 3: 拉回结果

```powershell
# 本地 PowerShell
scp -i "C:/Users/34904/.ssh/id_ed25519" -P 22371 -r `
  u202520081000097@172.18.101.241:~/jupyterlab/RAG/A/phase6f_hpc_results `
  E:\RAG\A\

# 复制到项目 reports 目录
cp E:\RAG\A\phase6f_hpc_results\* E:\RAG\agent-service-toolkit-clean\reports\enterprise_kb_v1\
```

## 输出文件

| 文件 | 路径 |
|------|------|
| Eval results | `~/jupyterlab/RAG/A/phase6f_hpc_results/phase6f_multichannel_retrieval_eval_results.json` |
| Per-case results | `~/jupyterlab/RAG/A/phase6f_hpc_results/phase6f_per_case_results.jsonl` |
| Failure analysis | `~/jupyterlab/RAG/A/phase6f_hpc_results/phase6f_failure_analysis.md` |

## 预期指标 (参考)

基于 Phase 4D bge-m3 official_docs eval (22 cases) 和 Phase 4FH internal eval (30 cases):

| 指标 | Baseline (单路) | Multi-channel (预期) |
|------|:---:|:---:|
| hit@3 | ~0.90 | >= baseline (去重+融合减少冗余) |
| hit@5 | ~0.93 | >= baseline |
| MRR | ~0.82 | >= baseline |
| duplicate_rate | >0 | ~0 (chunk_id 去重) |
| route_accuracy | ~0.90 | ~1.0 (orchestrator 保证) |
| corpus_balance | N/A | dual 都有命中 |
| citation_validity | N/A | 1.0 |
