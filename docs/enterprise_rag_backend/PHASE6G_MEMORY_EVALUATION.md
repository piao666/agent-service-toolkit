# Phase 6G Memory Evaluation

## Goal

Phase 6G-4 evaluates the deterministic conversation-memory prototype introduced in Phase 6G-0
through Phase 6G-3. It verifies memory on/off behavior, follow-up contextualization, session
isolation, source-summary safety, and the additive `memory_debug` contract.

This is a local offline evaluation. It does not start the FastAPI service, call a generative model,
run retrieval, or write Chroma.

## Evaluation Set

The evaluation set contains 24 cases and 47 turns:

| Case type | Cases | Purpose |
| --- | ---: | --- |
| `single_turn_baseline` | 4 | Independent Chinese and English queries remain independent. |
| `two_turn_follow_up` | 6 | Pronoun and prior-text references inherit the first-turn topic. |
| `three_turn_follow_up` | 3 | A topic survives two consecutive follow-up turns. |
| `cross_session_isolation` | 3 | Interleaved sessions do not read each other's topics. |
| `missing_session_noop` | 2 | Buffer mode remains disabled without a usable session ID. |
| `memory_off_noop` | 2 | Off mode neither reads nor writes memory. |
| `no_context_follow_up` | 2 | Follow-up wording without history is not forcibly rewritten. |
| `source_summary_safety` | 2 | Stored sources contain metadata summaries, not chunk bodies. |

The cases are stored in
`data/knowledge_base/evaluation/phase6g_memory_cases.jsonl`. Each case declares its memory mode,
session, turns, expected follow-up behavior, expected topic terms, and applicable isolation or
safety checks.

## Method

`scripts/run_phase6g_memory_eval.py` creates a fresh `ConversationMemoryStore` for each case. A
cross-session case uses one store with two distinct session IDs so that isolation is tested under
shared process state.

For each turn the runner:

1. calls `contextualize_query_with_memory` before writing the turn;
2. checks whether memory enablement and follow-up detection match the case;
3. checks the contextual query only when usable prior context exists;
4. simulates the Agent's bounded memory write with a fixed local answer fixture;
5. completes the same post-turn `memory_debug` fields used by the Agent;
6. verifies debug completeness, write/no-op behavior, and forbidden cross-session topics;
7. checks stored source keys and confirms that fixture `content` is absent from memory.

No answer quality is evaluated because the runner does not call an LLM. The context-hit metric is
limited to deterministic expected topic terms in the rewritten query.

## Results

| Metric | Result |
| --- | ---: |
| Cases | 24 |
| Turns | 47 |
| Follow-up turns | 24 |
| Follow-ups detected | 20 |
| Follow-ups eligible for contextualization | 18 |
| Follow-ups contextualized | 18 |
| Follow-up context hit rate | 1.0000 |
| Cross-session cases | 3 |
| Cross-session leaks | 0 |
| Memory-off no-op turns passed | 4 |
| Missing-session no-op turns passed | 2 |
| No-context no-op turns passed | 2 |
| Safe source summaries | 2 |
| Turns with complete memory debug | 47 |
| Errors | 0 |

The four linguistically follow-up turns in memory-off and missing-session cases are intentionally
not detected because contextualization exits before memory processing when memory is disabled.
The two no-context follow-ups are detected but remain unchanged. The 18 eligible follow-ups all
contain their expected topic terms after contextualization.

The first run exposed a three-turn topic-inheritance defect: the second turn's original pronoun
query could become the topic for the third turn. Topic selection now walks backward to the most
recent independent user question. This preserves the original stored user query while allowing
three-turn Chinese and English cases to retain the initial topic.

## Acceptance

The local acceptance criteria pass:

- `error_count=0`;
- `cross_session_leak_count=0`;
- `follow_up_context_hit_rate=1.0`;
- memory-off, missing-session, and no-context no-op cases are present and pass;
- source-summary and `memory_debug` checks pass;
- `calls_llm=false`, `writes_chroma=false`, and `starts_service=false`.

## Limitations And Next Step

The store remains process-local and has no cross-process persistence. It is not a long-term user
profile, does not replace citations, and does not demonstrate model-generated answer quality. The
rule-based contextualizer covers a bounded set of follow-up forms and can still miss implicit or
topic-switching queries.

Phase 6G-5 may add an API-level memory evaluation after manual acceptance, including response
schema validation and real Agent lifecycle behavior. A later storage experiment may compare a
LangGraph store or checkpointer. Streamlit integration belongs to Phase 6H and has not started.
