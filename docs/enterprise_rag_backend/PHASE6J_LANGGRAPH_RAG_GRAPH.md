# Phase 6J: Custom LangGraph Enterprise RAG Graph

## Goal and compatibility boundary

Phase 6J adds an explicit, inspectable LangGraph workflow for demonstrating pluggable Agent
orchestration. The custom graph does not replace the existing enterprise RAG Agent or service.
`ENTERPRISE_AGENT_GRAPH_MODE=legacy` remains the default, so the existing API, Streamlit UI, and
evaluation behavior are unchanged. The graph can be imported and called directly for controlled
smoke validation; API dispatch is intentionally deferred to avoid changing the stable endpoint.

## State

`EnterpriseRAGGraphState` carries the query, optional session ID, query type, contextual query,
memory debug, retrieved and ranked sources, retrieval debug, answer, citations, verifier debug,
graph debug, and final response. Every terminal response exposes additive debug data and records
the executed nodes, selected route, `calls_llm=false`, and `writes_chroma=false`.

## Nodes

| Node | Input | Output | Responsibility |
| --- | --- | --- | --- |
| `query_classifier` | query, session ID | query type, route | Deterministic classification without an LLM. |
| `memory_rewriter` | query, session memory | contextual query, memory debug | Reuses the Phase 6G session-isolated contextualizer. |
| `retriever` | contextual or original query, top-k | sources, retrieval debug | Adapts the existing enterprise retriever; smoke injects a local stub. |
| `ranker` | retrieved sources | ranked sources | Stable score ordering without a new reranker model. |
| `answer_generator` | query, ranked sources | answer | Deterministic smoke-safe answer generation without a provider. |
| `evidence_verifier` | query, answer, sources | verifier debug | Reuses the Phase 6I rule-based grounding verifier. |
| `clarification_response` | ambiguous query | clarification answer | Avoids retrieval when required context is missing. |
| `safe_response` | unsupported query | scope-safe answer | Avoids retrieval for clearly out-of-scope requests. |
| `final_response` | accumulated state | unified response | Builds citations, debug payloads, and bounded memory updates. |

## Conditional edges

- `ambiguous_query -> clarification_response -> final_response`
- `unsupported_query -> safe_response -> final_response`
- normal query types, including `memory_follow_up`, run through
  `memory_rewriter -> retriever -> ranker -> answer_generator -> evidence_verifier -> final_response`
- The verifier route currently terminates at `final_response`; optional safe fallback replacement is
  controlled by the existing Phase 6I setting.

The matching diagram is maintained in [agent_graph_mermaid.md](agent_graph_mermaid.md). The smoke
also verifies that LangGraph can render Mermaid text from the compiled graph.

## Reused capabilities

- Phase 6G: `ConversationMemoryStore` and deterministic follow-up contextualization.
- Phase 6F: the existing enterprise retriever, including configured retrieval and structured
  retrieval behavior, through an adapter rather than duplicated retrieval code.
- Phase 6I: deterministic evidence verification and optional safe fallback construction.

The graph builder accepts injected retriever and answer-generator functions. This makes smoke tests
independent from model providers and vector stores while the default callable still reuses the
existing runtime retriever.

## Feature flag

`ENTERPRISE_AGENT_GRAPH_MODE=legacy|custom_graph` is parsed by RAG settings. Invalid values fall
back to `legacy`. The current business endpoint continues to use its legacy implementation; the
flag documents and validates the optional mode without silently changing API dispatch.

## Smoke result

`scripts/smoke_phase6j_langgraph.py` builds a real LangGraph with an in-memory retrieval stub and
checks semantic, ambiguous, unsupported, and memory-follow-up routes. It also checks the retriever,
answer generator, evidence verifier, final response schema, and Mermaid export.

Final local summary:

- graph import/build and Mermaid export: passed
- semantic, ambiguous, unsupported, and memory routes: passed
- retriever, deterministic answer generator, and evidence verifier nodes: passed
- final response schema: passed
- `error_count=0`, `calls_llm=false`, `writes_chroma=false`

## Limitations

- The smoke does not call a real LLM and uses an injected retrieval stub.
- The smoke does not read or write Chroma.
- The deterministic answer generator is a graph validation baseline, not a production answer path.
- The custom graph is disabled by default and is not wired into the production endpoint in this
  phase.
- This is not a claim of production-grade Agent orchestration or complete query classification.

Phase 6K may package this Mermaid diagram and the verified graph contract into final project,
runbook, interview, resume, and demo documentation. Phase 6K has not started.
