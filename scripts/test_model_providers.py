from __future__ import annotations

import argparse
import asyncio
import json
import sys
import traceback
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from fastapi.testclient import TestClient  # noqa: E402
from langchain_core.messages import HumanMessage  # noqa: E402

from core import get_model, settings  # noqa: E402
from schema.models import DeepseekModelName, OpenAICompatibleName  # noqa: E402


def _secret_configured(value: Any) -> bool:
    return value is not None and str(value) != ""


def _error_summary(exc: Exception) -> dict[str, str]:
    message = str(exc).replace("\n", " ").strip()
    return {
        "error_type": type(exc).__name__,
        "error_summary": message[:300],
    }


def _provider_config(provider: str) -> dict[str, Any]:
    if provider == "deepseek":
        return {
            "provider": "deepseek",
            "model": DeepseekModelName.DEEPSEEK_CHAT.value,
            "base_url": "https://api.deepseek.com",
            "api_key_configured": _secret_configured(settings.DEEPSEEK_API_KEY),
        }
    if provider == "compatible":
        return {
            "provider": "openai-compatible",
            "model": settings.COMPATIBLE_MODEL,
            "base_url": settings.COMPATIBLE_BASE_URL,
            "api_key_configured": _secret_configured(settings.COMPATIBLE_API_KEY),
        }
    raise ValueError(f"Unsupported provider: {provider}")


async def _run_direct_chat(provider: str, prompt: str) -> dict[str, Any]:
    config = _provider_config(provider)
    model_name = (
        DeepseekModelName.DEEPSEEK_CHAT
        if provider == "deepseek"
        else OpenAICompatibleName.OPENAI_COMPATIBLE
    )
    if provider == "compatible" and not config["base_url"]:
        return {
            **config,
            "scenario": "direct_chat",
            "status": "not_available",
            "notes": "COMPATIBLE_BASE_URL is not configured.",
        }
    try:
        model = get_model(model_name)
        response = await model.ainvoke([HumanMessage(content=prompt)])
        return {
            **config,
            "scenario": "direct_chat",
            "status": "pass",
            "answer_preview": str(response.content)[:300],
        }
    except Exception as exc:
        return {
            **config,
            "scenario": "direct_chat",
            "status": "fail",
            **_error_summary(exc),
        }


def _run_enterprise_query(model: str, query: str, top_k: int) -> dict[str, Any]:
    from service.service import app

    body = {
        "query": query,
        "session_id": "phase5-provider-validation",
        "top_k": top_k,
        "return_sources": False,
        "model": model,
    }
    with TestClient(app) as client:
        response = client.post("/enterprise/agent/query", json=body)
    payload = response.json()
    return {
        "provider": "enterprise-query",
        "scenario": "enterprise_query",
        "status": "pass" if response.status_code == 200 else "fail",
        "status_code": response.status_code,
        "model": model,
        "answer_preview": payload.get("answer", "")[:300] if isinstance(payload, dict) else "",
        "retrieval_hit_count": (payload.get("retrieval_debug") or {}).get("hit_count")
        if isinstance(payload, dict)
        else None,
        "fallback": payload.get("fallback") if isinstance(payload, dict) else None,
        "model_debug": payload.get("model_debug") if isinstance(payload, dict) else None,
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    if args.provider in {"deepseek", "compatible"}:
        return asyncio.run(_run_direct_chat(args.provider, args.prompt))
    if args.provider == "enterprise-query":
        return _run_enterprise_query(args.model, args.query, args.top_k)
    raise ValueError(f"Unsupported provider: {args.provider}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate enterprise model provider wiring.")
    parser.add_argument(
        "--provider",
        choices=["deepseek", "compatible", "enterprise-query"],
        required=True,
    )
    parser.add_argument(
        "--prompt",
        default="Please explain the role of RAG in one short sentence.",
    )
    parser.add_argument(
        "--query",
        default="RAG 在企业知识库 Agent 中的作用是什么？",
    )
    parser.add_argument("--model", default=DeepseekModelName.DEEPSEEK_CHAT.value)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    try:
        result = run(args)
    except Exception as exc:
        result = {"status": "fail", **_error_summary(exc)}
        if args.verbose:
            result["traceback"] = traceback.format_exc()

    print(json.dumps(result, ensure_ascii=False, indent=2))  # noqa: T201


if __name__ == "__main__":
    main()
