# Phase 6C System Gap Analysis

## Current Validated Scope

- Retrieval-only evaluation completed on reviewed Chroma sample.
- The evaluated collection is `enterprise_ai_learning_kb_reviewed`.
- The evaluated vector store directory is `chroma_enterprise_phase6`, which is ignored local state.
- Retrieval output validation confirmed `banned_source_result_count=0` and `invalid_result_count=0`.

## Not Yet Validated Scope

- End-to-end Agent/API QA success is not validated.
- Production retrieval quality is not validated.
- Query routing stability is not validated.
- Intent recognition is not validated.
- Hybrid retrieval, reranking, and chunking ablation are not validated.
- Large-scale corpus ingestion is not validated.

## Local Knowledge Base Location

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

## Embedding Limitations

The current embedding route uses a local small Chinese embedding model. It is appropriate for a Chinese semantic retrieval smoke test, but it has limitations for:

- Mixed Chinese/English documents.
- English API documentation.
- Code snippets.
- Function names, class names, and configuration fields.
- Exact identifiers, order numbers, and paths.
- Cross-language query-document matching.

Future work should evaluate multilingual embeddings, code-aware embeddings, hybrid retrieval, English technical-document test cases, and mixed-language QA cases.

## Chunking Strategy Gaps

Current chunking is a Phase 6B engineering baseline. Format-specific gaps remain:

- DOCX needs title hierarchy plus paragraph aggregation.
- PDF needs page number plus heading/paragraph recovery, and header/footer cleanup when needed.
- HTML needs main/article extraction, heading splitting, and navigation/sidebar/footer filtering.
- Markdown needs heading splitting with code block protection.
- JSON/YAML needs key path or object-structure splitting.
- CSV/Table needs header, row group, and field-semantics-aware splitting.
- Code/API documentation needs function signatures, parameter descriptions, and examples preserved.

Not yet completed: semantic chunking, chunk size and overlap tuning, chunk-level ablation, reranker before/after comparison, and formal validation for PDF tables, scanned files, and two-column papers.

## Intent Recognition Gaps

The project has not systematically evaluated whether a user request is:

- `knowledge_lookup`
- `business_action`
- `chit_chat`
- `exact_lookup`
- `unsupported`
- `clarification_needed`

Intent test cases should cover knowledge-base questions, business-system calls, chit-chat, summarization and rewriting, exact lookup for identifiers or fields, multi-turn follow-up, and questions that do not need retrieval.

Current results cannot be used to claim stable query routing.

## Retrieval Strategy Gaps

The current strategy is primarily dense vector retrieval. Production-grade retrieval still needs:

- BM25 or keyword retrieval.
- Dense plus sparse hybrid retrieval.
- Exact matching.
- Metadata filters.
- Reranking.
- Top-k policy.
- Score thresholding.
- Query rewriting.
- Multi-query retrieval.
- Source diversity control.
- Negative query handling.

Pure vector retrieval is weak for exact identifiers, order numbers, API names, file paths, config keys, and short keyword queries.

Future hybrid scoring can be evaluated with:

```text
hybrid_score = alpha * dense_score + beta * sparse_score + gamma * metadata_match_score
```

This is only a proposed direction and is not implemented in Phase 6C.

## API/Agent Eval Skipped Status

Endpoint evaluation was skipped and should be rerun after the local service and provider configuration are available.

```json
{
  "api_eval_status": "skipped",
  "skip_reason": "local_service_unavailable",
  "case_count_run": 0,
  "calls_llm": false,
  "end_to_end_agent_eval_passed": false
}
```

## Required Work Before Claiming Production Readiness

- Run endpoint evaluation with the local service and configured provider available.
- Add intent routing tests and confusion analysis.
- Compare dense-only retrieval with hybrid retrieval.
- Evaluate reranking on the reviewed corpus.
- Run chunking ablation by format and topic.
- Expand reviewed source coverage through controlled ingestion.
- Add negative and exact-lookup cases for identifiers, field names, and short keyword queries.

## Proposed Phase 6D Plan

- Phase 6D-1: Intent routing evaluation.
- Phase 6D-2: Hybrid retrieval prototype.
- Phase 6D-3: Reranker evaluation.
- Phase 6D-4: Chunking ablation.
- Phase 6D-5: End-to-end Agent/API evaluation after service is available.

This plan is documentation only. Phase 6D is not implemented in this update.
