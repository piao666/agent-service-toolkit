# Phase 4D: Adopt bge-m3 as Default Embedding

> 版本: v1 | 时间: 2026-07-05 | 状态: **adopted** (HPC verified)

---

## Decision

| Model | Role |
|-------|------|
| **bge-m3** | **default_embedding** (adopted) |
| qwen3-embedding-0.6b | high_precision_candidate (retained) |
| bge-small-zh-v1.5 | lightweight_fallback (retained) |
| bge-reranker-base | deferred (not enabled) |
| Qwen3-Reranker-0.6B | deferred (not enabled) |

## Rationale

Based on Phase 4C HPC A/B results (NVIDIA L40):

| Model | dim | k=5 | k=10 | GPU |
|-------|:---:|:---:|:----:|:---:|
| bge-m3 | 1024 | **0.9091** | **0.9545** | 2.99GB |
| qwen3-embedding-0.6b | 1024 | **0.9091** | **0.9545** | 5.57GB |
| multilingual-e5-base | 768 | 0.8636 | 0.9545 | 3.47GB |
| bge-small-zh-v1.5 | 512 | 0.8182 | 0.9091 | 0.47GB |

bge-m3 selected over qwen3 due to:
- Identical accuracy (k=5=0.9091, k=10=0.9545)
- Half the GPU memory (2.99GB vs 5.57GB)
- Better suited for L40 11GB environment

---

## Production Index (Phase 4D HPC)

| Parameter | Value |
|-----------|-------|
| Collection | `enterprise_kb_v1_official_docs_bge_m3` |
| Persist dir | `storage/chroma_enterprise_kb_v1_bge_m3` |
| Model | bge-m3 (dim=1024) |
| Indexed chunks | **1117** |
| Build time | 19.0s (GPU) |

## Phase 4D Retrieval Eval (k=3)

- hit_rate: **0.9545** (21/22)
- MRR@3: **0.8409**
- core_001 multi-label fix verified: hit@3=True (rank=1)

## Reranker

NOT enabled. Deferred to next phase. bge-reranker-base and Qwen3-Reranker-0.6B recorded as candidates.

## Production Status

- **NOT in production answer pipeline** — evaluation phase only
- enabled=false, allowed_for_answer=false
