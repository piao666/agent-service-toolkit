# Phase 6E-5 Policy Wiring

## Why This Phase Exists

Phase 6E-0 to Phase 6E-3 added a query-type-aware retrieval policy helper and an offline
simulator. Phase 6E-4 validation found that the policy existed only as helper code and was not
called by the enterprise retrieval path. Therefore API-level baseline versus query-type-aware
comparison would not have been meaningful.

Phase 6E-5 wires the policy into the enterprise retrieval path without changing default behavior.

## Phase 6E-4 Boundary

Phase 6E-4 did not run full API-level evaluation because:

- `select_retrieval_policy()` was defined but not called by the retrieval entrypoint.
- `ENTERPRISE_RAG_POLICY_MODE` existed but was not read by retrieval execution.
- Runtime Agent/API behavior was still baseline dense retrieval.

## Wiring Location

The feature flag is read in `src/agents/enterprise_tools.py`.

- `ENTERPRISE_RAG_POLICY_MODE=baseline`: call the existing dense retrieval path.
- `ENTERPRISE_RAG_POLICY_MODE=query_type_aware`: call `retrieve_with_policy()` from
  `src/rag/retriever.py`.

`src/rag/retriever.py` performs the policy-specific reranking and returns policy debug metadata.

## Feature Flag

Default:

```text
ENTERPRISE_RAG_POLICY_MODE=baseline
```

Optional policy mode:

```text
ENTERPRISE_RAG_POLICY_MODE=query_type_aware
```

The default remains baseline, so existing Agent/API behavior is preserved unless the flag is
explicitly changed.

Phase 6E-7 changes `query_type_aware` from a global replacement into a gated mode. In gated mode,
only metadata, code/config, short-keyword, and citation-required queries use the specialized
policy. Ordinary knowledge and ambiguous or multi-hop queries fall back to baseline retrieval.

## Query-Type-Aware Behavior

- `exact_metadata_lookup`: uses bounded read-only Chroma scan plus metadata scoring, then falls
  back to dense results.
- `code_api_config` and `short_keyword`: use sparse-first scoring over document text and metadata,
  then falls back to dense results.
- Ordinary knowledge stays baseline.
- `phase6c_bad_case_regression` stays baseline unless the query has explicit metadata, code/API, or
  citation features.
- `ambiguous_query`: sets clarification debug fields while still returning evidence.
- `citation_required_query`: annotates sources with citation evidence checks.
- `negative_banned_source`: remains a guard-oriented policy in the helper layer; full runtime
  banned-source lists require the next full evaluation harness.

## Retrieval Debug

When `query_type_aware` is enabled, `retrieval_debug` can include:

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
- `requires_clarification`

Baseline mode records `policy_mode=baseline`.

## Local Probe

The local policy probe uses the 59 Phase 6E remaining bad cases and does not call an LLM, start a
service, or write Chroma.

Summary:

- `total_cases=59`
- `metadata_first_count=31`
- `sparse_first_count=7`
- `dense_sparse_fusion_count=10`
- `clarification_first_count=6`
- `citation_aware_count=5`
- `baseline_default_unchanged=true`
- `calls_llm=false`
- `writes_chroma=false`
- `recommended_hpc_full_eval=true`

Outputs:

- `data/knowledge_base/evaluation/phase6e5_local_policy_probe_results.jsonl`
- `data/knowledge_base/evaluation/phase6e5_local_policy_probe_summary.json`

## Current Limits

- The runtime metadata/sparse stage uses a bounded read-only Chroma scan. It is acceptable for the
  reviewed local corpus but still needs performance validation before wider use.
- Banned-source runtime filtering still depends on evaluation or request metadata providing banned
  source ids.
- The local probe verifies policy selection and wiring, not end-to-end answer quality.
- No production readiness claim is made.
- Not all bad cases are solved.

## Next Step

After manual review and checkpoint, Phase 6E-8 should run full API-level evaluation comparing
baseline, global query-type-aware, and gated query-type-aware mode. That step should validate
source hit, keyword hit, latency, fallback behavior, and banned-source safety under the real
retrieval path.
