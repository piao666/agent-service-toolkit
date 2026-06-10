# Provider Validation

## Phase 5 Goal

Phase 5 validates the model provider wiring used by the enterprise RAG backend. The goal is to confirm that DeepSeek and Qwen/OpenAI-compatible configuration can be used by the existing model selection path and by `POST /enterprise/agent/query`.

This phase does not add a new Agent workflow, retriever, endpoint, QA benchmark, training job, or fine-tuning workflow.

## Provider Configuration

### DeepSeek

Required configuration:

```text
DEEPSEEK_API_KEY=
DEFAULT_MODEL=deepseek-chat
```

DeepSeek is used for local development, prompt debugging, Chinese responses, and baseline behavior checks.

### Qwen/OpenAI-Compatible

Required configuration:

```text
COMPATIBLE_MODEL=
COMPATIBLE_API_KEY=
COMPATIBLE_BASE_URL=
```

OpenAI-compatible means protocol compatibility. It can point to Qwen, vLLM, or another private inference service that exposes an OpenAI-compatible chat endpoint. It does not require using a public OpenAI API.

## vLLM Positioning

vLLM is an optional model serving layer, not a required dependency of this FastAPI backend. The backend only needs a reachable OpenAI-compatible endpoint.

```text
FastAPI / Agent backend
  -> OpenAI-compatible API
  -> Qwen / vLLM inference service
```

## Validation Commands

```powershell
python scripts\test_model_providers.py --provider deepseek --prompt "请用一句中文说明 RAG 的作用。"
```

```powershell
python scripts\test_model_providers.py --provider compatible --prompt "请用一句中文说明企业知识库 Agent 的作用。"
```

```powershell
python scripts\test_model_providers.py --provider enterprise-query --model deepseek-chat --query "RAG 在企业知识库 Agent 中的作用是什么？" --top-k 5
```

## Validation Results

| Provider | Scenario | Status | Model | Endpoint | Notes |
| --- | --- | --- | --- | --- | --- |
| DeepSeek | direct chat | pass | deepseek-chat | https://api.deepseek.com | Returned a Chinese explanation of RAG. |
| DeepSeek | enterprise query | pass | deepseek-chat | configured | `POST /enterprise/agent/query` returned `status_code=200`, `retrieval_hit_count=5`, and `fallback.triggered=false`. |
| Qwen/OpenAI-compatible | direct chat | pass | qwen-plus | https://dashscope.aliyuncs.com/compatible-mode/v1 | Returned a Chinese explanation through the configured OpenAI-compatible endpoint. |
| Qwen/OpenAI-compatible | enterprise query | not run | openai-compatible | configured | Not executed in this environment because it would send retrieved knowledge-base context to an external compatible endpoint. Run only after explicit approval for that data flow. |

## Current Environment Notes

- DeepSeek API key is configured locally and direct chat is reachable outside the sandbox.
- OpenAI-compatible configuration is present locally with model `qwen-plus` and a configured compatible endpoint.
- Direct compatible chat is reachable outside the sandbox.
- Enterprise query with `openai-compatible` model was not executed because it would export retrieved knowledge-base context to an external endpoint during validation.

## Result Policy

- Record `pass` only when the command completes successfully.
- Record `fail` with a clear error type and short error summary when the endpoint is configured but the call fails.
- Record `not available` when configuration or endpoint access is missing in the current environment.
- Do not write real API keys, full tracebacks, or private endpoint credentials into this document.
