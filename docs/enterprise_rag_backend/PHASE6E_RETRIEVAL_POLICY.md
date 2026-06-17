# Phase 6E Retrieval Policy

## Background

Phase 6D closed the evaluation loop for corpus construction, reviewed Chroma ingestion,
embedding comparison, retrieval strategy comparison, reranker evaluation, chunking ablation,
Agent/API runtime validation, real provider evaluation, and bad-case calibration.

The final Phase 6D closure conclusion is that the remaining failures are concentrated in
retrieval policy, metadata lookup, code/config lookup, and old regression cases. They are not
API transport or runtime availability failures.

## Why Memory Moves Later

Conversation memory is still useful, but it does not directly address the calibrated Phase 6D-9
failure clusters. The immediate blocker is first-hop evidence selection: exact metadata queries
need metadata-first routing, code/config questions need lexical-first retrieval, and citation
queries need evidence verification. Memory management is therefore moved after the retrieval
policy work.

## Remaining Bad Cases

Phase 6D Final Closure records 59 remaining policy cases:

| Policy query type | Count |
|---|---:|
| exact_metadata_lookup | 31 |
| phase6c_bad_case_regression | 10 |
| code_api_config | 7 |
| ambiguous_query | 6 |
| citation_required_query | 5 |

The committed Phase 6D-9 calibrated taxonomy artifact still contains 84 rows. The Phase 6E
simulator keeps both `original_query_type` and `query_type` so the policy regression suite can
follow the final closure distribution without hiding that artifact mismatch.

## Query-Type-Aware Policy

### Metadata-First

`exact_metadata_lookup` should check metadata fields before relying on embedding similarity:

- `source_id`
- `doc_type`
- `domain`
- `title`
- `section_path`
- `heading_path`
- `chunk_id`
- `source_url`
- `normalized_id`

The intent is to promote exact metadata hits to the top results.

### Sparse-First / BM25-First

`code_api_config` and `short_keyword` need lexical-first retrieval for API paths, symbols,
function names, class names, config keys, parameter names, error codes, filenames, and exact
terms. Dense embeddings remain useful, but should not dominate these cases.

### Dense + Sparse Fusion

Ordinary knowledge queries such as `zh_knowledge`, `en_api_doc`, `mixed_zh_en_api`, and
`agent_rag_concept` should use semantic retrieval plus sparse keyword coverage.

### Clarification-First

`ambiguous_query` should not force one expected source. The preferred behavior is clarification
or a multi-candidate answer.

### Multi-Query Retrieval

`multi_hop_lookup` should split comparative or conjunctive queries with rule-based separators
such as "对比", "区别", "同时", "以及", "和", "并且", and "分别", then merge candidate evidence.

### Citation-Aware Evidence

`citation_required_query` should verify that returned evidence has traceable metadata, including
source id plus title, source URL, or section path when available.

### Banned-Source Guard

`negative_banned_source` remains a guard-first path. Success is `banned_source_result_count=0`,
not source hit.

## Offline Simulator

`scripts/run_phase6e_policy_simulator.py` reads Phase 6D-9 and Phase 6D-7 artifacts, builds
`phase6e_remaining_bad_cases.jsonl`, and writes policy recommendations plus a summary.

Outputs:

- `data/knowledge_base/evaluation/phase6e_remaining_bad_cases.jsonl`
- `data/knowledge_base/evaluation/phase6e_policy_simulation_results.jsonl`
- `data/knowledge_base/evaluation/phase6e_policy_simulation_summary.json`

The simulator is intentionally conservative. If a case cannot be verified by local rules, it is
marked `design_only`. Design-only cases are not counted as real retrieval improvement.

## Minimal Implementation

Phase 6E-2 adds `src/rag/retrieval_policy.py` and the
`ENTERPRISE_RAG_POLICY_MODE` setting. The default remains `baseline`, so production Agent/API
behavior is not changed by this phase.

Implemented helper functions:

- `infer_query_type`
- `select_retrieval_policy`
- `metadata_first_score`
- `sparse_first_score`
- `dense_sparse_fusion_score`
- `split_multi_hop_query`
- `citation_evidence_check`

Phase 6E-5 wires the helper into the enterprise retrieval path:

- `src/agents/enterprise_tools.py` reads `ENTERPRISE_RAG_POLICY_MODE`.
- `baseline` continues to call the existing dense retrieval path.
- `query_type_aware` calls `retrieve_with_policy()` in `src/rag/retriever.py`.
- `retrieval_debug` records selected policy fields without changing the response schema.

## Local Regression Result

Local simulator result:

- `total_remaining_bad_cases=59`
- `simulated_improvable_count=36`
- `design_only_count=13`
- `requires_production_change_count=59`
- `recommended_phase6e4_eval=true`

Recommended policy distribution:

| Policy | Count |
|---|---:|
| metadata_first | 31 |
| dense_sparse_fusion | 10 |
| sparse_first_bm25 | 7 |
| clarification_first | 6 |
| citation_aware_evidence | 5 |

These are offline policy estimates, not production accuracy gains.

## Phase 6E-6 Plan

Phase 6E-6 should run full API-level re-evaluation after Phase 6E-5 policy wiring, comparing
baseline vs `query_type_aware` mode.

## Boundaries

- This is not production launch validation.
- This does not claim all bad cases are solved.
- Default Agent/API behavior remains `baseline`.
- This does not call DeepSeek, Qwen, or any generation model.
- This does not write Chroma.
- This does not change default Agent/API behavior.
