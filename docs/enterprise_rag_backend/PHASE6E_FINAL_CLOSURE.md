# Phase 6E Final Closure

## Scope

Phase 6E explored query-type-aware retrieval policy variants and evaluated whether policy-level
routing could reduce the remaining calibrated bad cases without hurting the full evaluation set.

This closure document only summarizes completed Phase 6E results. It does not start Phase 6F, does
not modify production Agent/API behavior, does not run a new evaluation, does not call an LLM, and
does not write Chroma.

## Policy Variants

Phase 6E covered the following policy variants:

- Phase 6E-6: global `query_type_aware`
- Phase 6E-8: gated policy
- Phase 6E-10: conservative gate
- Phase 6E-11: targeted overlay
- Phase 6E-12: bad-case root cause audit

## Phase 6E-6: Global Query-type-aware

59-case result:

- Baseline `bad_case_count=40`
- Global `query_type_aware bad_case_count=33`

240-case result:

- Baseline `bad_case_count=62`
- Global `query_type_aware bad_case_count=71`

Conclusion: global `query_type_aware` improved the targeted 59-case bad-case set, but it regressed
on the 240-case full set. It cannot replace baseline globally.

## Phase 6E-8: Gated Policy

59-case result:

- Baseline `bad_case_count=39`
- Gated `bad_case_count=33`

240-case result:

- Baseline `bad_case_count=61`
- Gated `bad_case_count=72`

Conclusion: gated policy reproduced the same tradeoff as global `query_type_aware`: targeted
bad-case improvement with full-set regression.

## Phase 6E-10: Conservative Gate

59-case result:

- Baseline `bad_case_count=40`
- Conservative `bad_case_count=40`

240-case result:

- Baseline `bad_case_count=59`
- Conservative `bad_case_count=75`

Conclusion: conservative gate was too conservative to preserve targeted improvement, and it still
regressed on the 240-case full set.

## Phase 6E-11: Targeted Overlay

59-case quick-eval result:

- Baseline `source_hit_rate=0.2321`
- Targeted overlay `source_hit_rate=0.25`
- Baseline `bad_case_count=40`
- Targeted overlay `bad_case_count=39`

Conclusion: targeted overlay was safer but too weak. It reduced only one bad case and did not meet
the threshold for running 240-case full evaluation. It should be recorded as a negative or
weak-improvement experiment, not as a successful final strategy.

## Phase 6E-12: Bad-case Root Cause Audit

Total analyzed cases: 59.

Root cause distribution:

- `expected_source_exists_but_not_retrieved`: 43 cases, 73%
- `chunk_too_noisy_or_too_broad`: 31 cases, 53%
- `needs_metadata_index`: 22 cases, 37%
- `chunk_too_small_or_context_missing`: 7 cases, 12%
- `evaluator_too_strict_or_misaligned`: 6 cases, 10%
- `needs_citation_verifier`: 5 cases, 8%
- `needs_code_symbol_index`: 4 cases, 7%
- `needs_query_decomposition`: 3 cases, 5%
- `corpus_expansion`: 0 cases

The audit indicates that the main bottleneck is not complete corpus absence. Most expected sources
exist, but they are not accurately retrieved or are buried in noisy chunks. Pure policy tuning has
reached a bottleneck. A policy-only path is expected to fix only about 7 to 10 bad cases.

## Final Conclusion

Phase 6E fully explored query-type-aware, gated, conservative, and targeted-overlay retrieval
policies. The strongest policy result was Phase 6E-6 global `query_type_aware`, which improved the
59-case targeted set but degraded the 240-case full set.

Later conservative policies did not simultaneously preserve 59-case improvement and avoid 240-case
regression. Phase 6E-12 shows that the next meaningful improvement should come from structured
retrieval infrastructure rather than continued policy tuning.

Phase 6E does not claim:

- production readiness
- all bad cases solved
- clear 240-case improvement
- `bad_case_count` below 30

## Recommended Phase 6F Direction

Recommended Phase 6F direction: Structured Retrieval Infrastructure.

Candidate work items:

- metadata index
- code/config symbol index
- citation verifier
- chunk/evidence cleanup
- query decomposition for multi-hop cases
