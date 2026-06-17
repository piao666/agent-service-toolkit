# Phase 6E-7 Gated Retrieval Policy

## Background

Phase 6E-6 full API-level re-evaluation showed a split result:

- On the 59 remaining bad cases, `query_type_aware` improved source hit and reduced bad cases.
- On the 240-case full set, globally enabling `query_type_aware` reduced source hit and increased
  bad cases.

This means `query_type_aware` is useful as a targeted intervention, but it should not replace the
baseline retrieval path globally.

## Why Baseline Cannot Be Replaced Globally

The baseline dense retrieval path remains stronger for ordinary knowledge, API documentation, mixed
Chinese/English API questions, and concept questions. A global metadata/sparse policy can overfit
the hard 59-case set and degrade broader retrieval quality.

Phase 6E-7 therefore keeps baseline as the default and uses a gated policy only for query types that
benefit from non-dense signals.

## Gated Policy Rules

Enabled query-type-aware policies:

- `exact_metadata_lookup` -> `metadata_first`
- `code_api_config` -> `sparse_first_bm25`
- `short_keyword` -> conservative `sparse_first_bm25`
- `citation_required_query` -> `citation_aware_evidence`

Conditional policy:

- `phase6c_bad_case_regression` stays baseline unless the query contains explicit metadata,
  code/API/config, or citation features.

Fallback to baseline:

- `zh_knowledge`
- `en_api_doc`
- `mixed_zh_en_api`
- `agent_rag_concept`
- `ambiguous_query` retrieval stays baseline with clarification debug only
- `multi_hop_lookup` stays baseline until a full multi-query evaluation is done
- `negative_banned_source` retrieval stays baseline with guard debug only

## Retrieval Debug Fields

When `ENTERPRISE_RAG_POLICY_MODE=query_type_aware`, retrieval debug now records:

- `policy_mode`
- `inferred_query_type`
- `selected_policy`
- `gated_policy_enabled`
- `fallback_to_baseline`
- `gated_reason`
- `metadata_first_applied`
- `sparse_first_applied`
- `dense_sparse_fusion_applied`
- `citation_evidence_checked`
- `clarification_first_applied`

## Local Probe

The Phase 6E-7 local probe reads the 59 remaining policy cases and checks only routing decisions.
It does not call an LLM, start a service, or write Chroma.

Summary:

- `total_cases=59`
- `gated_enabled_count=49`
- `fallback_to_baseline_count=10`
- `metadata_first_count=35`
- `sparse_first_count=8`
- `citation_aware_count=6`
- `clarification_debug_only_count=6`
- `baseline_default_unchanged=true`
- `calls_llm=false`
- `writes_chroma=false`
- `recommended_hpc_full_eval=true`

Outputs:

- `data/knowledge_base/evaluation/phase6e7_gated_policy_probe_results.jsonl`
- `data/knowledge_base/evaluation/phase6e7_gated_policy_probe_summary.json`

## Phase 6E-8 Plan

Phase 6E-8 should run full API-level re-evaluation comparing baseline, global
`query_type_aware`, and gated `query_type_aware`. The expected outcome is to retain the 59-case
targeted improvement while avoiding the 240-case full regression observed in Phase 6E-6.

## Boundaries

- This does not claim production launch readiness.
- This does not claim all bad cases are solved.
- This does not call a generation model.
- This does not write Chroma.
- Default Agent/API behavior remains `baseline`.
