# Phase 6G Conversational Memory Plan

## Scope

Phase 6G adds bounded, session-scoped conversational memory to enterprise RAG question answering.
It addresses follow-up questions whose meaning depends on an earlier turn. For example, after
asking what RAG is, a user can ask what limitations "it" has and retrieval can use a contextual
query about RAG.

Memory does not replace knowledge-base retrieval. It only helps resolve the current query before
retrieval. Answers must still be grounded in retrieved sources, and memory cannot be treated as a
citation or used to invent evidence.

This phase does not provide production-grade persistence, long-term user memory, or a complete
solution for every form of contextual understanding.

## Existing State Mechanisms

The upstream service supports LangGraph checkpointers and stores for graph state and chat history.
Phase 6G does not reuse those mechanisms as its first implementation because the business RAG path
needs an explicit bounded turn model, source-only summaries, clear/count operations, deterministic
rule-based contextualization, and observable `memory_debug` fields. The prototype therefore uses a
small process-local store behind a focused interface. A later implementation can replace it with a
LangGraph store, SQLite, or Redis without changing the memory policy.

## Session Isolation

Memory is keyed only by the caller-provided `session_id`. The internal thread ID generated when a
business request omits `session_id` does not enable memory. Reads, writes, counts, and clear
operations address one normalized session key and never scan another session.

The in-memory store is protected by a lock for concurrent access within one process. It is not
shared across workers and is cleared on process restart.

## Stored Data

The buffer retains the latest N turns, with a default of five. A turn contains:

- user query;
- truncated assistant answer;
- source summaries limited to `source_id`, title, chunk ID, and source URL;
- UTC timestamp.

Retrieved chunk bodies, provider credentials, API keys, and arbitrary request metadata are not
stored. The default answer limit is 1,000 characters.

## Follow-up Contextualization

The baseline is deterministic and does not call an LLM. It detects Chinese and English follow-up
signals such as pronouns, references to earlier text, limitations, advantages, principles, and
usage questions. Without recent turns, it leaves the query unchanged.

When a recent turn exists, topic extraction prefers the previous user query, then a source title,
then a short prefix of the prior answer. A query such as `它有什么局限？` after `RAG 是什么？` is
rewritten to `RAG 有什么局限？`. Independent questions remain unchanged.

## Agent and API Integration

Configuration:

```text
ENTERPRISE_MEMORY_MODE=off|buffer
ENTERPRISE_MEMORY_MAX_TURNS=5
ENTERPRISE_MEMORY_MAX_ANSWER_CHARS=1000
```

The default is `off`, preserving the current Agent/API baseline. In `buffer` mode, memory is active
only when the business request includes `session_id`. The Agent contextualizes the query before
retrieval and appends the completed turn after answer synthesis. Sources and citations continue to
follow the existing retrieval path.

The response adds `memory_debug` without removing existing fields. It includes:

- `memory_mode` and `memory_enabled`;
- `session_id`;
- `memory_turn_count_before` and `memory_turn_count_after`;
- `is_follow_up`;
- `original_query` and `contextual_query`;
- `memory_rewrite_strategy`;
- `memory_used_for_retrieval` and `memory_written`;
- `cross_session_isolated`.

## Validation Boundary

Phase 6G-0 through Phase 6G-3 use a local smoke script for append/get/clear behavior, session
isolation, follow-up rewriting, missing-session behavior, and memory-off compatibility. The script
does not start the service, call an LLM, or write Chroma.

Phase 6G-4 is not part of this implementation. It should later introduce reproducible single-turn,
two-turn, three-turn, isolation, clarification, and memory-off versus memory-on cases. Candidate
metrics include follow-up context hit rate, cross-session leak count, answer/source availability,
and baseline compatibility. HPC or real-provider evaluation should only follow local acceptance.

This phase does not include Streamlit work or claim production readiness.
