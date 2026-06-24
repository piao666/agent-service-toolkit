# Phase 7D-4A Delta Verifier / Judge Matrix

## Scope

Phase 7D-4A is a local/HPC-returned delta-case matrix check for verifier and judge settings. It does not rerun the full 240-case benchmark in this repository step, does not write Chroma, and does not change the core retrieval strategy.

The goal is to test whether verifier / judge toggles can close the remaining custom_graph versus legacy residual gap after Phase 7D-3.

## Tested Configurations

The matrix compared four verifier / judge combinations on the Phase 7D delta cases:

| Variant | Verifier | Judge | Legacy bad | Custom bad | Gap | Custom <= legacy |
| --- | --- | --- | ---: | ---: | ---: | --- |
| v_on_j_on | rule_based | rule_based_fallback | 3 | 6 | 3 | false |
| v_on_j_off | rule_based | off | 3 | 7 | 4 | false |
| v_off_j_off | off | off | 5 | 7 | 2 | false |
| v_off_j_on | off | rule_based_fallback | 2 | 5 | 3 | false |

## Result

No verifier / judge combination made custom_graph less than or equal to legacy on this delta matrix.

The smallest observed gap was `v_off_j_off`, but it still left custom_graph worse than legacy and is not a sufficient candidate for full 240-case rerun by itself.

## Interpretation

Verifier / judge tuning does not appear to resolve the Phase 7D-3 residual gap. The current best tested configuration remains Phase 7D-3:

```text
multi-hop=off
planner=debug_only
judge=on
```

The next diagnostic direction should move away from verifier / judge toggles and toward source coverage / retrieval top_k control-variable testing.

## Boundary

This result is diagnostic only. It does not claim production readiness, does not prove custom_graph is better than legacy, and does not replace a full 240-case evaluation.
