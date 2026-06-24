# Phase 7C Evaluation Instrumentation

## Goal

Phase 7C-1 prepares enriched evaluation instrumentation for a future DeepSeek 240-case rerun.
It does not rerun the 240-case set locally, call a real LLM, write Chroma, or change the core
retrieval / planner / judge strategy.

## Why This Phase Is Needed

Phase 7B showed that the Phase 7A after-fix regression artifacts were useful for high-level
comparison but incomplete for detailed bad-case diagnosis:

1. The summary persisted calibrated bad-case counts but not the full calibrated bad-case ID sets.
2. `judge_debug` was not preserved in the 240-case JSONL rows.
3. `planner_debug`, multi-hop status, and `graph_debug` were summarized but not consistently
   available per case.
4. Shared / only-legacy / only-custom bad cases had to rely partly on proxy signals instead of
   complete calibrated labels.

Because of these gaps, the correct next step is instrumentation. Changing retrieval policy or graph
strategy without richer evidence would risk tuning against incomplete diagnostics.

## New Enriched Regression Runner

Phase 7C adds:

```text
scripts/run_phase7c_deepseek_240_regression_enriched.py
```

The runner is designed for a future HPC run against two running endpoint instances:

- legacy service
- custom_graph service

It requires `--execute` before it sends any endpoint requests. Without `--execute`, it only prints a
skipped summary and does not call endpoints.

## Per-Case Fields

Each enriched result row is designed to preserve:

- `case_id`
- `mode`
- `query`
- `query_type`
- `expected_source_id`
- `expected_doc_type`
- `expected_keywords`
- `answer_non_empty`
- `schema_valid`
- `source_count`
- `source_hit`
- `doc_type_hit`
- `keyword_hit`
- `bad_case`
- `bad_case_reasons`
- `calibrated_bad_case`
- `calibrated_bad_case_reasons`
- `latency_ms`
- `error`
- `timeout`
- `retrieval_debug`
- `verifier_debug`
- `planner_debug`
- `judge_debug`
- `graph_debug`
- `nodes_executed`
- `planner_type`
- `requires_multi_hop`
- `multi_hop_enabled`
- `judge_verdict`

For custom_graph rows, it also records graph observability fields such as `graph_debug_present`,
`graph_mode`, `nodes_executed_count`, `planner_present`, and `judge_present`.

## Summary Fields

The enriched summary persists complete ID sets:

- `legacy_bad_case_ids`
- `custom_graph_bad_case_ids`
- `legacy_calibrated_bad_case_ids`
- `custom_graph_calibrated_bad_case_ids`
- `shared_bad_case_ids`
- `only_legacy_bad_case_ids`
- `only_custom_graph_bad_case_ids`
- `shared_calibrated_bad_case_ids`
- `only_legacy_calibrated_bad_case_ids`
- `only_custom_graph_calibrated_bad_case_ids`

It also records source miss, doc-type miss, keyword miss, multi-hop, planner, and judge
distributions.

## Analyzer Compatibility

`scripts/analyze_phase7b_bad_cases.py` now supports two sources:

- `diagnostics_source=old_proxy`: existing Phase 7A after-fix artifacts are used.
- `diagnostics_source=enriched`: Phase 7C enriched artifacts are used when present.

When enriched artifacts are present, shared / only bad-case analysis uses real persisted bad-case
IDs instead of proxy overlap.

## Boundaries

- No local DeepSeek call in Phase 7C-1.
- No local 240-case run in Phase 7C-1.
- No Chroma write.
- No core RAG, planner, judge, retriever, or service logic change.
- No claim that custom_graph is better than legacy.

## Next Step

Claude Code can run the enriched script on HPC after starting separate legacy and custom_graph
services. The resulting enriched JSONL and summary should then be used for a stronger Phase 7B-style
bad-case diagnosis.
