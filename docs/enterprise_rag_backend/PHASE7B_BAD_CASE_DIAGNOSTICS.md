# Phase 7B Bad-Case Diagnostics

## Goal

Phase 7B performs offline diagnostics on the Phase 7A after-fix DeepSeek 240-case regression files.
It does not call endpoints, invoke an LLM, rerun the 240-case set, or write Chroma.

## Inputs

- `data/knowledge_base/evaluation/phase7a_after_fix_deepseek_legacy_240_results.jsonl`
- `data/knowledge_base/evaluation/phase7a_after_fix_deepseek_legacy_240_summary.json`
- `data/knowledge_base/evaluation/phase7a_after_fix_deepseek_custom_240_results.jsonl`
- `data/knowledge_base/evaluation/phase7a_after_fix_deepseek_custom_240_summary.json`
- `data/knowledge_base/evaluation/phase7a_after_fix_deepseek_240_regression_summary.json`

## Important Metric Boundary

The Phase 7A summaries record the authoritative calibrated bad-case counts:

- legacy `bad_case_count=49`
- custom_graph `bad_case_count=49`

The result JSONL rows also expose lower-level diagnostic signals such as `source_hit`,
`keyword_hit`, `doc_type_hit`, schema validity, runtime errors, and timeouts. These visible fields
are useful for diagnosing failure patterns, but they are not identical to the calibrated
bad-case metric.

The persisted summary includes only the available `bad_case_ids` list. Therefore, Phase 7B reports:

- calibrated bad-case totals from the summary,
- available bad-id overlap from persisted IDs,
- diagnostic bad proxy overlap from visible row-level signals.

This avoids inventing missing calibrated bad-case IDs.

## Diagnostics Performed

The script `scripts/analyze_phase7b_bad_cases.py` computes:

- legacy and custom_graph calibrated bad-case totals,
- available shared / only-legacy / only-custom bad-case IDs,
- source miss, keyword miss, doc-type miss, empty answer, schema invalid, error, and timeout counts,
- multi-hop case count and multi-hop diagnostic bad proxy count,
- planner-type distribution inferred from query type when raw planner debug is not persisted,
- judge verdict distribution, marked as not persisted when raw judge debug is absent,
- top visible bad-case patterns.

## Current Findings

The Phase 7A after-fix regression is stable:

- legacy and custom_graph both finish with `error_count=0` and `timeout_count=0`.
- legacy calibrated bad-case count remains 49.
- custom_graph calibrated bad-case count remains 49.
- custom_graph no longer has the previous 500 failure mode.

The visible row-level diagnostics show that many remaining cases are retrieval evidence issues,
especially source/doc-type misses. This supports investigating source selection, metadata evidence,
and evaluation alignment before changing planner policy again.

## Limitations

- This is offline analysis only.
- It does not rerun retrieval or generation.
- It does not inspect raw server logs.
- Raw `planner_debug` and `judge_debug` objects are not persisted in the available Phase 7A JSONL
  rows, so planner and judge distributions are inferred or marked as not persisted.
- It does not prove that custom_graph is better than legacy.

## Recommended Next Actions

1. Preserve Phase 7A as a stability and observability fix.
2. Use Phase 7B patterns to prioritize source/doc-type miss investigation.
3. Persist raw planner and judge debug fields in future large evaluations if deeper graph-level
   diagnostics are required.
4. Avoid additional planner-policy changes until the dominant retrieval evidence patterns are
   understood.
