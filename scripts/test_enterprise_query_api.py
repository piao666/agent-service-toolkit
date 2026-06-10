from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from fastapi.testclient import TestClient  # noqa: E402
from langchain_core.messages import AIMessage  # noqa: E402

import agents.enterprise_rag_agent as enterprise_rag_module  # noqa: E402


def contains_cjk(text: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in text)


def requests_english(text: str) -> bool:
    normalized = text.lower()
    return any(
        request in normalized
        for request in {
            "answer in english",
            "respond in english",
            "use english",
            "in english",
            "用英文",
            "使用英文",
            "英文回答",
            "英语回答",
        }
    )


class LocalTestModel:
    async def ainvoke(self, messages: list[Any], config: dict[str, Any] | None = None) -> AIMessage:
        user_prompt = "\n".join(str(getattr(message, "content", "")) for message in messages)
        question = user_prompt
        if "User question:\n" in user_prompt:
            question = user_prompt.split("User question:\n", 1)[1].split("\n\n", 1)[0]
        if contains_cjk(question) and not requests_english(question):
            return AIMessage(
                content=(
                    "RAG 会使用检索到的知识库片段约束回答，并返回 source tracing "
                    "元数据，便于核验答案依据。"
                )
            )
        return AIMessage(
            content=(
                "RAG uses retrieved knowledge-base chunks to ground the answer and return "
                "source-tracing metadata for verification."
            )
        )


def parse_bool(value: str) -> bool:
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "y"}:
        return True
    if normalized in {"0", "false", "no", "n"}:
        return False
    raise argparse.ArgumentTypeError("Expected a boolean value.")


def run_request(args: argparse.Namespace) -> dict[str, Any]:
    if not args.use_configured_model:
        enterprise_rag_module.get_model = lambda model_name: LocalTestModel()

    from service.service import app

    body: dict[str, Any] = {
        "query": args.query,
        "session_id": args.session_id,
        "top_k": args.top_k,
        "return_sources": args.return_sources,
    }
    if args.model:
        body["model"] = args.model

    with TestClient(app) as client:
        response = client.post("/enterprise/agent/query", json=body)

    try:
        payload = response.json()
    except Exception:
        payload = {"raw_response": response.text}

    sources = payload.get("sources", []) if isinstance(payload, dict) else []
    retrieval_debug = payload.get("retrieval_debug", {}) if isinstance(payload, dict) else {}
    answer = payload.get("answer") if isinstance(payload, dict) else None
    model_debug = payload.get("model_debug", {}) if isinstance(payload, dict) else {}
    return {
        "status_code": response.status_code,
        "answer": answer,
        "source_count": len(sources),
        "retrieval_debug_hit_count": retrieval_debug.get("hit_count"),
        "latency_ms": payload.get("latency_ms") if isinstance(payload, dict) else None,
        "model_debug": model_debug,
        "fallback": payload.get("fallback") if isinstance(payload, dict) else None,
        "answer_contains_cjk": contains_cjk(answer or ""),
        "expected_cjk_answer": contains_cjk(args.query) and not requests_english(args.query),
        "response": payload,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Test the enterprise query API endpoint.")
    parser.add_argument(
        "--query",
        nargs="?",
        const="",
        default="What is the role of RAG in an enterprise knowledge-base agent?",
        help="User question to send to the enterprise query endpoint.",
    )
    parser.add_argument("--session-id", default="phase4-test-001")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--return-sources", type=parse_bool, default=True)
    parser.add_argument("--model", default=None)
    parser.add_argument(
        "--use-configured-model",
        action="store_true",
        help="Use the configured chat model instead of the local test model.",
    )
    args = parser.parse_args()
    result = run_request(args)
    print(json.dumps(result, ensure_ascii=False, indent=2))  # noqa: T201


if __name__ == "__main__":
    main()
