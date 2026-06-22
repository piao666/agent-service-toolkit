# Phase 6L-1: Custom Graph Endpoint Integration

## Goal

Phase 6L-1 moves the Phase 6J custom LangGraph from an isolated callable graph to an optional
execution path behind the existing `POST /enterprise/agent/query` endpoint. The default remains
`legacy`; this phase does not replace the stable Agent, rerun the 240-case evaluation, or establish
production readiness.

## Protocol self-check

The two graph implementations use different contracts:

- `enterprise_rag_agent` extends `MessagesState`. The generic service invokes it with a
  `messages` list and reads the final answer from `response["messages"][-1]`.
- `enterprise_rag_graph` uses `EnterpriseRAGGraphState`, a regular `TypedDict` containing `query`,
  `session_id`, retrieval fields, debug fields, and `final_response`.

Directly replacing the `enterprise-rag-agent` registry entry would break generic invoke and stream
assumptions. The registry therefore remains unchanged.

## Endpoint-level routing

`/enterprise/agent/query` now reads `rag_settings.agent_graph_mode`:

```text
ENTERPRISE_AGENT_GRAPH_MODE=legacy
  -> existing enterprise-rag-agent message-based path

ENTERPRISE_AGENT_GRAPH_MODE=custom_graph
  -> await run_enterprise_rag_graph(...)
  -> map final_response into EnterpriseAgentQueryResponse
```

The endpoint returns a generated business `session_id` when the request omits one, but passes the
original caller value to the custom graph. This preserves the Phase 6G rule that missing caller
session IDs do not enable conversational memory.

## Async graph conversion

All nine graph nodes now use async signatures. `run_enterprise_rag_graph()` calls the compiled
graph with `await compiled_graph.ainvoke(...)`. Synchronous injected retrievers are moved to a
worker thread; async retrievers can be awaited directly. The graph builder still supports injected
retrieval and answer functions for deterministic smoke tests.

## Answer generation

The default answer node reuses `ANSWER_SYNTHESIS_PROMPT` and the existing model registry:

```text
get_model(selected_model).ainvoke(messages)
```

Only source titles and bounded previews are included in the graph prompt. If no sources exist, the
model is not called. If model construction or invocation fails, the graph returns the existing safe
fallback and records a bounded error type in `model_debug`; it does not expose credentials or
environment contents.

When `USE_FAKE_MODEL=true` and `model=fake`, the same model-backed node uses the project fake model.
`graph_debug.calls_real_llm` remains false. An injected answer generator used by the Phase 6J smoke
also records no real LLM call.

## Response additions

`EnterpriseAgentQueryResponse` now includes additive `graph_debug`, defaulting to an empty object.
The custom path returns graph mode, executed nodes, selected route, answer-generator mode, and
real-LLM-call/Chroma-write flags. Legacy responses return `graph_debug={}` and otherwise retain
their existing response shape.

## Feature flag

```text
ENTERPRISE_AGENT_GRAPH_MODE=legacy
ENTERPRISE_AGENT_GRAPH_MODE=custom_graph
```

Invalid values resolve to `legacy`. `.env.example` documents both modes without containing a
credential.

## Smoke result

`scripts/smoke_phase6l_custom_graph_endpoint.py` uses an in-process ASGI transport, a retrieval
stub, and the project fake model. It does not start a long-running service or access Chroma.

Validated results:

- custom graph endpoint status and response schema: passed;
- `graph_debug.graph_mode=custom_graph`: passed;
- executed node list present: passed;
- `model_debug.provider=custom_graph`: passed;
- injected model failure returned a safe fallback with status 200: passed;
- legacy endpoint branch remains callable: passed;
- `calls_llm=false`;
- `calls_real_llm=false`;
- `writes_chroma=false`;
- `error_count=0`.

The generated summary is stored at
`data/knowledge_base/evaluation/phase6l_custom_graph_endpoint_smoke.json`.

## Current limits

- No 240-case evaluation was run.
- No HPC environment was used.
- No real provider was called; real-LLM behavior needs separate validation.
- This is the first endpoint integration step and does not establish production readiness.
- The generic invoke/stream endpoints still use the legacy registry contract.

## Phase 6L-2 plan

After manual review, Phase 6L-2 may compare `legacy` and `custom_graph` on a controlled API-level
evaluation, including source hit, latency, error, fallback, and calibrated bad-case differences.
HPC or external-provider evaluation must remain a separate explicit decision.

## Phase 6L-3 graph debug surfacing hardening

The Phase 6L-2 baseline reported zero custom-graph debug records. Static review showed that the
schema, endpoint mapping, graph final response, and Phase 6L-1 ASGI smoke already carried the field.
The comparison runner, however, sent both labels to one service instance even though graph mode is
a process-start setting. It also treated field presence as sufficient instead of validating a
non-empty custom payload.

Phase 6L-3 hardens both boundaries:

- `run_enterprise_rag_graph()` defensively restores `graph_debug` from final graph state before
  returning the final response;
- the service copies the debug mapping and node list into the response model;
- graph initialization uses `route=null`, and the classifier writes the selected route;
- endpoint smoke requires non-empty debug, `graph_mode=custom_graph`, and
  `nodes_executed_count > 0`;
- the comparison runner uses separate legacy/custom service URLs and validates top-level debug,
  graph mode, and nodes independently.

Legacy responses may continue to return an empty `graph_debug`. Phase 6L-3 does not rerun the HPC
comparison; that is a separate Phase 6L-4 decision.

## Phase 6L-5 graph-mode environment precedence

The Phase 6L-4 dual-service run returned successful transport and schemas for both processes, but
the process labelled `custom_graph` returned no graph debug. Repository inspection found no
`load_dotenv(override=True)` call: Pydantic Settings already gives process variables precedence
over values from `.env`. The remaining risk was an import-time settings instance combined with an
incorrectly propagated service environment.

Phase 6L-5 makes this boundary explicit:

- `rag_settings.agent_graph_mode` reads `ENTERPRISE_AGENT_GRAPH_MODE` directly from the current
  process before falling back to the value captured by the settings instance;
- the endpoint reports the resolved mode in `model_debug.agent_graph_mode` without exposing any
  environment contents;
- the endpoint smoke launches an isolated Python subprocess and verifies that an explicit
  `custom_graph` process variable overrides the `.env` default;
- the in-process ASGI smoke separately requires a non-empty custom graph debug payload and executed
  node list;
- the dual-service runner starts independent legacy and custom processes with explicit modes and
  refuses to run the comparison unless diagnostic requests confirm both modes. A failed diagnostic
  does not produce a successful comparison summary.

The failed Phase 6L-4 result remains diagnostic evidence only. A new dual-service comparison is
required after this fix; no 240-case run, real provider call, or Chroma write is part of Phase
6L-5.
