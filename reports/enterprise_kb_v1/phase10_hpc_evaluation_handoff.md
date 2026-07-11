# Phase 10 HPC Evaluation Handoff

This handoff does not execute an HPC job. It identifies the existing entrypoints
and the evidence that must return before a new success claim is made.

## Existing inputs

- Evaluation script: scripts/enterprise_kb_v1/run_phase6f_multichannel_retrieval_eval.py
- Config smoke: scripts/enterprise_kb_v1/smoke_phase6f_eval_config.py
- Command reference: reports/enterprise_kb_v1/phase6f_hpc_run_commands.md
- Gold corrections: reports/enterprise_kb_v1/phase6f_gold_correction_notes.md
- Historical result: reports/enterprise_kb_v1/phase6f_multichannel_retrieval_eval_results.json
- Historical per-case evidence: reports/enterprise_kb_v1/phase6f_per_case_results.jsonl

## Required rerun order

1. Sync the committed backend code to the existing HPC checkout.
2. Verify both existing Chroma indexes and configured bge-m3 model paths.
3. Run the Phase 6F config smoke before the evaluation.
4. Use the exact command and environment documented in phase6f_hpc_run_commands.md.
5. Return both the aggregate JSON and per-case JSONL; an aggregate report alone is insufficient.
6. Compare case count, expected-source coverage, index counts, warnings, failed cases, and route metric note.
7. Treat any missing index, missing per-case evidence, or changed denominator as a failed or insufficient-evidence run.

## Acceptance fields

- environment must identify HPC
- indices_ready must be true
- total_cases and cases_with_expected_sids must be present
- official and internal chunk counts must be present
- baseline, multichannel, and delta metrics must be present
- dual_accuracy and citation_validity must be present
- failed_case_count and warnings must be present
- overall_pass must be recomputed by the script
- per-case output must cover every declared case

## Separate real-provider rerun

After repairing the qwen-max HTTP 403, run the Graph API with
ALLOW_LLM_FALLBACK=false and record requested provider/model, actual
provider/model, fallback_used, HTTP status, citations, citation semantic
support, and memory traces. Never include API keys or AUTH_SECRET in logs.
