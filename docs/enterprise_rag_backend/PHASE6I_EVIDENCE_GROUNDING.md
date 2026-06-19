# Phase 6I Evidence Grounding and Citation Verifier

## Purpose

Retrieval alone does not prove that a generated answer is supported by the returned evidence. A
model can add unsupported details, overstate a partial source, or return source cards that are
topically related but do not cover its answer terms. Phase 6I adds a deterministic evidence check
after answer synthesis so the API and demo UI can expose this risk rather than treating every
non-empty source list as grounded.

Citation grounding is stricter than displaying sources. Source display answers "what was
retrieved"; citation grounding estimates whether answer terms are covered by traceable source
metadata and bounded previews. The verifier never invents a citation.

## Scope and Boundary

The first baseline is rule-based. It does not call a generative LLM, access a provider, write
Chroma, or save complete chunks. It is disabled by default:

```text
ENTERPRISE_EVIDENCE_VERIFIER_MODE=off|rule_based
ENTERPRISE_EVIDENCE_SAFE_FALLBACK=false|true
ENTERPRISE_EVIDENCE_MIN_SCORE=0.30
ENTERPRISE_EVIDENCE_HIGH_SCORE=0.60
```

Default mode is `off`, and safe fallback defaults to `false`. Existing answer behavior is therefore
unchanged unless the operator explicitly enables the verifier.

## Verifier Design

Inputs:

- user query
- generated answer
- returned sources
- optional query type

Supported source fields include `source_id`, title, document type, section path, source URL, chunk
ID, bounded preview/text fields, and relevance scores. Missing fields are accepted. Nested metadata
is used as a fallback for current retriever response compatibility.

Rule-based term extraction covers:

- bounded Chinese character sequences and n-grams with common stop terms removed
- English technical terms such as RAG, LoRA, FastAPI, API, BM25, Chroma, and LangGraph
- code/config symbols such as `ENTERPRISE_MEMORY_MODE`, `source_id`, `session_id`, HTTP methods,
  status codes, function forms, and API paths
- multi-word technical phrases such as `Request Body`

Terms are deduplicated and bounded. Source summaries retain only source ID, title, chunk ID, and
extracted evidence terms in verifier diagnostics; complete source text is not returned.

## Scoring and Output

The base score is:

```text
matched important answer terms / all important answer terms
```

Normal thresholds classify scores of at least 0.60 as high, 0.30-0.60 as medium, and below 0.30
as low. Citation-required queries require at least 0.70 for high and classify scores below 0.50 as
low. Empty answers and empty source lists are always low. A source-backed answer without extracted
important terms is medium rather than assumed grounded.

The additive `verifier_debug` output contains:

```text
verifier_mode
grounding_score
grounding_status
answer_has_sources
citation_coverage
important_terms
matched_terms
unsupported_terms
source_count
safe_fallback_triggered
calls_llm
writes_chroma
```

Citation coverage requires sources, at least one matched answer term, and coverage by at least one
source summary. A low result can trigger a language-aware safe fallback only when
`ENTERPRISE_EVIDENCE_SAFE_FALLBACK=true`; otherwise the verifier is diagnostic and does not replace
the answer.

## Agent, API, and UI Integration

The existing enterprise RAG graph executes an optional `verify_evidence` node after answer
synthesis and before final response assembly. This is a scoped extension of the accepted graph, not
the Phase 6J custom graph. With verifier mode off, the node emits an empty debug object and leaves
the draft answer unchanged.

The business API response adds an optional `verifier_debug` object. Existing answer, source,
retrieval, model, memory, fallback, latency, and session fields remain intact. The Streamlit UI adds
an Evidence grounding section with status, score, citation coverage, matched terms, unsupported
terms, and safe-fallback status. Low grounding is shown as a visible warning. Raw response display
continues to use display-safe redaction.

## Evaluation Set

`phase6i_evidence_cases.jsonl` contains 24 synthetic cases. It covers strongly grounded answers,
partial and weak support, unsupported claims, citation-required questions, API/config symbols,
memory follow-up answers, empty answers, and empty source lists. Short synthetic previews avoid
using private corpus content.

The local runner directly calls the verifier and does not start FastAPI. Results:

```text
case_count=24
high_count=14
medium_count=2
low_count=8
expected_status_match_rate=1.0
citation_required_checked_count=3/3
unsupported_answer_detected_count=2/2
empty_sources_low_confidence_count=2
verifier_debug_present_count=24
safe_fallback_triggered_count=1
error_count=0
calls_llm=false
writes_chroma=false
starts_service=false
```

These numbers validate deterministic behavior on the designed local cases. They are not an answer
accuracy score and are not evidence that hallucination has been eliminated.

## Limitations

- Lexical overlap cannot prove that every factual claim is correct.
- Synonyms and paraphrases can be under-counted without semantic similarity.
- A shared term can produce coverage even when the source contradicts the answer.
- The verifier is not production-grade fact checking and does not replace human review.
- Safe fallback is answer-level, not claim-level.
- Future work may add embedding similarity, claim extraction, contradiction checks, or an optional
  LLM judge behind independent evaluation and feature flags.

## Relationship to Phase 6J

Phase 6J is planned to define a custom LangGraph enterprise RAG graph and can reuse this verifier as
an explicit graph node. Phase 6J has not started; the legacy graph remains the default.
