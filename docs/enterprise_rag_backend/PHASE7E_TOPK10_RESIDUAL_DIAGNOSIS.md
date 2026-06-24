# Phase 7E TopK=10 Residual Diagnosis

## Scope

This is an offline diagnosis of the Phase 7E top_k=10 delta-case run. It reads existing JSONL results only. It does not call an endpoint, does not call an LLM, does not run a full 240-case evaluation, and does not write Chroma.

## Input

```text
data\knowledge_base\evaluation\phase7e_delta_topk10_deepseek_results.jsonl
data\knowledge_base\evaluation\phase7e_delta_topk10_deepseek_summary.json
```

## Residual Delta

- only_custom_bad: 3
- only_custom_bad case ids: exp_041, exp_058, exp_134
- only_legacy_bad: 2
- only_legacy_bad case ids: exp_034, exp_193

## Only-Custom Root Cause Distribution

- answer_synthesis_diff: 3
- keyword_still_missing: 3
- source_serialization_not_persisted: 3

## Findings

- source_ordering_diff: False
- answer_synthesis_diff: True
- source_serialization_diff: True
- data_or_chunk_gap: False

The current result shows that top_k=10 is the best tested delta setting, but custom_graph still does not meet `custom_graph <= legacy` on the delta set.

## Recommendation

- Full 240 with top_k=10: False
- Source ordering small fix: False
- Answer prompt alignment: True
- Data/chunk optimization: False

## Boundary

This diagnosis does not claim custom_graph is better than legacy and does not represent a production benchmark.
