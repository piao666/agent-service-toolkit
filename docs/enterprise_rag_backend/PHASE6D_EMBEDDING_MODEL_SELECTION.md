# Phase 6D-2 Embedding Model Selection and Benchmark

## Goal

Phase 6D-2 compares local embedding model candidates on the same reviewed sample chunks and the same retrieval benchmark cases. The benchmark checks retrieval behavior, model load status, indexing time, query latency, and query-type-specific performance before later retrieval improvements are designed.

This benchmark uses reviewed sample chunks only.
This is not a production model switch.
No production Agent/API behavior is modified.
No production Chroma collection is written.
No generative LLM is called.
Model aliases are used in committed files; local absolute model paths are not committed.

## Why The Existing Baseline Is Not Enough

The existing baseline is useful for local development because it is relatively small and quick, but Phase 6C showed that retrieval quality still has gaps around exact metadata lookup, API/config queries, and bad-case regressions. Phase 6D-2 therefore compares multiple local embedding candidates before changing any production path.

## Candidate Models

| Model alias | Role in this benchmark |
| --- | --- |
| `bge-small-zh-v1.5` | Current fast local baseline and historical comparison point. |
| `bge-m3` | Multilingual and long-text candidate for later retrieval experiments. |
| `multilingual-e5-base` | Stable multilingual baseline for Chinese/English comparison. |
| `qwen3-embedding-0.6b` | Candidate focused on mixed-language, code/API/config, and cross-lingual retrieval behavior. |

All four models loaded successfully in this run. The load report stores only model aliases and placeholder model paths.

## Benchmark Cases

The benchmark uses 72 cases, with 8 cases per query type:

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

Negative cases verify banned-source exclusion only. They do not prove semantic answer quality.

## Reviewed Chunks

The benchmark uses 575 recovered reviewed chunks:

- `ingest_candidate=true`
- `review_status=approved`
- `normalization_status=pass`
- banned, filtered, rejected, or navigation-heavy sources excluded

The benchmark uses an in-memory vector index. It does not write a production Chroma collection and does not expand the corpus.

## Evaluation Method

Each model embeds the same recovered chunk texts and the same benchmark queries. Embeddings are normalized and compared with cosine similarity in memory. Results are evaluated with:

- source hit at top-k
- top-1 source hit
- source MRR
- doc type hit at top-k
- keyword hit at top-k
- exact match hit at top-k
- banned source result count
- model load time
- indexing time
- average query latency

## Overall Metrics

| Model | Source hit@5 | Top1 source hit | MRR source | Keyword hit@5 | Doc type hit@5 | Exact hit@5 | Code/API hit@5 | Avg query ms | Indexing sec |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `bge-small-zh-v1.5` | 0.8125 | 0.6406 | 0.7094 | 0.7812 | 0.7031 | 0.4375 | 0.75 | 5.9795 | 40.2112 |
| `bge-m3` | 0.7969 | 0.6875 | 0.7336 | 0.875 | 0.6719 | 0.4688 | 0.625 | 82.8577 | 926.362 |
| `multilingual-e5-base` | 0.75 | 0.5938 | 0.6448 | 0.8281 | 0.6719 | 0.375 | 0.625 | 23.7941 | 254.1502 |
| `qwen3-embedding-0.6b` | 1.0 | 0.875 | 0.9229 | 0.8906 | 0.7969 | 0.5 | 1.0 | 140.7893 | 1474.562 |

`qwen3-embedding-0.6b` has the strongest quality metrics on the current reviewed sample benchmark. It also has the highest indexing time and average query latency, so it is not suitable for frequent local reruns on this machine.

## Query-Type Highlights

| Query type | Strongest observed model | Notes |
| --- | --- | --- |
| `zh_knowledge` | `qwen3-embedding-0.6b` | Reached 1.0 source hit and 1.0 top1 source hit. |
| `en_api_doc` | Tie across all four models on source hit | All reached 1.0 source hit. |
| `mixed_zh_en_api` | Tie on source hit; `qwen3-embedding-0.6b` strongest MRR/top1 | Summary tie-break recorded `bge-small-zh-v1.5`, while Qwen3 also reached 1.0 source hit and had stronger top1/MRR. |
| `agent_rag_concept` | Tie on source hit; `bge-small-zh-v1.5` strongest MRR | All reached 1.0 source hit. |
| `exact_metadata_lookup` | `qwen3-embedding-0.6b` | Best source hit and MRR, but exact matching remains imperfect. |
| `code_api_config` | `qwen3-embedding-0.6b` | Best source hit and code/API hit. |
| `short_keyword` | `qwen3-embedding-0.6b` | Best source hit; exact keyword hit ties with baseline and E5. |
| `negative_banned_source` | All models passed banned-source exclusion | Banned source result count is 0 for all models. |
| `phase6c_bad_case_regression` | `qwen3-embedding-0.6b` | Best source hit and MRR. |

## Load Results

| Model | Load success | Dimension | Load time sec |
| --- | --- | ---: | ---: |
| `bge-small-zh-v1.5` | true | 512 | 36.3777 |
| `bge-m3` | true | 1024 | 4.7985 |
| `multilingual-e5-base` | true | 768 | 3.9277 |
| `qwen3-embedding-0.6b` | true | 1024 | 31.3254 |

No model failed due to missing files, dependency errors, or resource limits in this run.

## Recommendation

Use `qwen3-embedding-0.6b` as the main candidate for later Phase 6D retrieval experiments because it achieved the strongest overall source hit, top1 source hit, MRR, code/API/config performance, exact metadata source hit, and Phase 6C regression recovery on the reviewed sample benchmark.

Keep `bge-small-zh-v1.5` as the local fast baseline because it has much lower indexing time and query latency, and it remains useful for quick local checks.

Keep `bge-m3` and `multilingual-e5-base` as comparison models for later experiments. They remain useful controls for multilingual and long-text retrieval evaluation.

## Current Limits

This benchmark is limited to the reviewed sample corpus and 72 curated cases. It does not prove that any model is absolutely best. It does not represent a production traffic distribution, a full enterprise corpus, or a final model selection. It does not evaluate generation quality, citation quality, multi-turn behavior, or production latency under service load.

The current exact metadata results also show that dense embedding alone is not enough for exact field lookup. Exact lookup should be handled by metadata filters, keyword matching, or hybrid retrieval in later phases.

## Next Phases

Phase 6D-3 should use these findings to prototype hybrid retrieval, especially for exact metadata, code/API/config, and short keyword cases.

Phase 6D-4 should evaluate reranking on top of the strongest dense retrieval candidates.

Phase 6D-5 should test whether chunking changes improve exact and API/config cases.

No Hybrid Retrieval, Reranker, Chunking Ablation, or production model replacement is completed in this phase.
