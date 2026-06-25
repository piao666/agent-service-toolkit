# Phase 7E Final Consolidation & Freeze

## 1. Scope

| Phase | Content |
|-------|---------|
| 7A | Planner + Multi-hop + Judge Prototype |
| 7B | Bad-case Diagnostics |
| 7C | Enriched Evaluation Instrumentation (240-case) |
| 7D | Ablation Experiments (multi-hop, judge, planner) |
| 7E | Top-K / Source Coverage / Answer-Source Alignment / Keyword Coverage Diagnosis |

## 2. Final Conclusions

1. custom_graph is **engineering-stable**: no error/timeout/500 in any Phase 7 evaluation.
2. custom_graph's primary value is **observability**: graph_debug, nodes_executed, planner_debug, judge_debug, answer_synthesis_profile.
3. **Legacy remains the stable baseline**; custom_graph does not claim superiority.
4. custom_graph does **not** universally outperform legacy on calibrated bad_case.
5. **Multi-hop showed no benefit** in Phase 7; it was a contributor to regression (7D-1 ablation: custom bad 105→101).
6. **Planner active mode had negative side effects**; debug_only is preferred (7D-3: gap narrowed to +1).
7. **Verifier/judge tuning did not resolve the residual gap** (7D-2: judge off made custom worse, 107).
8. **top_k=10 is best on delta cases** (gap +1, only_custom=3) but does not justify full 240 or production claims.
9. **Answer/source persistence is complete** (7E-4B), supporting future diagnostics.
10. **Keyword coverage patch (7E-5A) is engineering-stable** with answer_synthesis_profile=keyword_coverage_v1 observable, but aggregate quality gain is unproven.
11. **7E-5C diagnosis**: fixed_custom_bad=1, regressed_custom_bad=1, stable=12, good=6 — net neutral.
12. **Current recommendation**: keep keyword_coverage_v1 profile, **stop** prompt/keyword coverage expansion.

## 3. Key Results Table

### Phase 7C: Enriched 240-case Baseline

| Metric | legacy | custom_graph |
|--------|--------|-------------|
| calibrated bad | 100 | 105 |
| shared bad | 94 | 94 |
| only bad | 6 | 11 |
| multi_hop_enabled | 0 | 20 |
| multi_hop_bad | 0 | 11 |

### Phase 7D Ablation Series

| Phase | multi_hop | judge | planner | legacy | custom | gap | only_custom |
|-------|-----------|-------|---------|--------|--------|-----|-------------|
| 7C | on | on | active | 100 | 105 | +5 | 11 |
| 7D-1 | off | on | active | 97 | 101 | +4 | 9 |
| 7D-2 | off | off | active | 100 | 107 | +7 | 12 |
| 7D-3 🥇 | off | on | debug_only | 102 | 103 | **+1** | **6** |

### Phase 7E Top-K Delta Matrix (20 delta cases)

| top_k | legacy | custom | gap | only_custom |
|-------|--------|--------|-----|-------------|
| 5 | 12 | 16 | +4 | 5 |
| 8 | 10 | 15 | +5 | 6 |
| 10 🥇 | 11 | 12 | **+1** | **3** |

### Phase 7E Answer/Source Alignment (7E-4B)

| Metric | Value |
|--------|-------|
| case_count | 20 |
| legacy_bad | 11 |
| custom_bad | 13 |
| error | 0 |
| persistence fields | all present |

### Phase 7E-5B Keyword Coverage Rerun

| Metric | 7E-4B | 7E-5B |
|--------|-------|-------|
| legacy_bad | 11 | 14 |
| custom_bad | 13 | 13 |
| only_custom_bad | — | 2 |
| answer_synthesis_profile | — | keyword_coverage_v1 |

### Phase 7E-5C Diagnosis

| Category | Count |
|----------|-------|
| fixed_custom_bad | 1 |
| regressed_custom_bad | 1 |
| stable_custom_bad | 12 |
| stable_custom_good | 6 |
| custom_answer_sha256_changed | 18/20 |
| custom_source_sequence_changed | 0 |
| recommendation | **keep** |

## 4. Frozen Configuration

```
ENTERPRISE_AGENT_GRAPH_MODE=custom_graph
ENTERPRISE_MULTI_HOP_MODE=off
ENTERPRISE_PLANNER_MODE=debug_only
ENTERPRISE_JUDGE_MODE=rule_based_fallback
ENTERPRISE_LLM_JUDGE_MODE=rule_based_fallback
ENTERPRISE_EVIDENCE_VERIFIER_MODE=rule_based
ENTERPRISE_STRUCTURED_RETRIEVAL_MODE=metadata_symbol
ENTERPRISE_MEMORY_MODE=buffer
RAG_DEFAULT_TOP_K=10 (for delta diagnosis; demo default per project config)
```

## 5. What NOT to Continue

1. ❌ Conservative multi-hop gate
2. ❌ Verifier/judge tuning for residual gap
3. ❌ Expanding prompt keyword coverage
4. ❌ Full 240-case with current config
5. ❌ Claiming custom_graph quality superiority over legacy
6. ❌ Over-fitting on 20 delta cases

## 6. Next: Phase 8 — Demo / Interview / Resume Packaging

1. Streamlit demo script polish
2. Stable demo query set
3. graph_debug showcase
4. answer/source persistence showcase
5. Controlled ablation storyline
6. Resume project description
7. Interview Q&A: why legacy kept, why custom_graph not replacing legacy, why multi-hop abandoned, why keyword_coverage_v1 kept
