# Phase 6H Streamlit Demo Plan

## Goal and Boundary

Phase 6H adds a focused Streamlit presentation layer for the existing enterprise RAG Agent. The
page is intended for local demonstrations of knowledge-base answers, source tracing, retrieval
diagnostics, and Phase 6G session memory. It calls the existing FastAPI business endpoint and does
not duplicate retrieval, ranking, memory, or answer synthesis.

This is a demo UI, not a production web application. It does not call a provider directly, read an
environment file, accept or store API keys, write Chroma, or change the production Agent/API
contract.

## Entry Point and API Connection

The existing upstream entry point is reused:

```powershell
.\.venv\Scripts\python.exe -m streamlit run src\streamlit_app.py
```

The default backend is `http://127.0.0.1:8000`, and the default endpoint is
`/enterprise/agent/query`. Both values can be changed in the sidebar. Requests contain only the
existing `query`, `session_id`, `top_k`, and `return_sources` fields.

The memory and structured retrieval selectors are status and demonstration controls. The current
backend reads these modes from service startup environment variables, so changing the UI selector
does not mutate the running backend. The page states this limitation explicitly.

## Page Structure

- **Sidebar:** API URL and endpoint, session ID, memory mode, structured retrieval mode, top-k,
  source return toggle, timeout, health check, and example questions.
- **Chat area:** user messages and Agent answers rendered with Streamlit chat components.
- **Sources:** expandable source records with traceable metadata and a bounded preview.
- **Memory:** current session diagnostics and a visible follow-up rewrite when one occurs.
- **Debug:** collapsed retrieval, memory, request, and display-safe raw response JSON.
- **Status band:** active endpoint, session ID, and the modes selected for demonstration.

## Memory Demonstration

The sidebar exposes the current `session_id` and an advisory memory mode. A refresh action creates
a new session ID and clears the visible conversation. Clear Chat only removes frontend messages;
it does not claim to clear backend memory because the service does not expose a memory-clear API.

Each response can display:

- `memory_mode`
- `memory_enabled`
- `session_id`
- turn counts before and after the request
- follow-up status
- original and contextual queries
- rewrite strategy
- whether memory was used for retrieval
- cross-session isolation status

## Sources and Citations

The endpoint uses `sources` as its evidence carrier; a separate citations field is not required.
Each expandable source shows `source_id`, title, document type, section path, source URL, chunk ID,
relevance score, and at most 500 characters of `content_preview`. Complete chunk content and local
filesystem paths are not displayed. Valid HTTP(S) source URLs are clickable.

## Retrieval and Structured Retrieval Display

`retrieval_debug` is shown in a collapsed JSON panel. The UI also provides an advisory structured
retrieval selector (`off` or `metadata_symbol`). The running service remains the source of truth;
the UI does not claim that a selector changes a process-level environment setting.

## Error Handling

- An unavailable API produces: `未连接到 Agent API，请先启动 FastAPI 服务。`
- A timeout asks the user to check the service and retry.
- HTTP errors show the status and a bounded response detail.
- An invalid or incomplete response schema is reported without crashing the page.
- An empty source list is represented explicitly rather than inventing evidence.

## Security and Privacy

The page has no API-key control and never reads `.env`. Request payloads contain no credentials.
Before rendering diagnostics, values under credential-like keys and local path fields are redacted;
Windows absolute paths and token-like values embedded in strings are also masked. Source previews
are bounded and complete retrieved content is not rendered.

## Current Limitations

- Memory remains a process-local backend buffer and is cleared on service restart.
- Memory is not shared across backend processes and is not a long-term user profile.
- Frontend mode selectors cannot alter backend startup environment variables.
- The UI does not replace source verification or citation review.
- Phase 6H provides local demonstration behavior, not authentication, authorization, deployment,
  concurrency testing, or production readiness.
