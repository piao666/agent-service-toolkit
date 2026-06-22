# Phase 6M Real LLM Representative Evaluation Preparation

## Scope

Phase 6L used two independent FastAPI processes and a fake model to verify endpoint routing,
response-schema stability, graph-debug observability, and service cleanup. It did not measure real
LLM answer quality. Its low latency is consistent with that bounded scope and must not be presented
as a real-provider latency result.

Phase 6M prepares a small, reviewable comparison over eight representative cases. The goal is not
another benchmark. It is to compare fake-model and real DeepSeek behavior for answer fluency,
expected-term coverage, evidence-verifier output, custom-graph debug visibility, and request
latency.

## Case Coverage

`data/knowledge_base/evaluation/phase6m_representative_cases.jsonl` covers semantic QA, a two-turn
memory follow-up, code/API/config lookup, citation-required lookup, exact metadata lookup,
ambiguous input, unsupported input, and multi-hop lookup. The runner limits execution to at most
ten cases and defaults to eight.

The output records a bounded answer preview, whether the answer is non-empty, source count,
grounding status, graph-debug presence, deterministic expected-keyword notes, latency, errors, and
timeouts. The expected-keyword note is not an automated quality verdict; manual review remains
required.

## Safe Default

The runner does not send requests unless `--execute` is supplied. A DeepSeek run also requires
`DEEPSEEK_API_KEY` in the runner process environment. Missing credentials produce
`skipped_due_to_missing_key=true`; the script never prints or writes the credential.

Plan-only validation:

```powershell
.\.venv\Scripts\python.exe scripts\run_phase6m_real_llm_representative_eval.py `
  --provider both `
  --endpoint-mode custom_graph
```

Authorized representative run against an already started service:

```powershell
$env:DEEPSEEK_API_KEY = "<SECRET_FROM_SECURE_STORE>"
.\.venv\Scripts\python.exe scripts\run_phase6m_real_llm_representative_eval.py `
  --provider both `
  --endpoint-mode custom_graph `
  --base-url http://127.0.0.1:8000 `
  --limit 8 `
  --execute
```

The backend process must be started separately with the intended graph mode. The runner checks the
reported `model_debug.agent_graph_mode` and marks a mismatch instead of silently accepting the
wrong endpoint mode.

## Boundaries

- No real LLM is called while preparing this phase locally.
- The runner does not start a service, write Chroma, run 240 cases, or run a benchmark.
- Results must not contain API keys or `.env` contents.
- Eight representative cases cannot establish general model superiority or production readiness.
- The real DeepSeek run is deferred to an authorized external environment.
