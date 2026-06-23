# Phase 7A Planner, Multi-hop, and Judge Prototype

## Goal

Phase 7A adds three local prototype capabilities to the custom Enterprise RAG graph:

1. `planner_debug`: rule-based query planning for `simple`, `complex`, `multi_hop`,
   `ambiguous`, and `unsupported` cases.
2. Multi-hop prototype retrieval: only enabled when the planner sets
   `requires_multi_hop=true`; it creates two or three subqueries and reuses the existing
   retriever to merge sources.
3. `judge_debug`: a local `rule_based_fallback` answer judge that does not call a real LLM.

This phase is a local prototype. It does not change the legacy default path, does not run HPC or
240-case evaluation, does not call a real DeepSeek model, and does not write Chroma.

## Implementation

New modules:

- `src/rag/planner.py`: deterministic planner and multi-hop query splitter.
- `src/rag/llm_judge.py`: deterministic answer judge.
- `scripts/smoke_phase7a_planner_multihop_judge.py`: local smoke coverage for planner,
  multi-hop routing, and judge output.

Updated custom graph:

- Adds a `planner` node after `query_classifier`.
- Routes `ambiguous` and `unsupported` planner decisions to existing clarification and safe
  response nodes.
- Routes normal queries to memory rewriting.
- Routes only `requires_multi_hop=true` cases to `multi_hop_retriever`.
- Runs `judge` after the evidence verifier and before `final_response`.

## Response Debug Fields

The custom graph can now return:

- `planner_debug`
- `judge_debug`
- `graph_debug.planner`
- `graph_debug.multi_hop`
- `graph_debug.judge`

`nodes_executed` includes `planner` for custom graph calls. Multi-hop cases include
`multi_hop_retriever`; judged normal cases include `judge`.

## Evaluation

The local smoke set covers:

- `simple_qa`
- `multi_hop_compare`
- `code_config`
- `citation_required`
- `ambiguous_query`
- `unsupported_query`
- `evidence_sensitive`

The smoke uses stub retrieval and stub answer generation, so it validates graph control flow and
debug surfacing rather than retrieval quality.

## Boundaries

- No real LLM call.
- No 240-case run.
- No HPC run.
- No Chroma write.
- No claim that this is production-grade planning or judging.
- No claim that custom graph is better than legacy.

## Next Step

After local review and checkpoint, a later phase can decide whether to run a bounded endpoint-level
comparison for custom graph planner and judge behavior. That should remain separate from this local
prototype.

## Default Endpoint Hardening

After the first local prototype, external endpoint testing showed that the fake-retriever smoke did
not cover the real default custom-graph endpoint path. The hardening patch adds a default endpoint
smoke that calls `/enterprise/agent/query` with `ENTERPRISE_AGENT_GRAPH_MODE=custom_graph` and
`USE_FAKE_MODEL=true` without injecting a retriever or answer generator.

The graph order is now:

1. `query_classifier`
2. `clarification_response` or `safe_response` for ambiguous or unsupported queries
3. `memory_rewriter`
4. `planner`
5. `retriever` or `multi_hop_retriever`
6. `ranker`
7. `answer_generator`
8. `evidence_verifier`
9. `judge`
10. `final_response`

The planner runs after memory rewriting, so follow-up queries can be planned against the
contextualized query. Multi-hop retrieval keeps the full contextual query and adds up to two
subqueries. Retriever, verifier, and judge failures are recorded in debug fields and should not
turn a single local component failure into an endpoint-level 500.
