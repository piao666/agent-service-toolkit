from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from dotenv import load_dotenv  # noqa: E402

from agents.enterprise_tools import build_enterprise_retrieval_payload  # noqa: E402
from rag.config import rag_settings  # noqa: E402

DEFAULT_QUERIES = [
    "RAG 在企业知识库 Agent 中的作用是什么？",
    "Prompt 约束如何减少 Agent 幻觉？",
    "DeepSeek 和 Qwen provider 在系统中分别适合什么用途？",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Test the enterprise retriever tool.")
    parser.add_argument("--query", action="append", nargs="?", const="", default=None)
    parser.add_argument("--top-k", type=int, default=None)
    parser.add_argument("--persist-dir", default=None)
    parser.add_argument("--collection-name", default=None)
    return parser.parse_args()


def summarize(payload: dict) -> dict:
    summary = {
        "fallback": payload["fallback"],
        "retrieval_debug": payload["retrieval_debug"],
        "sources": payload["sources"],
    }
    if payload["fallback"]["triggered"]:
        summary["context"] = payload["context"]
    else:
        summary["context_preview"] = payload["context"][:800]
    return summary


def main() -> None:
    load_dotenv()
    args = parse_args()
    queries = args.query or DEFAULT_QUERIES
    payloads = []
    for query in queries:
        payload = build_enterprise_retrieval_payload(
            query=query,
            top_k=args.top_k,
            persist_dir=args.persist_dir or rag_settings.CHROMA_PERSIST_DIR,
            collection_name=args.collection_name or rag_settings.CHROMA_COLLECTION_NAME,
        )
        payloads.append({"query": query, "result": summarize(payload)})

    print(json.dumps(payloads, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
