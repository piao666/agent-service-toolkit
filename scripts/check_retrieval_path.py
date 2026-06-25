#!/usr/bin/env python3
"""Retrieval path audit — read-only, no LLM, no Chroma write.

Tests specific queries against the current retriever, outputs top_k sources for diagnosis.
"""
from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC = REPO_ROOT / "src"
sys.path.insert(0, str(SRC))

os.environ.setdefault("USE_FAKE_MODEL", "true")
os.environ.setdefault("ENTERPRISE_MEMORY_MODE", "buffer")
os.environ.setdefault("ENTERPRISE_STRUCTURED_RETRIEVAL_MODE", "metadata_symbol")
os.environ.setdefault("ENTERPRISE_EVIDENCE_VERIFIER_MODE", "rule_based")
os.environ.setdefault("ENTERPRISE_MULTI_HOP_MODE", "off")
os.environ.setdefault("ENTERPRISE_PLANNER_MODE", "debug_only")
os.environ.setdefault("DATABASE_TYPE", "sqlite")
os.environ.setdefault("MODE", "prod")
os.environ.setdefault("CHROMA_PERSIST_DIR", "./chroma_enterprise")
os.environ.setdefault("CHROMA_COLLECTION_NAME", "enterprise_ai_learning_kb_reviewed")
os.environ.setdefault("LOCAL_EMBEDDING_MODEL_ROOT", str(REPO_ROOT / "models"))

from rag.retriever import retrieve, retrieve_with_overlay
from rag.retrieval_policy import decide_overlay

TEST_QUERIES = [
    {
        "query": "FastAPI 的 Request Body 如何定义？",
        "expected_terms": ["fastapi", "request body", "pydantic", "请求体"],
        "is_external_tech": True,
    },
    {
        "query": "LoRA 有什么作用？",
        "expected_terms": ["lora", "微调", "低秩", "fine-tune"],
        "is_external_tech": True,
    },
    {
        "query": "RAG 是什么？",
        "expected_terms": ["rag", "检索", "retrieval", "增强", "生成"],
        "is_external_tech": False,
    },
    {
        "query": "这个系统是如何进行检索的？",
        "expected_terms": ["检索", "向量", "chroma", "retrieval", "pipeline"],
        "is_external_tech": False,
    },
]

GENERIC_ENTERPRISE_PREFIXES = (
    "enterprise_prompt_guidelines",
    "enterprise_model_provider_policy",
    "enterprise_agent_overview",
)
PREVIEW_MAX = 160


def _safe_preview(text: str) -> str:
    clean = text.replace("\n", " ").replace("\r", " ")[:PREVIEW_MAX]
    clean = re.sub(r"sk-[A-Za-z0-9_-]{12,}", "[REDACTED]", clean)
    return clean.strip()


def diagnose_query(query_info: dict[str, Any], top_k_values: list[int]) -> dict[str, Any]:
    q = query_info["query"]
    expected = [t.lower() for t in query_info["expected_terms"]]
    is_ext = query_info["is_external_tech"]
    results: dict[str, Any] = {"query": q, "expected_terms": expected, "is_external_tech": is_ext, "runs": {}}

    for tk in top_k_values:
        try:
            raw_results = retrieve(q, top_k=tk)
        except Exception as e:
            results["runs"][str(tk)] = {"error": str(e)[:200]}
            continue

        run: dict[str, Any] = {"top_k": tk, "source_count": len(raw_results), "sources": []}
        generic_count = 0
        expected_hits = 0
        for r in raw_results:
            source_id = str(getattr(r, "source", "") or "")
            metadata = getattr(r, "metadata", {}) or {}
            chunk_id = str(getattr(r, "chunk_id", "") or "")
            title = str(metadata.get("title", "") or getattr(r, "title", "") or "")
            content = str(getattr(r, "content_preview", "") or getattr(r, "page_content", "") or "")
            combined = f"{source_id} {title} {chunk_id} {content}".lower()

            is_generic = source_id.startswith(GENERIC_ENTERPRISE_PREFIXES)
            if is_generic:
                generic_count += 1

            term_hits = [t for t in expected if t in combined]
            if term_hits:
                expected_hits += 1

            run["sources"].append({
                "source_id": source_id,
                "chunk_id": chunk_id,
                "title": title[:100],
                "preview": _safe_preview(content),
                "score": round(float(getattr(r, "relevance_score", 0) or 0), 4),
                "is_generic": is_generic,
                "term_hits": term_hits[:5],
            })

        run["generic_enterprise_docs_count"] = generic_count
        run["expected_term_hits_in_top_k"] = expected_hits
        run["expected_source_found"] = expected_hits > 0

        # Diagnosis
        if expected_hits == 0:
            if generic_count >= len(raw_results) - 1:
                run["diagnosis"] = "all sources are generic enterprise docs; expected content may not be in top_k"
            else:
                run["diagnosis"] = "expected content exists in corpus but not retrieved into top_k"
        elif generic_count > len(raw_results) // 2:
            run["diagnosis"] = "generic enterprise docs dominating ranking; expected content present but ranked lower"
        else:
            run["diagnosis"] = "reasonable mix of sources"

        results["runs"][str(tk)] = run

    return results


def main():
    print("Retrieval Path Audit")
    all_results = []
    for qi in TEST_QUERIES:
        print(f"\n=== {qi['query'][:50]} ===")
        diag = diagnose_query(qi, [5, 10, 20])
        all_results.append(diag)
        for tk_str, run in diag["runs"].items():
            if "error" in run:
                print(f"  top_k={tk_str}: ERROR {run['error']}")
                continue
            print(f"  top_k={tk_str}: src={run['source_count']} generic={run['generic_enterprise_docs_count']} term_hits={run['expected_term_hits_in_top_k']} diagnosis={run['diagnosis']}")
            for s in run["sources"][:3]:
                print(f"    {s['source_id']:40s} {s['title'][:50]:50s} score={s['score']} generic={s['is_generic']}")

    # Write report
    eval_dir = REPO_ROOT / "data" / "knowledge_base" / "evaluation"
    eval_dir.mkdir(parents=True, exist_ok=True)
    report_path = eval_dir / "retrieval_path_audit_report.json"
    report_path.write_text(json.dumps(all_results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nReport: {report_path}")


if __name__ == "__main__":
    main()
