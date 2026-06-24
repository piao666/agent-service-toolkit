# Phase 7D-1b Residual Delta Diagnosis

## Scope

This diagnosis reads the existing Phase 7D-1 enriched JSONL and summary files only. It does not call endpoints, does not invoke an LLM, does not run 240-case evaluation again, and does not write Chroma.

## Input

- `data/knowledge_base/evaluation/phase7d1_multihop_off_deepseek_240_results.jsonl`
- `data/knowledge_base/evaluation/phase7d1_multihop_off_deepseek_240_summary.json`

## Delta Counts

```text
legacy bad_case_count = 97
custom_graph bad_case_count = 101
only_custom_bad = 9
only_legacy_bad = 5
```

## Only Custom Bad Cases

```text
exp_003, exp_021, exp_029, exp_041, exp_058, exp_062, exp_078, exp_118, exp_174
```

## Only Legacy Bad Cases

```text
exp_034, exp_035, exp_039, exp_093, exp_185
```

## Only Custom Root-Cause Distribution

- judge_side_effect: 6
- keyword_miss: 9
- planner_side_effect: 1

## Side-Effect Signals

```text
planner_side_effect_found = True
judge_side_effect_found = True
retrieval_order_diff_found = False
```

## Recommendations

- Run judge ablation before changing retrieval policy because only-custom deltas include judge_side_effect signals.
- Run planner debug-only ablation if planner_side_effect persists after judge ablation.
- Inspect answer generation and source ordering for only-custom deltas that have retrieval_order_diff.
- Defer conservative multi-hop gate changes until judge/planner residual deltas are isolated.

## Boundary

This is a residual delta diagnosis, not a production benchmark. It does not claim custom_graph is better than legacy and does not claim all bad cases are resolved.
