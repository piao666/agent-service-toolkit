# Phase 7E Answer / Source Alignment Diagnosis

## Scope

This document summarizes an offline diagnosis of Phase 7E-4B answer/source persistence results. It reads JSONL artifacts only. It does not call an endpoint, does not call an LLM, does not run a full 240-case evaluation, and does not write Chroma.

## Overview

- case_count: 20
- request_count: 40
- legacy_bad: 11
- custom_graph_bad: 13
- shared_bad: 9
- only_custom_bad: 4
- only_legacy_bad: 2
- custom_graph_error_count: 0
- legacy_error_count: 0

## Delta Cases

- only_custom_bad case ids: exp_034, exp_041, exp_058, exp_193
- only_legacy_bad case ids: exp_039, exp_059

## Only-Custom Root Cause Distribution

- custom_missing_keyword_in_answer: 4
- legacy_keyword_present_custom_missing: 3
- same_sources_answer_diff: 4
- suspected_stochastic_or_synthesis_diff: 4

## Alignment Signals

- same_sources_answer_diff_count: 4
- source_order_diff_count: 0
- source_serialization_diff_count: 0
- source_missing_or_doc_type_gap_count: 0
- prompt_profile_diff_count: 0
- suspected_stochastic_or_synthesis_diff_count: 4

## Interpretation

custom_graph has no error or timeout in this delta run, but it still does not match legacy on bad-case count. If same-source answer differences dominate, the next diagnostic direction should be answer synthesis behavior. If source order differences dominate, source ordering should be inspected. If source/doc-type gaps dominate, the issue should move back to retrieval/data/chunk coverage.

This diagnosis does not claim custom_graph is better than legacy and does not justify a full 240-case top_k=10 run by itself.
