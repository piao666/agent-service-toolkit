# Phase 3H Batch 1 Text/DOM Capture Report

> time: 2026-07-05T16:37:20.310479+08:00 | batch: 1 | sources: 5
> all_pass: True

## Summary

| source_id | HTTP | HTML | MD | headings | code | tables | quality |
|-----------|:----:|-----:|----:|:--------:|:----:|:------:|:-------:|
| fastapi_official_routing | 200 | 151KB | 12KB | 20 | 15 | 0 | **pass** |
| fastapi_official_request_body | 200 | 131KB | 9KB | 11 | 8 | 0 | **pass** |
| fastapi_official_dependency_injection | 200 | 141KB | 14KB | 14 | 10 | 0 | **pass** |
| fastapi_official_middleware | 200 | 112KB | 5KB | 5 | 3 | 0 | **pass** |
| fastapi_official_error_handling | 200 | 156KB | 15KB | 13 | 16 | 0 | **pass** |

## Quality gates

| source_id | raw.html | normalized.md | text_metadata.json | audit.json | G1 heading | G2 code | G3 table |
|-----------|:--:|:--:|:--:|:--:|:--:|:--:|:--:|
| fastapi_official_routing | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| fastapi_official_request_body | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| fastapi_official_dependency_injection | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| fastapi_official_middleware | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| fastapi_official_error_handling | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |

## Constraints check

| Constraint | Status |
|------------|:------:|
| Only Batch 1 processed | ✅ |
| Qwen excluded | ✅ |
| No crawl | ✅ (single URL per source) |
| No screenshots | ✅ |
| No Chroma/embedding/index | ✅ |
| Registry/allowlist unmodified | ✅ |
| No source enabled | ✅ |