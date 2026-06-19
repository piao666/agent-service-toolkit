# Phase 6H Demo Script

## Start the Local Components

Start FastAPI with the intended local fake or configured-safe model and backend modes. Then start
the UI in a separate terminal:

```powershell
.\.venv\Scripts\python.exe -m streamlit run src\streamlit_app.py
```

The memory and structured retrieval selectors in the sidebar are advisory. Confirm that the
running FastAPI process was started with the modes needed for the demonstration.

## Demo 1: Standard RAG Question

1. Ask `RAG 是什么？`.
2. Confirm that the answer is visible in the chat.
3. Expand Sources and inspect the available title, source ID, section, chunk ID, URL, preview, and
   relevance score.
4. Do not infer retrieval quality when the local collection is unavailable or sources are empty.

## Demo 2: Multi-turn Memory

Use one session ID and a backend started in buffer memory mode:

1. Ask `RAG 是什么？`.
2. Ask `它有什么局限？`.
3. Ask `那它适合什么场景？`.
4. Inspect Memory below each answer. For eligible follow-ups, compare `original_query` with
   `contextual_query` and confirm the topic remains RAG.
5. Refresh Session and confirm that a new session ID is used. Clear Chat alone only clears the
   frontend transcript and does not clear backend memory.

## Demo 3: Sources and Debug

1. Ask `FastAPI 的 Request Body 如何定义？`.
2. Expand the first source record and inspect traceability metadata.
3. Expand Retrieval debug, Memory debug JSON, Request payload, and Raw response JSON.
4. Confirm local paths and credential-like values are redacted from rendered diagnostics.

## Failure Demonstration

Stop FastAPI or enter an unavailable local port, then use API Health Check or submit a question.
The UI should report that the Agent API is unavailable and remain interactive. Restore the correct
URL before continuing.

## Acceptance Checklist

- Streamlit starts without a provider credential in the frontend.
- The UI can call the existing business endpoint and render an answer.
- Sources, retrieval debug, and memory debug are visible when returned.
- Follow-up contextualization can be inspected in buffer mode.
- Missing sources and unavailable API states are handled explicitly.
- No complete chunk content, local absolute path, or API key is displayed.
