# Phase 7E Answer / Source Alignment Plan

## Why This Is Needed

Phase 7E top_k diagnostics showed that `top_k=10` is the best current delta-case configuration, but custom_graph still has a residual gap:

```text
legacy bad=11
custom_graph bad=12
only_custom_bad=3
```

The current JSONL artifacts contain enough scoring/debug fields to identify the remaining case ids, but they do not persist answer previews, source previews, source ordering, or prompt/config profiles. Without those fields, later diagnosis cannot distinguish answer synthesis differences from source ordering or serialization differences.

## Current Data Gap

The current residual diagnosis can identify that `exp_041`, `exp_058`, and `exp_134` remain only_custom_bad at `top_k=10`, but cannot safely inspect:

1. legacy versus custom_graph answer wording.
2. source_id / doc_type / chunk_id order.
3. top source content previews.
4. prompt/config profile differences.

## Instrumentation Scope

Phase 7E-4A only strengthens evaluation result persistence. It does not change system strategy.

The enriched runner now persists:

```text
answer_preview
answer_chars
answer_sha256
source_previews
source_id_sequence
doc_type_sequence
chunk_id_sequence
prompt_profile
```

Full answers and full chunks are not persisted. Only bounded previews, metadata, lengths, and hashes are stored.

## Follow-up HPC Run

The next run should be a small delta-case run, not a full 240-case run. It should generate:

```text
data/knowledge_base/evaluation/phase7e_answer_source_topk10_results.jsonl
data/knowledge_base/evaluation/phase7e_answer_source_topk10_summary.json
```

After those files exist, `scripts/analyze_phase7e_answer_source_alignment.py` can compare answer previews and source sequences.

## Decision Rules

If the same sources are retrieved but answers diverge, investigate prompt alignment.

If source order differs, investigate a small source ordering fix.

If source or doc type is still missing, move toward data, chunk, or retrieval coverage work.

## Boundary

This phase does not call endpoints locally, does not call an LLM, does not run 240 cases, does not write Chroma, and does not claim production readiness or complete bad-case resolution.
