# Phase 6D-3 Hybrid Retrieval Prototype

## Goal

Phase 6D-3 implements an offline hybrid retrieval prototype over the same reviewed sample chunks used by earlier Phase 6 work. It compares dense-only retrieval, sparse BM25, exact match, reciprocal-rank fusion, and weighted hybrid fusion.

This is an offline hybrid retrieval prototype.
It is not wired into production Agent/API routing.
No production Chroma collection is written.
No generative LLM is called.
Hybrid weights are initial experimental values, not tuned production parameters.

## Why Dense-Only Is Not Enough

Dense retrieval is useful for semantic questions, but it can be weak for exact fields, short keywords, API names, config keys, ids, and metadata filters. Phase 6D-2 showed that exact metadata and code/API/config cases still need more than vector similarity. Phase 6D-3 therefore tests sparse and exact signals before any production routing change.

## Reviewed Chunk Scope

The prototype uses only reviewed sample chunks:

- `ingest_candidate=true`
- `review_status=approved`
- `normalization_status=pass`
- banned, filtered, rejected, and navigation-heavy sources excluded

The full bge-small run recovered 575 reviewed chunks. It used an in-memory index and did not write Chroma.

## Case Design

The evaluation uses 72 cases, with 8 cases for each query type:

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

The case set emphasizes exact metadata lookup, code/API/config, and short keywords because those are the areas where sparse and exact retrieval should help.

## Retrieval Methods

`dense_only` uses local embeddings with in-memory cosine similarity. The full run used `bge-small-zh-v1.5` as the quick local baseline.

`sparse_bm25` uses a lightweight in-script BM25 implementation with rough Chinese and English tokenization. It preserves underscores, paths, config-like fields, ids, API names, and ordinary English terms.

`exact_match` scores exact occurrences in chunk metadata, title, section path, source id, doc type, normalized id, chunk id, and recovered chunk text.

`hybrid_rrf` uses reciprocal-rank fusion over dense, sparse, and exact scores with `k=60`.

`hybrid_weighted` uses the initial experimental formula:

```text

hybrid_score = 0.45 * dense_score + 0.30 * sparse_score + 0.20 * exact_match_score + 0.05 * metadata_match_score

```

These weights are not tuned production parameters.

## Overall Metrics

Full benchmark settings:

- model alias: `bge-small-zh-v1.5`
- cases: 72
- reviewed chunks: 575
- top-k: 5

| Strategy | Source hit@5 | Top1 source hit | MRR source | Doc type hit@5 | Keyword hit@5 | Exact hit@5 | Code/API hit@5 | Banned source count |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `dense_only` | 0.7969 | 0.6094 | 0.6867 | 0.7344 | 0.8281 | 0.5625 | 0.75 | 0 |
| `sparse_bm25` | 0.8438 | 0.75 | 0.781 | 0.7969 | 0.8906 | 0.625 | 0.875 | 0 |
| `exact_match` | 0.7188 | 0.6719 | 0.6849 | 0.6875 | 0.8281 | 0.5625 | 0.625 | 0 |
| `hybrid_rrf` | 0.7656 | 0.7188 | 0.7336 | 0.7188 | 0.8594 | 0.625 | 0.75 | 0 |
| `hybrid_weighted` | 0.7812 | 0.7188 | 0.7474 | 0.7344 | 0.8906 | 0.625 | 0.75 | 0 |

In this run, `sparse_bm25` is strongest overall. The two hybrid variants improve top1 and MRR over dense-only, but their current initial fusion settings do not beat BM25 on overall source hit.

## Query-Type Comparison

| Query type | Best strategy by source hit@5 | Notes |
| --- | --- | --- |
| `exact_metadata_lookup` | `sparse_bm25` | Dense-only reached 0.375; sparse, exact, RRF, and weighted reached 0.5. |
| `code_api_config` | `sparse_bm25` | Dense-only reached 0.75; sparse reached 0.875. |
| `short_keyword` | `sparse_bm25` | Dense-only reached 0.875; sparse, exact, RRF, and weighted reached 1.0. |
| `negative_banned_source` | all strategies passed | Banned source result count remained 0. |

The prototype confirms that lexical signals are valuable for exact metadata, code/API/config, and short keyword queries.

## Dense-Only Gaps

Dense-only remains strong for semantic knowledge queries, but it underperforms on exact metadata lookup. It can also rank correct sources lower for short identifiers and config-like terms. This supports adding a non-dense signal before considering production integration.

## Hybrid Benefits And Costs

Hybrid retrieval improves top1 source hit and MRR compared with dense-only:

- `hybrid_rrf`: top1 +0.1094, MRR +0.0469
- `hybrid_weighted`: top1 +0.1094, MRR +0.0607

Both hybrid variants also improve exact metadata and short keyword source hit by +0.125. However, the initial weights slightly reduce overall source hit compared with dense-only in this sample run. This indicates that the fusion design needs tuning and better query-intent-aware weighting.

## Current Limits

This is a prototype over reviewed sample chunks, not a production retrieval strategy. It uses simple BM25 tokenization and handcrafted exact-match scoring. The weighted fusion coefficients are initial values, not tuned parameters. The run uses the fast baseline embedding model, not a full qwen3 benchmark.

The qwen3 smoke test was not run in this pass to avoid overwriting the full bge-small results and to avoid repeated large-model local indexing. Qwen3 can be used later for a small controlled comparison with explicit output paths.

## Production Boundary

This phase does not modify production Agent code, API behavior, Agent registry, service routes, or Chroma collections. It does not call a business system and does not call a generative LLM.

The prototype results should be reviewed manually before any future runtime integration is considered.

## Next Phases

Phase 6D-4 can evaluate reranking over dense, sparse, and hybrid candidate pools. Reranking should focus on cases where source hit exists but top1 or MRR is still weak.

Phase 6D-5 can evaluate whether chunking changes improve exact metadata, code/API/config, and short keyword retrieval without hurting semantic knowledge queries.

This phase does not complete Reranker, Chunking Ablation, or final enterprise retrieval optimization.
