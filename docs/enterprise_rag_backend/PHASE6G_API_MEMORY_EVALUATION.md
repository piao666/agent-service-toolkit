# Phase 6G API Memory Evaluation

## Goal

Phase 6G-5 verifies that the conversation-memory behavior validated offline in Phase 6G-4 is
preserved through the real FastAPI request lifecycle and the
`POST /enterprise/agent/query` response schema. It covers memory off and buffer modes, two-turn
and three-turn follow-ups, session isolation, missing sessions, no-context follow-ups, and the
additive `memory_debug` response.

This evaluation uses the in-process fake chat model. It does not call a provider or generative LLM.
It also points the service at an intentionally unavailable temporary embedding path so retrieval
returns a controlled fallback before opening Chroma. The evaluation does not assess answer or
retrieval quality.

## Service Lifecycle

`scripts/run_phase6g_api_memory_eval.py` controls two short-lived local service processes on
`http://127.0.0.1:8000`:

1. memory off, for the baseline no-op request;
2. memory buffer, for all session-aware requests.

Each process uses `src/run_service.py`, waits for `/health`, calls the business endpoint, and is
stopped before the next mode starts. Runtime logs, SQLite state, and unavailable embedding/Chroma
paths are placed outside the repository in temporary storage. Tracing is disabled. The service
uses an explicit fake model for every request, and no provider credential is read or emitted by
the evaluation script.

## Cases

The API evaluation contains six scenarios and twelve requests:

| Scenario | Requests | Expected behavior |
| --- | ---: | --- |
| Memory-off baseline | 1 | Memory disabled, query unchanged, no memory write. |
| Two-turn follow-up | 2 | Second request resolves the RAG topic. |
| Three-turn follow-up | 3 | Third request retains RAG rather than the prior limitation wording. |
| Cross-session isolation | 4 | RAG and LoRA sessions resolve only their own topics. |
| Missing session | 1 | Buffer mode remains disabled without `session_id`. |
| No-context follow-up | 1 | Follow-up is detected but not rewritten without history. |

Every response is checked for the complete enterprise query response contract and these
`memory_debug` fields:

- memory mode, enablement, and session ID;
- turn counts before and after the request;
- follow-up detection and original/contextual query;
- rewrite strategy and retrieval-memory usage;
- memory write status and session-isolation marker.

## Results

| Metric | Result |
| --- | ---: |
| API available | true |
| Cases | 6 |
| Requests | 12 |
| Memory-off no-op requests | 1 |
| Memory-on enabled requests | 10 |
| Follow-ups detected | 6 |
| Contextual queries returned | 5 |
| Contextual query hit rate | 1.0000 |
| Complete memory debug responses | 12 |
| Cross-session leaks | 0 |
| Missing-session no-op requests | 1 |
| No-context no-op requests | 1 |
| Schema-valid responses | 12 |
| Errors | 0 |
| Timeouts | 0 |

The five contextualized requests are the follow-ups with usable history. The no-context follow-up
is detected but remains unchanged. The missing-session request exits before memory follow-up
processing, as required. All twelve responses preserve the business endpoint schema.

## Boundary

The evaluation proves local API wiring and deterministic memory behavior only. The memory store is
still process-local, is cleared on restart, and is not shared across workers. It is not a long-term
user profile and does not replace knowledge-base evidence or citations. No real LLM, Chroma write,
retrieval-quality evaluation, load test, or production deployment is included.

After manual acceptance, Phase 6H may expose `session_id`, memory mode, contextual query, turn
count, and `memory_debug` in a Streamlit demo. Phase 6H has not started.
