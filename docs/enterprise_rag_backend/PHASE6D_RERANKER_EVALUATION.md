# Phase 6D-4 Reranker Evaluation

## Goal

Phase 6D-4 builds an offline reranker evaluation framework on top of the Phase 6D-3 dense, sparse, and hybrid candidate pool. The goal is to measure whether a cross-encoder reranker can improve candidate ordering before any production integration.

This is an offline reranker evaluation.
It is not wired into production Agent/API routing.
No production Chroma collection is written.
No generative LLM is called.
Reranker results depend on candidate pool quality.
This phase does not complete production reranking.
HPC full benchmark is planned separately and is not claimed in this local run.

## Why Reranker Is Needed

Dense retrieval, BM25, and hybrid fusion can find useful candidates, but top-1 ranking can still be unstable. A reranker can compare the query with each candidate passage more directly and may improve ordering when the candidate pool already contains the expected source.

The reranker should not be blamed when the candidate pool misses the expected source. For that reason this phase separately records `candidate_pool_source_hit_at_k`, `reranker_possible_improvement_count`, `reranker_improved_count`, `reranker_degraded_count`, and `reranker_unchanged_count`.

## Reviewed Chunk Scope

The evaluation uses reviewed sample chunks only:

- `ingest_candidate=true`
- `review_status=approved`
- `normalization_status=pass`
- banned, filtered, rejected, and navigation-heavy sources excluded

The local full run recovered 575 reviewed chunks. It used an in-memory index and did not write Chroma.

## Case Design

The reranker cases are derived from the Phase 6D-3 hybrid retrieval cases and are written to `data/knowledge_base/evaluation/phase6d_reranker_cases.jsonl`.

| Query type | Count |
| --- | ---: |
| `zh_knowledge` | 8 |
| `en_api_doc` | 8 |
| `mixed_zh_en_api` | 8 |
| `agent_rag_concept` | 8 |
| `exact_metadata_lookup` | 8 |
| `code_api_config` | 8 |
| `short_keyword` | 8 |
| `negative_banned_source` | 8 |
| `phase6c_bad_case_regression` | 8 |

The focus cases are exact metadata lookup, code/API/config, short keyword, and Phase 6C bad-case regression queries.

## Candidate Pool Design

For each query, the script first builds a candidate pool from:

- `dense_only_top20`
- `sparse_bm25_top20`
- `hybrid_weighted_top20`

The pool is merged, de-duplicated, ordered by the hybrid weighted score, and capped by `candidate_pool_size=20` in the local full run. The before-rerank ranking is the hybrid-weighted candidate order. The after-rerank ranking is produced by the cross-encoder scores.

## Local Model Load Status

| Reranker alias | Mode | Load success | Notes |
| --- | --- | --- | --- |
| `bge-reranker-base` | load-only, smoke, local full eval | true | Used for final local result files. |
| `qwen3-reranker-0.6b` | load-only | true | Loaded locally, but rerank smoke/full was not run to avoid CPU-heavy repeated scoring. |

Model paths are recorded only as aliases:

- `<LOCAL_RERANKER_MODEL_ROOT>/bge-reranker-base`
- `<LOCAL_RERANKER_MODEL_ROOT>/Qwen3-Reranker_0.6B`
- `<LOCAL_EMBEDDING_MODEL_ROOT>/bge-small-zh-v1.5`

## Local Full Evaluation Settings

- reranker alias: `bge-reranker-base`
- dense model alias: `bge-small-zh-v1.5`
- cases: 72
- reviewed chunks: 575
- candidate pool size: 20
- top-k: 5
- batch size: 4
- device: `cpu`

## Before/After Metrics

| Metric | Before rerank | After rerank | Delta |
| --- | ---: | ---: | ---: |
| Source hit@5 | 0.7812 | 0.7969 | +0.0157 |
| Top1 source hit | 0.7188 | 0.6719 | -0.0469 |
| MRR source | 0.7474 | 0.7227 | -0.0247 |
| Keyword hit@5 | 0.8906 | 0.8906 | 0.0 |
| Exact match hit@5 | 0.625 | 0.625 | 0.0 |
| Code/API source hit@5 | 0.75 | 0.75 | 0.0 |
| Banned source result count | 0 | 0 | 0 |

Candidate pool source hit@5 is 0.8438. This means the candidate pool often contains the expected source, but the local bge reranker did not consistently move it upward.

## Query-Type Notes

| Query type | Source hit delta | Top1 delta | MRR delta | Interpretation |
| --- | ---: | ---: | ---: | --- |
| `exact_metadata_lookup` | -0.125 | -0.25 | -0.2083 | Reranker degraded exact metadata ordering in this local run. |
| `code_api_config` | 0.0 | -0.125 | -0.0417 | Reranker kept hit rate but worsened ordering. |
| `short_keyword` | 0.0 | 0.0 | -0.0208 | Reranker did not improve short keyword ranking. |
| `phase6c_bad_case_regression` | +0.25 | +0.125 | +0.1562 | Reranker helped part of the bad-case regression set. |

Overall effect counts:

- improved: 4
- degraded: 6
- unchanged: 62

The result is mixed and should not be treated as a production reranking strategy.

## Latency Cost

Average rerank latency in the local full run is 6159.4565 ms per query for a candidate pool of 20 on CPU. This is too expensive for direct request-path use without batching, GPU verification, smaller candidate pools, caching, or timeout controls.

## Current Limits

This phase uses a reviewed sample corpus, not a full production corpus. The local full run uses one reranker model and one dense baseline. The qwen3 reranker was load-tested only. The candidate pool and scoring weights remain experimental. The run does not evaluate answer quality and does not call any generative model.

The result shows that reranker evaluation is necessary, but it does not justify production reranking yet.

## Production Boundary

This phase does not modify production Agent code, API behavior, Agent registry, service routes, or Chroma collections. It does not call a business system and does not call a generative LLM.

The prototype results should be reviewed manually before any future runtime integration is considered.

## HPC Full Benchmark Verification Plan

HPC full benchmark is planned but not executed in this local run. Use placeholders only:

```text
Project repo:
<HPC_WORKDIR>/agent-service-toolkit

Data cache:
<HPC_WORKDIR>/agent-service-toolkit/data/knowledge_base/manifests
<HPC_WORKDIR>/agent-service-toolkit/data/knowledge_base/normalized
<HPC_WORKDIR>/agent-service-toolkit/data/knowledge_base/chunks
<HPC_WORKDIR>/agent-service-toolkit/data/knowledge_base/evaluation

Models:
<HPC_MODEL_ROOT>/bge-small-zh-v1.5
<HPC_MODEL_ROOT>/bge-reranker-base
<HPC_MODEL_ROOT>/Qwen3-Reranker_0.6B
```

If embedding full verification is repeated, the model root may also include:

```text
<HPC_MODEL_ROOT>/bge-m3
<HPC_MODEL_ROOT>/multilingual-e5-base
<HPC_MODEL_ROOT>/qwen3-embedding-0.6b
```

Planned HPC constraints:

- 64-core CPU, single L40 GPU, available VRAM around 11GB, and 24GB RAM.
- 11GB VRAM is suitable for sequential single-model reranker full benchmark with conservative batch size.
- It is not suitable for loading several large models in parallel.
- `bge-reranker-base` should be the first full benchmark target.
- `qwen3-reranker-0.6b` should use a controlled benchmark with smaller batch size.
- If out-of-memory or process termination occurs, record `skipped_due_to_vram_limit` instead of reporting success.

Suggested HPC parameters:

| Reranker alias | Batch size | Candidate pool size | Top-k |
| --- | ---: | ---: | ---: |
| `bge-reranker-base` | 8 or 16 | 20 | 5 |
| `qwen3-reranker-0.6b` | 1 or 2 | 10 or 20 | 5 |

## Handoff To Phase 6D-5

Phase 6D-5 should evaluate chunking strategy ablation before any production reranker integration. The current reranker result depends strongly on candidate quality and chunk boundaries. Better chunking may improve candidate pool quality and reranker behavior, especially for exact metadata, code/API/config, and short keyword cases.

This phase does not complete chunking ablation, final retrieval optimization, Phase 6E, Phase 6F, or Phase 7.
