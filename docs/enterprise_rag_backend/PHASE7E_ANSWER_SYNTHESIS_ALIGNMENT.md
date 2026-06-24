# Phase 7E-5A Answer Synthesis / Keyword Coverage Alignment

## Background

Phase 7E-4C analyzed the persisted answer/source artifacts from the Phase 7E-4B
top_k=10 delta run. The diagnosis found:

- only_custom_bad case ids: `exp_034`, `exp_041`, `exp_058`, `exp_193`
- only_legacy_bad case ids: `exp_039`, `exp_059`
- same_sources_answer_diff_count: `4`
- source_order_diff_count: `0`
- source_serialization_diff_count: `0`
- prompt_profile_diff_count: `0`
- suspected_stochastic_or_synthesis_diff_count: `4`

The residual gap is therefore more consistent with answer synthesis / keyword
coverage differences than with retrieval, source ordering, source serialization,
prompt profile, or data/chunk coverage gaps.

## Scope

Phase 7E-5A makes a minimal custom_graph-only answer synthesis patch. It does not:

- change retrieval;
- change Chroma;
- change chunking or embeddings;
- change source ordering;
- change source serialization;
- tune verifier or judge behavior;
- re-enable multi-hop;
- change the legacy endpoint path.

## Implementation

The custom_graph answer generator now builds a bounded keyword coverage hint before
calling the configured model. The hint asks the model to:

- answer only from retrieved context;
- preserve relevant API names, config keys, function names, parameters, document
  types, and source terms from the evidence;
- naturally cover key user/source terms when useful;
- avoid introducing facts outside sources;
- say the evidence is insufficient when the sources do not support an answer.

The profile is exposed as:

```text
answer_synthesis_profile = keyword_coverage_v1
answer_synthesis_mode = keyword_coverage_v1
```

This is added to custom_graph debug/model metadata so later enriched evaluation can
attribute result rows to this answer synthesis mode.

## Local Validation

The local default custom_graph endpoint smoke now verifies:

- the keyword coverage instruction exists;
- the profile marker exists;
- empty-source instruction construction is safe;
- source_id sequence is unchanged by the instruction helper;
- custom_graph endpoint responses expose the answer synthesis profile.

## Next Step

Phase 7E-5B should rerun the top_k=10 delta cases on HPC with the same fixed
controls:

- multi-hop=off
- planner=debug_only
- judge=rule_based_fallback
- verifier=rule_based

This patch does not claim that custom_graph is better than legacy. It only prepares
a conservative answer synthesis alignment candidate for controlled delta-case
verification.
