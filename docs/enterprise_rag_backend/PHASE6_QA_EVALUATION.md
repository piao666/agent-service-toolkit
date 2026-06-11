# Phase 6C QA Evaluation

## Corrected Conclusion

Retrieval-only evaluation completed on reviewed Chroma sample.
API/Agent endpoint evaluation was skipped because local service was unavailable.
No end-to-end Agent QA success is claimed.

This document must not be read as proof that end-to-end Agent/API evaluation passed, that the complete QA evaluation loop is finished, or that the RAG system is production ready.

## Goal And Boundary

Phase 6C currently provides a retrieval-only evaluation baseline for the reviewed Phase 6 corpus. API/Agent endpoint evaluation is represented in the output schema, but the local endpoint run was skipped and should be rerun after the local service and provider configuration are available.

## Evaluation Scope

The evaluation reads the reviewed Chroma collection `enterprise_ai_learning_kb_reviewed` from `chroma_enterprise_phase6`. It does not create a new collection, expand the ingestion scope, or modify production endpoint behavior.

## Local Knowledge Base Layout

```text
data/knowledge_base/
  raw/                 # ignored raw downloaded/local source cache
  normalized/          # ignored normalized text cache
  chunks/              # ignored chunk text cache
  manifests/           # committed metadata/report manifests
  evaluation/          # committed evaluation cases/results/summaries

chroma_enterprise_phase6/
  # ignored local Chroma vector store

collection_name:
  enterprise_ai_learning_kb_reviewed
```

## QA Case Design

The case file is `data/knowledge_base/evaluation/phase6_qa_cases.jsonl`. It contains positive cases for deep learning, NLP, AI Agent concepts, FastAPI documentation, and repository metadata, plus negative cases that verify banned sources are not returned.

## Retrieval Metrics

| metric | value |
| --- | --- |
| case_count | 26 |
| positive_case_count | 24 |
| negative_case_count | 2 |
| source_hit_at_k | 0.9167 |
| doc_type_hit_at_k | 0.9583 |
| keyword_hit_at_k | 0.875 |
| top1_source_hit | 0.5833 |
| mrr_source | 0.7153 |
| empty_result_count | 0 |
| banned_source_result_count | 0 |
| invalid_result_count | 0 |

Retrieval evaluation calls the local embedding model to encode queries, reads Chroma, and stores only metadata plus short previews.

## API Metrics

| metric | value |
| --- | --- |
| api_eval_status | skipped |
| case_count_selected | 10 |
| case_count_run | 0 |
| expected_source_hit_rate | 0.0 |
| expected_keyword_hit_rate | 0.0 |
| fallback_count | 0 |
| error_count | 0 |
| avg_latency_ms | None |
| calls_llm | False |
| end_to_end_agent_eval_passed | False |

Endpoint evaluation was skipped and should be rerun after the local service and provider configuration are available.

## Embedding Limitations

The current embedding route uses a local small Chinese embedding model. It is suitable for a Chinese semantic retrieval smoke test, but it is limited for mixed Chinese/English documents, English API documentation, code snippets, function names, class names, configuration fields, exact identifiers, order numbers, paths, and cross-language query-document matching.

Follow-up options include evaluating multilingual embeddings, evaluating code-aware embeddings, using hybrid retrieval, separately evaluating English technical documentation, and creating a dedicated mixed-language QA set. The current embedding model should not be described as the production-best solution.

## Chunking Strategy Gaps

Phase 6B chunking is an engineering validation baseline, not a final chunking strategy. Different source formats need different strategies:

- DOCX: title hierarchy plus paragraph aggregation.
- PDF: page number plus heading/paragraph recovery, with header and footer cleanup when needed.
- HTML: main/article extraction plus heading splitting, with navigation, sidebar, and footer filtering.
- Markdown: heading splitting with code block protection.
- JSON/YAML: key path or object-structure splitting.
- CSV/Table: header, row group, and field-semantics-aware splitting.
- Code/API documentation: preserve function signatures, parameter descriptions, and example code instead of hard cuts.

The current phase has not completed semantic chunking, chunk size and overlap tuning, chunk-level ablation, reranker before/after chunk quality comparison, or formal validation for PDF tables, scanned files, and two-column papers.

## Intent Recognition Gaps

The current evaluation does not systematically validate user intent recognition, including knowledge lookup, business action calls, chit-chat, summarization or rewriting, exact lookup for identifiers and fields, multi-turn follow-up, or questions that do not need retrieval.

A later router evaluation should use intent labels such as:

```text
intent = knowledge_lookup / business_action / chit_chat / exact_lookup / unsupported / clarification_needed
```

Current results should not be used to claim stable query routing.

## Retrieval Strategy Gaps

The current retrieval evaluation is primarily dense vector retrieval over a small reviewed sample. Production-grade retrieval still needs BM25 or keyword retrieval, dense plus sparse hybrid retrieval, exact matching, metadata filters, reranking, top-k policy, score thresholding, query rewriting, multi-query retrieval, source diversity control, and negative query handling.

Pure vector retrieval is weak for exact identifiers, order numbers, API names, file paths, config keys, and short keyword queries.

A possible future scoring direction is:

```text
hybrid_score = alpha * dense_score + beta * sparse_score + gamma * metadata_match_score
```

This is a future plan only and is not implemented in Phase 6C.

## Current Limitations

The reviewed collection is intentionally small and metadata controlled. Phase 6C reports retrieval evidence for this reviewed sample only and does not claim production accuracy. Some misses may be caused by limited source coverage, chunk boundaries, mixed Chinese and English terminology, and the current dense-only retrieval strategy.

## Next Improvements

Recommended follow-up work is to inspect bad cases, design intent routing evaluation, prototype hybrid retrieval, evaluate reranking, run chunking ablation, and rerun endpoint evaluation after the local service is available.
