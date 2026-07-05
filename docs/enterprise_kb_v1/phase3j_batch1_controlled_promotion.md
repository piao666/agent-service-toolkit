# Phase 3J Batch 1 Controlled Promotion Report

> time: 2026-07-05T16:49:24.481781+08:00 | promoted: 5 | anchor-safe: True | validation errors: 0

## Promoted sources

| source_id | fetch_status | promotion_status | capture_batch | enabled | allowed_for_answer | text_capture.status |
|-----------|-------------|------------------|---------------|:------:|:------------------:|:-------------------:|
| fastapi_official_routing | captured | approved_for_text_dom_corpus | phase3h_batch1 | False | False | captured |
| fastapi_official_request_body | captured | approved_for_text_dom_corpus | phase3h_batch1 | False | False | captured |
| fastapi_official_dependency_injection | captured | approved_for_text_dom_corpus | phase3h_batch1 | False | False | captured |
| fastapi_official_middleware | captured | approved_for_text_dom_corpus | phase3h_batch1 | False | False | captured |
| fastapi_official_error_handling | captured | approved_for_text_dom_corpus | phase3h_batch1 | False | False | captured |

## Non-Batch1 contamination check

All 16 non-Batch1 external_official sources verified clean.
See `phase3j_non_batch_unchanged_check.txt` for per-source detail.

| Check | Result |
|-------|:------:|
| Anchor broken for Batch 1 | Yes (deepcopy text_capture) |
| Non-Batch1 text_capture.status all not_fetched | True |
| Non-Batch1 no promotion fields | True |
| external_official = 21 | True |
| verified = 19 | True |
| needs_manual_review = 2 | True |
| Validation errors | 0 |

## Constraints

| Constraint | Status |
|------------|:------:|
| Only metadata promotion | Yes |
| No URL scraping | Yes |
| No index created | True |
| Enabled still false | True |