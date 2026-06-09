from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from dotenv import load_dotenv

from rag.config import rag_settings
from rag.retriever import retrieve


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Test enterprise Chroma retrieval.")
    parser.add_argument("--query", required=True)
    parser.add_argument("--top-k", type=int, default=None)
    parser.add_argument("--persist-dir", default=None)
    parser.add_argument("--collection-name", default=None)
    return parser.parse_args()


def main() -> None:
    load_dotenv()
    args = parse_args()
    results = retrieve(
        args.query,
        top_k=args.top_k or rag_settings.RAG_DEFAULT_TOP_K,
        persist_dir=args.persist_dir or rag_settings.CHROMA_PERSIST_DIR,
        collection_name=args.collection_name or rag_settings.CHROMA_COLLECTION_NAME,
    )
    payload = {
        "query": args.query,
        "top_k": args.top_k or rag_settings.RAG_DEFAULT_TOP_K,
        "persist_dir": args.persist_dir or rag_settings.CHROMA_PERSIST_DIR,
        "collection_name": args.collection_name or rag_settings.CHROMA_COLLECTION_NAME,
        "result_count": len(results),
        "results": [result.model_dump() for result in results],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
