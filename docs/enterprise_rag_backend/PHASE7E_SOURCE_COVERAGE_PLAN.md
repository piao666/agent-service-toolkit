# Phase 7E Source Coverage / Top-K Plan

## Why Phase 7E

Phase 7D-4A tested verifier and judge combinations on delta cases. No combination made custom_graph less than or equal to legacy, so verifier / judge tuning is not the next best direction.

The current best tested configuration remains Phase 7D-3:

```text
multi-hop=off
planner=debug_only
judge=on
```

The remaining gap should be investigated as a source coverage and retrieval top_k control-variable issue before changing retrieval strategy again.

## Fixed Variables

Phase 7E should keep the following variables fixed:

```text
multi-hop=off
planner=debug_only
judge=rule_based_fallback
verifier=rule_based
```

The goal is to isolate whether changing source coverage alone changes the delta cases.

## Control Variable

Phase 7E should test:

```text
top_k=5
top_k=8
top_k=10
```

The first run should use delta cases only. It should not start with a full 240-case evaluation.

## Prepared Case Selection

The preparation script writes:

```text
data/knowledge_base/evaluation/phase7e_topk_delta_cases.jsonl
data/knowledge_base/evaluation/phase7e_topk_source_coverage_plan.json
```

The case file includes:

1. only_custom_bad cases.
2. only_legacy_bad cases.
3. representative shared bad cases with source/doc-type miss signals, capped at 20 cases.

## Decision Rule

If increasing top_k reduces only_custom_bad cases without adding comparable only_legacy regressions, then a full 240-case rerun is worth considering.

If top_k does not improve the delta cases, avoid another full run and move to more targeted source ranking or evidence ordering diagnostics.

## Boundary

This is a preparation step only. It does not call an endpoint, does not call a real LLM, does not run 240 cases, and does not write Chroma. It does not claim production readiness or complete bad-case resolution.
