# Phase 6I-6K Roadmap

## Current Baseline

The project has completed implementation through the Phase 6H Streamlit RAG demo. The current
capability set includes the enterprise knowledge-base RAG pipeline, controlled retrieval with
source tracing, a 240-case evaluation program, embedding and reranker benchmarks, query-policy
experiments, structured retrieval materialization, conversational memory, API-level memory
validation, and a Streamlit demonstration UI.

The best measured structured retrieval version remains Phase 6F-8:

- calibrated 240-case bad cases: 59 to 49
- source hit rate: 0.694 to 0.751
- errors: 0

Phase 6G memory evaluation covered 24 cases and 47 turns with a 1.0 follow-up context hit rate and
zero cross-session leaks. Its API evaluation completed 12 requests with 12 valid response schemas
and zero errors. Phase 6H renders answers, source cards, retrieval and memory diagnostics, request
payloads, raw display-safe responses, and unavailable-API errors.

These are measured local project results. They do not mean that all retrieval failures are fixed,
that high-concurrency testing is complete, or that the system is production-ready.

## Execution Order

1. Phase 6I: Evidence Grounding + Citation Verifier
2. Phase 6J: Custom LangGraph Enterprise RAG Graph
3. Phase 6K: Final README / Resume / Demo Packaging

Phase 6I implementation and local evaluation are complete pending final quality gates and
checkpoint. Phase 6J and Phase 6K have not started. Each phase requires implementation, automated
checks, manual acceptance, and its own checkpoint before the next phase begins.

## Phase 6I: Evidence Grounding + Citation Verifier

Status: implemented and locally evaluated; final checkpoint is pending.

### Objective

Add a deterministic verifier that checks whether answer claims have support in retrieved evidence,
whether citations are traceable, and whether an unsupported-answer fallback is necessary. The
verifier must not invent evidence or replace the original source records.

### Planned Scope

- Add `src/rag/evidence_verifier.py`.
- Add a rule-based evaluation runner and dedicated cases/results/summary artifacts.
- Document grounding semantics, citation coverage, unsupported-term detection, fallback behavior,
  limitations, and reproducibility.
- Expose additive diagnostics through the existing response path only when enabled.

Feature flag:

```text
ENTERPRISE_EVIDENCE_VERIFIER_MODE=off|rule_based
```

Default: `off`.

Planned diagnostics:

```text
verifier_debug
grounding_score
grounding_status
citation_coverage
unsupported_terms
safe_fallback_triggered
```

### Acceptance

- Zero evaluation errors.
- Grounding debug is present for every enabled case.
- Citation-required cases are exercised.
- At least one deliberately unsupported answer is detected.
- No generative LLM call or Chroma write is used by the verifier evaluation.
- Existing default Agent/API behavior remains unchanged.
- Tests, lint, leakage checks, and manual review pass.

Local evaluation result: 24 cases, 1.0 expected-status match rate, 3/3 citation-required cases
checked, 2/2 unsupported-answer cases detected, complete verifier debug for every case, and zero
runtime errors. The verifier made no LLM call and no Chroma write.

## Phase 6J: Custom LangGraph Enterprise RAG Graph

### Objective

Provide a clear, self-owned LangGraph workflow that exposes the enterprise RAG reasoning stages
without replacing the accepted legacy graph by default.

Feature flag:

```text
ENTERPRISE_AGENT_GRAPH_MODE=legacy|custom_graph
```

Default: `legacy`.

### Planned Graph

```text
query_classifier
  -> memory_rewriter
  -> retriever
  -> ranker
  -> answer_generator
  -> evidence_verifier
  -> final_response
```

Conditional routing:

- ambiguous query -> clarification response
- unsupported query -> safe response
- normal query -> memory rewriting and retrieval path

### Acceptance

- The custom graph imports successfully.
- A fake-model smoke run covers its main and conditional paths.
- The Mermaid diagram matches the implementation.
- Legacy mode remains the default and existing tests pass.
- The smoke does not call a real LLM or write Chroma.
- Lint, leakage checks, and manual review pass.

## Phase 6K: Final README / Resume / Demo Packaging

### Objective

Consolidate the accepted system into consistent public repository, runbook, demonstration,
interview, and resume materials. This phase packages measured work; it does not manufacture new
technical claims.

### Planned Deliverables

- Update `README.md`.
- Add project final summary and operational runbook.
- Add interview notes and a concise resume project description.
- Add a reproducible demo walkthrough.

### Required Coverage

- project objective and architecture
- RAG pipeline and structured retrieval
- measured evaluation methodology and results
- conversational memory
- evidence grounding
- custom LangGraph workflow
- Streamlit demo
- startup and verification commands
- demonstration script
- resume description and interview discussion
- limitations and future improvements

### Acceptance

- Commands, paths, links, and metrics are verified against accepted repository artifacts.
- Upstream functionality and project additions are clearly distinguished.
- Results are reported with their actual evaluation boundary.
- No production-readiness claim, secret, local absolute path, private corpus text, or organization-
  specific naming is introduced.
- Documentation review and leakage checks pass.

## Shared Boundaries

- Do not start a later phase before the current phase passes manual acceptance.
- Keep all new runtime features default-off until validated.
- Do not describe skipped work as passed or design-only work as implemented.
- Do not commit environment files, credentials, model weights, vector databases, raw private
  content, caches, logs, local paths, or large generated binaries.
- Preserve the upstream generic Agent endpoints and the existing business query endpoint.
