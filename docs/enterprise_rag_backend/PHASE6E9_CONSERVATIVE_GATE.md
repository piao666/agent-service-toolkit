# Phase 6E-9 Conservative Gate

## Phase 6E-8 Finding

Phase 6E-8 full API-level re-evaluation showed that gated policy still helps the targeted bad-case
set but still hurts the full evaluation set.

59 remaining bad cases:

- baseline `source_hit=0.25`
- gated `source_hit=0.3571`
- baseline `bad_case=39`
- gated `bad_case=33`
- baseline latency `1762 ms`
- gated latency `1786 ms`

240-case full:

- baseline `source_hit=0.6938`
- gated `source_hit=0.6411`
- baseline `bad_case=61`
- gated `bad_case=72`
- baseline latency `2189 ms`
- gated latency `2251 ms`

## Why Phase 6E-7 Was Still Too Broad

The Phase 6E-7 gate still allowed ordinary API documentation questions to trigger sparse-first
retrieval. For example, a normal question such as "FastAPI 里 Request Body 如何定义？" should be
handled as ordinary documentation QA, not as a code/config lookup. Broad sparse-first routing can
mis-rank semantically relevant documentation chunks.

## Conservative Gate Rules

The conservative gate is precision-first. Specialized policy is enabled only when the query has a
strong signal.

### Metadata-first

`metadata_first` is enabled only when the query contains strong metadata signals such as:

- `source_id`
- `chunk_id`
- `doc_type`
- `domain`
- `title`
- `section_path`
- `source_url`
- `normalized_id`
- `metadata`
- `文档类型`
- `来源编号`
- `chunk 编号`
- `source id`

Otherwise `exact_metadata_lookup` falls back to baseline.

### Sparse-first

`sparse_first_bm25` is enabled only for strong code/API/config signals, such as:

- explicit API path like `/items/{id}`
- filenames such as `.py`, `.json`, `.yaml`, `.yml`
- function calls such as `foo()`
- class declarations such as `class Foo`
- config/env/环境变量/参数/字段/endpoint/schema/错误码
- uppercase config constants, underscore variables, camelCase names, HTTP methods, or status codes

Normal documentation questions about FastAPI concepts fall back to baseline.

### Citation-aware

`citation_aware_evidence` is enabled only when the query explicitly asks for citation/source
evidence with terms such as:

- `引用`
- `出处`
- `来源`
- `证据`
- `citation`
- `source`
- `reference`

## Forced Baseline Query Types

The following query types stay baseline unless a strong signal is detected by the conservative
gate:

- `zh_knowledge`
- `en_api_doc`
- `mixed_zh_en_api`
- `agent_rag_concept`
- `phase6c_bad_case_regression`
- `ambiguous_query`
- `multi_hop_lookup`
- `negative_banned_source`

`ambiguous_query` still records clarification debug, but retrieval is not replaced.

## Local Probe

The Phase 6E-9 local probe reads the same 59 remaining cases and checks routing decisions only. It
does not start a service, call an LLM, or write Chroma.

Summary:

- `total_cases=59`
- `conservative_gate_enabled_count=28`
- `fallback_to_baseline_count=31`
- `metadata_first_count=13`
- `sparse_first_count=10`
- `citation_aware_count=5`
- `clarification_debug_only_count=6`
- `strong_signal_required=true`
- `baseline_default_unchanged=true`
- `calls_llm=false`
- `writes_chroma=false`
- `recommended_hpc_full_eval=true`

Direct probe:

- Query: `FastAPI 里 Request Body 如何定义？`
- Inferred type: `zh_knowledge`
- Selected policy: `dense_sparse_fusion`
- Conservative gate enabled: `false`
- Fallback to baseline: `true`

## Phase 6E-10 Plan

Phase 6E-10 should run full API-level re-evaluation comparing baseline, Phase 6E-7 gated policy,
and Phase 6E-9 conservative gate. The goal is to keep targeted 59-case gains while recovering
240-case full-set performance.

## Boundaries

- This does not claim production launch readiness.
- This does not claim all bad cases are solved.
- This does not call a generation model.
- This does not write Chroma.
- Default Agent/API behavior remains `baseline`.
