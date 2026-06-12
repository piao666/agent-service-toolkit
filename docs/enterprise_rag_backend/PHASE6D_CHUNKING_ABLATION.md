# Phase 6D-5 Chunking Ablation Evaluation

## Goal

Phase 6D-5 evaluates how different chunking strategies affect retrieval quality over the reviewed sample corpus. The focus is on exact metadata lookup, code/API/config, short keyword, and Phase 6C bad-case regression queries.

This is an offline chunking ablation.
It is not wired into production Agent/API routing.
No production Chroma collection is written.
No generative LLM is called.
It does not switch the production chunking strategy.

## Why Chunking Ablation Is Needed

Earlier Phase 6D work showed that dense, sparse, hybrid, and reranker behavior depends heavily on candidate quality. Candidate quality is affected by chunk boundaries, metadata density, and whether exact terms stay near their explanations. Chunking ablation tests those assumptions before any runtime integration.

## Reviewed Data Scope

The evaluation uses reviewed normalized documents and existing reviewed chunks only:

- `ingest_candidate=true`
- `review_status=approved`
- `normalization_status=pass`
- banned, filtered, rejected, and navigation-heavy sources excluded

The full local run selected 12 reviewed normalized documents and compared all strategies over the same 72 cases.

## Strategies

| Strategy | Description |
| --- | --- |
| `baseline_existing_chunks` | Current reviewed chunk manifest, without modifying the manifest. |
| `small_chunks` | Paragraph-aware chunks around 450 chars with small overlap. |
| `large_chunks` | Paragraph-aware chunks around 1300 chars with moderate overlap. |
| `sliding_window_overlap` | Character sliding windows around 850 chars with larger overlap. |
| `metadata_enriched_chunks` | Paragraph chunks prefixed with title, source id, doc type, domain, language, and normalized id. |
| `section_aware_chunks` | Heading-aware section splitting when headings exist, with paragraph fallback. |

All ablation chunks are generated in memory. The script does not overwrite `chunk_manifest.jsonl`.

## Full Run Settings

- model alias: `bge-small-zh-v1.5`
- cases: 72
- selected reviewed normalized documents: 12
- top-k: 5
- batch size: 8
- device: `cpu`
- retrieval scoring: dense + BM25 + exact/metadata weighted hybrid

## Overall Metrics

| Strategy | Chunks | Avg chars | Max chars | Source hit@5 | Top1 | MRR | Keyword hit@5 | Exact hit@5 | Code/API hit@5 | Banned count |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| `baseline_existing_chunks` | 575 | 799.433 | 966 | 0.7812 | 0.7188 | 0.75 | 0.8438 | 0.5938 | 0.75 | 0 |
| `small_chunks` | 1174 | 400.0801 | 494 | 0.7812 | 0.6719 | 0.7167 | 0.8125 | 0.5312 | 0.75 | 0 |
| `large_chunks` | 397 | 1143.3753 | 1421 | 0.7812 | 0.7188 | 0.7427 | 0.8281 | 0.5625 | 0.75 | 0 |
| `sliding_window_overlap` | 675 | 844.6281 | 850 | 0.7656 | 0.6562 | 0.7031 | 0.8438 | 0.5625 | 0.75 | 0 |
| `metadata_enriched_chunks` | 577 | 945.8735 | 1109 | 0.7656 | 0.7031 | 0.7292 | 0.8594 | 0.625 | 0.625 | 0 |
| `section_aware_chunks` | 1067 | 405.1453 | 961 | 0.7812 | 0.6562 | 0.707 | 0.8125 | 0.5312 | 0.75 | 0 |

The current baseline remains the best overall strategy for source hit, top1, and MRR. `metadata_enriched_chunks` has the best exact-match hit rate, but it reduces overall source hit and code/API hit in this run.

## Query-Type Deltas Versus Baseline

### Exact Metadata Lookup

| Strategy | Source hit delta | Top1 delta | MRR delta |
| --- | ---: | ---: | ---: |
| `small_chunks` | -0.125 | -0.25 | -0.2083 |
| `large_chunks` | -0.125 | -0.125 | -0.1458 |
| `sliding_window_overlap` | -0.125 | -0.25 | -0.2292 |
| `metadata_enriched_chunks` | -0.125 | 0.0 | -0.0625 |
| `section_aware_chunks` | 0.0 | -0.125 | -0.0833 |

Exact metadata ranking does not improve on source hit. Metadata enrichment helps exact term presence overall but does not improve exact metadata source ranking in this case set.

### Code/API/Config

| Strategy | Source hit delta | Top1 delta | MRR delta |
| --- | ---: | ---: | ---: |
| `small_chunks` | 0.0 | +0.125 | +0.0625 |
| `large_chunks` | 0.0 | +0.125 | +0.0625 |
| `sliding_window_overlap` | 0.0 | +0.125 | +0.0625 |
| `metadata_enriched_chunks` | -0.125 | 0.0 | -0.0625 |
| `section_aware_chunks` | 0.0 | 0.0 | -0.0208 |

Small, large, and sliding-window chunks improve ordering for code/API/config cases without improving source hit. Metadata enrichment degrades source hit for this query type.

### Short Keyword

| Strategy | Source hit delta | Top1 delta | MRR delta |
| --- | ---: | ---: | ---: |
| `small_chunks` | 0.0 | 0.0 | -0.0208 |
| `large_chunks` | 0.0 | 0.0 | 0.0 |
| `sliding_window_overlap` | 0.0 | 0.0 | -0.0208 |
| `metadata_enriched_chunks` | 0.0 | 0.0 | 0.0 |
| `section_aware_chunks` | 0.0 | 0.0 | -0.0208 |

Short keyword retrieval is already strong in the baseline. No ablation strategy improves it.

### Phase 6C Bad-Case Regression

| Strategy | Source hit delta | Top1 delta | MRR delta |
| --- | ---: | ---: | ---: |
| `small_chunks` | +0.125 | 0.0 | +0.025 |
| `large_chunks` | +0.125 | 0.0 | +0.025 |
| `sliding_window_overlap` | 0.0 | 0.0 | 0.0 |
| `metadata_enriched_chunks` | +0.125 | 0.0 | +0.0417 |
| `section_aware_chunks` | 0.0 | 0.0 | 0.0 |

Small, large, and metadata-enriched chunks help part of the bad-case regression set, but not enough to beat the current baseline overall.

## Improvements And Regressions

Improvements:

- `metadata_enriched_chunks` improves overall exact-match hit rate from 0.5938 to 0.625.
- `small_chunks`, `large_chunks`, and `sliding_window_overlap` improve code/API/config top1 and MRR while preserving source hit.
- `small_chunks`, `large_chunks`, and `metadata_enriched_chunks` improve Phase 6C bad-case regression source hit by 0.125.

Regressions:

- `small_chunks` and `section_aware_chunks` increase chunk count substantially and reduce overall top1/MRR.
- `sliding_window_overlap` reduces overall source hit, top1, and MRR.
- `metadata_enriched_chunks` improves exact-match presence but degrades overall source hit and code/API source hit.
- `large_chunks` keeps source hit and top1 tied with baseline but slightly lowers MRR and exact hit.

## Current Conclusion

The best overall strategy in this run is `baseline_existing_chunks`. No ablation strategy is strong enough to justify replacing the current reviewed chunking strategy.

The useful next design direction is not a global chunking switch. It is a conditional strategy: retain the current baseline for general retrieval, then test targeted metadata enrichment or chunk-size variants for exact/code-heavy query paths after intent routing and larger-corpus validation.

## Current Limits

This is an offline evaluation over reviewed samples, not a production corpus. The splitters are simple, and section-aware splitting depends on headings already present in normalized text. The run uses `bge-small-zh-v1.5` as the local fast baseline. It does not evaluate answer quality and does not call any generative model.

The ablation chunks are generated in memory and are not written as a production chunk manifest.

## Production Boundary

This phase does not modify production Agent code, API behavior, Agent registry, service routes, or Chroma collections. It does not call a business system and does not call a generative LLM.

Manual review is required before checkpoint and before any future runtime integration.

## Handoff

Phase 6E can use these results when designing conversation memory and query rewriting because memory may change query specificity and metadata needs. If reranking or chunking is revisited on HPC, use placeholder paths such as `<HPC_WORKDIR>` and `<HPC_MODEL_ROOT>` and record skipped states honestly when resource limits occur.

This phase does not complete Phase 6E, Phase 6F, Phase 7, or any production readiness claim.
