# Phase 7E Top-K Source Coverage Matrix

## Scope

Phase 7E tested top_k as a control variable on the prepared delta cases. The fixed configuration was:

```text
multi-hop=off
planner=debug_only
judge=rule_based_fallback
verifier=rule_based
```

This phase focuses on delta-case source coverage. It is not a full 240-case run and does not write Chroma.

## Matrix Result

| top_k | legacy bad | custom_graph bad | gap | only_custom | custom <= legacy |
| ---: | ---: | ---: | ---: | ---: | --- |
| 5 | 12 | 16 | +4 | 5 | false |
| 8 | 10 | 15 | +5 | 6 | false |
| 10 | 11 | 12 | +1 | 3 | false |

## Conclusion

`top_k=10` is the best setting in this delta-case matrix, reducing the custom_graph gap to +1.

However, custom_graph still does not meet the `custom_graph <= legacy` threshold. Therefore, this result does not justify moving directly to a full 240-case rerun.

## Next Diagnostic Step

The next step is Phase 7E-3: inspect the remaining `top_k=10` only_custom_bad cases:

```text
exp_041
exp_058
exp_134
```

The goal is to determine whether the residual gap is caused by source ordering, answer synthesis, source serialization, evaluator threshold, or data/chunk coverage.

## Boundary

This matrix does not claim custom_graph is better than legacy and does not represent a production benchmark. It is a controlled delta-case diagnostic only.
