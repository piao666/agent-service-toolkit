# Phase 6D-6 Agent/API Evaluation

## Scope

Phase 6D-6 evaluates the existing `POST /enterprise/agent/query` endpoint from the
application-facing API boundary. It checks service reachability, OpenAPI request schema alignment,
structured response validity, answer presence, retrieval evidence presence, source hit behavior,
keyword hit behavior, and banned-source exclusion.

This phase is evaluation and runtime diagnosis only. It does not modify production Agent/API
behavior, does not write a production Chroma collection, does not run a production load test, and
does not claim production readiness.

## Service and Endpoint

- Service base URL: `http://127.0.0.1:8000`
- Endpoint: `/enterprise/agent/query`
- Endpoint exists in OpenAPI: true
- Request payload fields used by the evaluator: `query`, `session_id`, `top_k`, `return_sources`
- Payload matches the OpenAPI request schema: true
- Evidence carrier: `sources`

The endpoint does not need a separate `citations` field for this evaluation. `sources` is the
runtime source-evidence carrier.

## Case Set

The full evaluation uses 40 cases across eight query types:

| Query Type | Count |
| --- | ---: |
| `zh_knowledge` | 5 |
| `en_api_doc` | 5 |
| `mixed_zh_en_api` | 5 |
| `exact_metadata_lookup` | 5 |
| `code_api_config` | 5 |
| `short_keyword` | 5 |
| `negative_banned_source` | 5 |
| `phase6c_bad_case_regression` | 5 |

Negative banned-source cases only check that banned sources are not returned. They do not evaluate
semantic answer quality.

## Original Issue

The first Phase 6D-6 run showed that API transport and response schema were stable, but runtime RAG
evidence was not usable:

- API requests returned 200.
- Response schema validation passed.
- All cases initially reached retrieval fallback.
- `sources=[]` caused evidence and source-hit metrics to be zero.

Static and runtime diagnosis found two root causes:

1. `runtime_chroma_disk_io_error`: the original runtime Chroma store could not be opened reliably by
   `chromadb.PersistentClient` in this environment.
2. `evaluator_source_id_extraction_mismatch`: after runtime retrieval was repaired externally, the
   evaluator still treated top-level `source=unknown` as the source id and missed the actual
   `sources[].metadata.source_id` value.

## Fix Summary

The runtime and evaluator fixes were:

- Used an external repaired runtime Chroma cache represented in project files only as
  `<RUNTIME_CHROMA_DIR>`.
- Kept local embedding path references as `<LOCAL_EMBEDDING_MODEL_PATH>`.
- Added config compatibility for `LOCAL_EMBEDDING_MODEL_ROOT` and
  `ENTERPRISE_CHROMA_COLLECTION`, while preserving the original primary variables.
- Enhanced retriever fallback diagnostics with sanitized `retrieval_stage` and `error_summary`.
- Fixed evaluator source-id extraction to prefer `sources[].metadata.source_id` before top-level
  source fields.
- Treated non-empty `sources` as evidence present.

The evaluator source-id priority is:

1. `source.metadata.source_id`
2. `source.source_id`
3. `source.metadata.doc_id`
4. `source.doc_id`
5. `source.metadata.title`
6. `source.title`
7. `source.source`, except `unknown` is ignored

## Full Rerun Results

The full 40-case Agent/API evaluation was rerun on the repaired runtime Chroma.

| Metric | Value |
| --- | ---: |
| `case_count` | 40 |
| `request_success_rate` | 1.0 |
| `response_schema_valid_rate` | 1.0 |
| `answer_non_empty_rate` | 1.0 |
| `fallback_count` | 0 |
| `evidence_present_rate` | 1.0 |
| `citation_present_rate` | 1.0 |
| `source_hit_rate` | 0.7429 |
| `keyword_hit_rate` | 0.9429 |
| `banned_source_result_count` | 0 |
| `bad_case_count` | 10 |

By-query-type observations:

- `zh_knowledge`, `en_api_doc`, `mixed_zh_en_api`, and `short_keyword` all reached source-hit rate
  1.0.
- `code_api_config` source-hit rate reached 0.8.
- `exact_metadata_lookup` and `phase6c_bad_case_regression` remain weaker and account for most
  residual bad cases.
- Negative banned-source cases returned no banned sources.

## Interpretation

Phase 6D-6 now confirms that the endpoint can call the Agent/API path, return non-empty answers, and
return source evidence through `sources` when the runtime Chroma environment is healthy. It also
confirms that source-id parsing must use metadata fields, not only the top-level `source` field.

This is still not a production-readiness claim:

- `bad_case_count=10` remains.
- This is not a load test.
- This is not a complete enterprise readiness evaluation.
- This does not complete Phase 6E memory work or Phase 6F readiness work.
- The repaired runtime Chroma cache is local runtime state and is not committed.

## Safety Flags

- `calls_agent_api=true`
- `writes_chroma=false`
- `modifies_agent=false`
- `modifies_api=false`
- `writes_production_chroma_collection=false`
- `downloads_model=false`
- `stores_full_answer=false`

## Next Step

Manual review should inspect the 10 remaining bad cases before checkpoint. After manual review, this
Phase 6D-6 checkpoint can be considered complete as an end-to-end Agent/API evaluation on the
reviewed runtime corpus, with residual retrieval-quality issues explicitly recorded.
