from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_DIR = REPO_ROOT / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from fastapi.testclient import TestClient  # noqa: E402
from langchain_core.messages import AIMessage, HumanMessage  # noqa: E402

import agents.enterprise_rag_agent as enterprise_rag_module  # noqa: E402


class LocalTestModel:
    async def ainvoke(self, messages: list[Any], config: dict[str, Any] | None = None) -> AIMessage:
        return AIMessage(
            content=(
                "RAG 在企业知识库 Agent 中用于把用户问题转换为可检索的上下文查询，"
                "并基于命中的知识片段生成受约束的回答。"
            )
        )


def apply_script_config(args: argparse.Namespace) -> None:
    if args.persist_dir:
        from rag.config import rag_settings

        rag_settings.CHROMA_PERSIST_DIR = args.persist_dir


async def run_agent(args: argparse.Namespace) -> dict[str, Any]:
    if not args.use_configured_model:
        enterprise_rag_module.get_model = lambda model_name: LocalTestModel()

    result = await enterprise_rag_module.enterprise_rag_agent.ainvoke(
        {"messages": [HumanMessage(content=args.query)]},
        config={
            "configurable": {
                "thread_id": args.thread_id,
                "user_id": args.user_id,
                "top_k": args.top_k,
            }
        },
    )
    message = result["messages"][-1]
    metadata = message.response_metadata
    return {
        "query": args.query,
        "top_k": args.top_k,
        "use_configured_model": args.use_configured_model,
        "answer": message.content,
        "source_count": len(metadata.get("sources", [])),
        "sources": metadata.get("sources", []),
        "retrieval_debug": metadata.get("retrieval_debug", {}),
        "fallback": metadata.get("fallback", {}),
        "model_debug": metadata.get("model_debug", {}),
    }


def run_service_endpoint(args: argparse.Namespace) -> dict[str, Any]:
    if not args.use_configured_model:
        enterprise_rag_module.get_model = lambda model_name: LocalTestModel()

    from service.service import app

    with TestClient(app) as client:
        response = client.post(
            "/enterprise-rag-agent/invoke",
            json={
                "message": args.query,
                "thread_id": args.thread_id,
                "user_id": args.user_id,
                "agent_config": {"top_k": args.top_k},
            },
        )
    payload = response.json()
    metadata = payload.get("response_metadata", {})
    return {
        "status_code": response.status_code,
        "query": args.query,
        "top_k": args.top_k,
        "use_configured_model": args.use_configured_model,
        "answer": payload.get("content", ""),
        "source_count": len(metadata.get("sources", [])),
        "sources": metadata.get("sources", []),
        "retrieval_debug": metadata.get("retrieval_debug", {}),
        "fallback": metadata.get("fallback", {}),
        "model_debug": metadata.get("model_debug", {}),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Test the enterprise RAG agent graph.")
    parser.add_argument(
        "--query",
        nargs="?",
        const="",
        default="RAG 在企业知识库 Agent 中的作用是什么？",
        help="User question to send to the agent.",
    )
    parser.add_argument("--top-k", type=int, default=5, help="Retriever top_k.")
    parser.add_argument("--persist-dir", default=None, help="Chroma persist directory.")
    parser.add_argument("--thread-id", default="phase3-agent-test")
    parser.add_argument("--user-id", default="local-user")
    parser.add_argument(
        "--use-configured-model",
        action="store_true",
        help="Use the configured chat model instead of the local test model.",
    )
    parser.add_argument(
        "--via-service",
        action="store_true",
        help="Call POST /enterprise-rag-agent/invoke through FastAPI TestClient.",
    )
    args = parser.parse_args()
    apply_script_config(args)
    payload = run_service_endpoint(args) if args.via_service else asyncio.run(run_agent(args))
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
