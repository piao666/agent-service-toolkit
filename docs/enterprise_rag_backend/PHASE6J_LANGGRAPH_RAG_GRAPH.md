# Phase 6J: Custom LangGraph Enterprise RAG Graph

## Goal and compatibility boundary

Phase 6J adds an explicit, inspectable LangGraph workflow for demonstrating pluggable Agent
orchestration. The custom graph does not replace the existing enterprise RAG Agent or service.
`ENTERPRISE_AGENT_GRAPH_MODE=legacy` remains the default, so the existing API, Streamlit UI, and
evaluation behavior are unchanged. Phase 6L-1 adds optional endpoint-level dispatch for
`custom_graph` without replacing the registry entry or routing custom state through the generic
message-based invoke path.

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
| `answer_generator` | query, ranked sources, model | answer, model debug | Uses the configured model asynchronously; smoke can inject a deterministic generator. |
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
independent from model providers and vector stores. The default graph reuses the existing runtime
retriever and calls `get_model(...).ainvoke(...)`; model failures return a safe fallback instead of
propagating an endpoint error.

## Feature flag

`ENTERPRISE_AGENT_GRAPH_MODE=legacy|custom_graph` is parsed by RAG settings. Invalid values fall
back to `legacy`. Phase 6L-1 reads this setting only inside `/enterprise/agent/query`: `legacy`
keeps the existing message-based Agent path, while `custom_graph` directly awaits the custom graph
runner. The generic Agent registry remains unchanged.

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

- The smoke does not call a real LLM and uses injected retrieval and answer stubs.
- The smoke does not read or write Chroma.
- The default answer node now has a model-backed path, but real-provider behavior requires separate
  validation.
- The custom graph is disabled by default. Phase 6L-1 endpoint wiring is the first integration step,
  not a production-readiness claim.
- This is not a claim of production-grade Agent orchestration or complete query classification.

Phase 6L-2 may compare legacy and custom graph behavior on a controlled evaluation set after the
Phase 6L-1 implementation is reviewed.
