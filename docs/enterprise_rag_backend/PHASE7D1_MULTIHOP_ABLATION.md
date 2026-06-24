# Phase 7D-1 Multi-hop Ablation

## Scope

Phase 7D-1 evaluates a custom graph ablation with multi-hop retrieval disabled through configuration.

This run used the existing 240-case DeepSeek regression setup and did not introduce a new retrieval strategy. It only checks whether disabling the Phase 7A multi-hop branch reduces the custom graph regression gap.

## Configuration Change

The runtime adds:

```text
ENTERPRISE_MULTI_HOP_MODE=off|rule_based
```

The default is `off` for this ablation path. When the planner marks a query as requiring multi-hop and the mode is `off`, the graph records this in `planner_debug` and routes to the normal retriever.

## Result Summary

Phase 7D-1 result:

```text
multi_hop_enabled: 20 -> 0
custom_graph bad_case_count: 105 -> 101
legacy bad_case_count: 100 -> 97
only_custom_bad: 9
only_legacy_bad: 5
error_count: 0
timeout_count: 0
writes_chroma: false
runs_benchmark: false
```

The custom graph improved after disabling multi-hop, but it still did not fully match the legacy path:

```text
custom_graph bad_case_count = 101
legacy bad_case_count = 97
```

## Interpretation

Multi-hop retrieval was one source of regression, but it was not the only source. Disabling it reduced custom graph bad cases by 4, while a residual delta remains between custom graph and legacy.

The remaining gap should be analyzed with per-case diagnostics before changing planner, judge, retriever ordering, or answer generation behavior.

## Boundary

This is an ablation result, not a production benchmark. It does not claim the custom graph is better than legacy, and it does not claim all bad cases are resolved.

## Recommended Next Step

Run Phase 7D-1b residual delta diagnosis to inspect:

- only-custom bad cases
- only-legacy bad cases
- planner side effects
- judge side effects
- retrieval ordering differences
- source/doc type/keyword miss patterns
