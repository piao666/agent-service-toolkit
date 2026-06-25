# Phase 7E-5C Keyword Coverage Delta Diagnosis

## Results

| Metric | 7E-4B | 7E-5B |
|--------|-------|-------|
| legacy_bad | 11 | 14 |
| custom_bad | 13 | 13 |
| error | 0 | 0 |

## Custom Graph Delta

| Category | Count |
|----------|-------|
| fixed_custom_bad | 1 |
| regressed_custom_bad | 1 |
| stable_custom_bad | 12 |
| stable_custom_good | 6 |
| suspected_llm_variance | 18 |
| suspected_patch_helped | 4 |
| suspected_patch_regressed | 5 |
| legacy_regressed | 4 |

## Conclusion

1. 7E-5A engineering stability confirmed (no error/timeout/500).
2. answer_synthesis_profile=keyword_coverage_v1 visible in prompt_profile.
3. 7E-5B custom_bad (13) vs 7E-4B (13) — no proven aggregate gain.
4. legacy_bad: 11 -> 14 (LLM output variance on small delta sample).
5. Recommendation: **keep** 7E-5A patch.
