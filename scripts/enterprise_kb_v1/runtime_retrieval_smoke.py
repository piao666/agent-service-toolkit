#!/usr/bin/env python3
"""Phase 4E: HPC Runtime Retrieval Smoke Test — 10 queries against bge-m3 official_docs index.

HPC 独立运行，不依赖项目 Python 包。直接用 SentenceTransformer + chromadb。
输出 trace JSONL + results JSON 到 ~/jupyterlab/RAG/A/。

Trace 每行必含 13 字段：
query, top_k, embedding_model, collection_name, persist_dir,
retrieved_chunk_ids, retrieved_source_ids, scores,
origin_urls, heading_paths, text_previews, latency_ms, errors
"""

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import torch
from sentence_transformers import SentenceTransformer
import chromadb
import yaml

# ── HPC 路径常量（与 hpc_phase4d_build_bge_m3_index.py 一致）────────────────
PROJECT = Path.home() / "jupyterlab" / "RAG" / "agent-service-toolkit-clean"
A_DIR = Path.home() / "jupyterlab" / "RAG" / "A"
MODEL_ROOT = Path.home() / "jupyterlab" / "models"
PERSIST_DIR_NAME = "storage/chroma_enterprise_kb_v1_bge_m3"
COLLECTION_NAME = "enterprise_kb_v1_official_docs_bge_m3"
MODEL_PATH = MODEL_ROOT / "bge-m3"
CHROMA_DIR = PROJECT / PERSIST_DIR_NAME
REGISTRY_PATH = PROJECT / "data" / "enterprise_kb_v1" / "source_registry" / "source_registry.yaml"

# ── 10 条 smoke query（覆盖 5 个项目，中英双语）────────────────────────────
SMOKE_QUERIES = [
    {"id": "smoke_001", "query": "How to create a Chroma collection with cosine similarity?", "target": "Chroma", "lang": "en"},
    {"id": "smoke_002", "query": "Chroma 如何选择一个 collection?", "target": "Chroma", "lang": "zh"},
    {"id": "smoke_003", "query": "FastAPI request body validation with Pydantic BaseModel", "target": "FastAPI", "lang": "en"},
    {"id": "smoke_004", "query": "FastAPI 请求体是如何被验证的?", "target": "FastAPI", "lang": "zh"},
    {"id": "smoke_005", "query": "LangGraph StateGraph nodes and edges construction", "target": "LangGraph", "lang": "en"},
    {"id": "smoke_006", "query": "OpenAI chat completion streaming with tool calls", "target": "OpenAI", "lang": "en"},
    {"id": "smoke_007", "query": "Pydantic Field validators and custom validation functions", "target": "Pydantic", "lang": "en"},
    {"id": "smoke_008", "query": "什么是 retrieval augmented generation?", "target": "RAG", "lang": "zh"},
    {"id": "smoke_009", "query": "chroma collection embedding function", "target": "Chroma", "lang": "en"},
    {"id": "smoke_010", "query": "如何在 LangGraph 中定义 conditional edges?", "target": "LangGraph", "lang": "zh"},
]

TOP_K = 5
TEXT_PREVIEW_LEN = 200


def _build_source_url_map() -> dict[str, str]:
    """从 source_registry.yaml 构建 source_id → origin_url 映射。"""
    if not REGISTRY_PATH.exists():
        print(f"WARNING: source_registry not found at {REGISTRY_PATH}")
        return {}
    with open(REGISTRY_PATH, encoding="utf-8") as f:
        registry = yaml.safe_load(f)
    url_map: dict[str, str] = {}
    for src in registry.get("sources", []):
        sid = src.get("source_id", "")
        url = src.get("origin_url") or ""
        if sid and url:
            url_map[sid] = url
    return url_map


def main() -> None:
    print("=" * 60)
    print("Phase 4E: HPC Runtime Retrieval Smoke Test")
    print(f"Start: {datetime.now(timezone.utc).isoformat()}")
    print("=" * 60)

    # ── GPU 检查 ──────────────────────────────────────────────────────────
    if not torch.cuda.is_available():
        print("FATAL: CUDA not available"); sys.exit(1)
    gpu_name = torch.cuda.get_device_name(0)
    gpu_mem_gb = round(torch.cuda.get_device_properties(0).total_memory / 1e9, 1)
    print(f"GPU: {gpu_name} ({gpu_mem_gb} GB)")

    # ── 加载 bge-m3 ───────────────────────────────────────────────────────
    print(f"Loading model: {MODEL_PATH}")
    t0 = time.perf_counter()
    model = SentenceTransformer(str(MODEL_PATH), device="cuda")
    dim = model.get_embedding_dimension()
    load_s = round(time.perf_counter() - t0, 1)
    print(f"Loaded: dim={dim}, time={load_s}s")

    # ── 连接 Chroma 索引 ──────────────────────────────────────────────────
    if not CHROMA_DIR.exists():
        print(f"FATAL: Chroma persist dir not found: {CHROMA_DIR}"); sys.exit(1)
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    try:
        col = client.get_collection(COLLECTION_NAME)
    except Exception as e:
        print(f"FATAL: collection not found: {e}"); sys.exit(1)
    chunk_count = col.count()
    print(f"Collection: {COLLECTION_NAME}, chunks={chunk_count}")

    # ── 构建 source_id → origin_url 映射 ──────────────────────────────────
    url_map = _build_source_url_map()
    print(f"Source URL map: {len(url_map)} entries")

    print()

    # ── 逐条 smoke query ──────────────────────────────────────────────────
    A_DIR.mkdir(parents=True, exist_ok=True)
    trace_path = A_DIR / "phase4e_runtime_retrieval_trace_samples.jsonl"
    results_path = A_DIR / "phase4e_hpc_runtime_retrieval_results.json"

    all_traces: list[dict] = []
    summary_rows: list[dict] = []
    total_queries = len(SMOKE_QUERIES)
    queries_with_results = 0

    with open(trace_path, "w", encoding="utf-8") as trace_f:
        for i, sq in enumerate(SMOKE_QUERIES):
            qid = sq["id"]
            query_text = sq["query"]
            t_start = time.perf_counter()

            q_emb = model.encode([query_text], show_progress_bar=False).tolist()
            res = col.query(
                query_embeddings=q_emb,
                n_results=TOP_K,
                include=["metadatas", "distances", "documents"],
            )

            latency_ms = round((time.perf_counter() - t_start) * 1000, 2)

            metadatas = res["metadatas"][0] if res["metadatas"] else []
            distances = res["distances"][0] if res["distances"] else []
            documents = res["documents"][0] if res["documents"] else []

            chunk_ids: list[str] = []
            source_ids: list[str] = []
            scores: list[float] = []
            origin_urls: list[str] = []
            heading_paths: list[str] = []
            text_previews: list[str] = []

            for j, (meta, dist, doc) in enumerate(zip(metadatas, distances, documents)):
                chunk_id = str(meta.get("chunk_id", f"unknown_{j}"))
                source_id = str(meta.get("source_id", "unknown"))
                heading = str(meta.get("heading_path", ""))
                origin_url = url_map.get(source_id, source_id)

                chunk_ids.append(chunk_id)
                source_ids.append(source_id)
                scores.append(round(1 / (1 + max(dist, 0.0)), 4))
                origin_urls.append(origin_url)
                heading_paths.append(heading)
                # 文本预览：前200字符，去除多余空白
                normalized = " ".join((doc or "").split())
                text_previews.append(normalized[:TEXT_PREVIEW_LEN])

            hit_count = len(metadatas)
            if hit_count > 0:
                queries_with_results += 1

            trace_record = {
                "query": query_text,
                "top_k": TOP_K,
                "embedding_model": "bge-m3",
                "collection_name": COLLECTION_NAME,
                "persist_dir": PERSIST_DIR_NAME,
                "retrieved_chunk_ids": chunk_ids,
                "retrieved_source_ids": list(dict.fromkeys(source_ids)),
                "scores": scores,
                "origin_urls": origin_urls,
                "heading_paths": heading_paths,
                "text_previews": text_previews,
                "latency_ms": latency_ms,
                "errors": [],
            }
            all_traces.append(trace_record)
            trace_f.write(json.dumps(trace_record, ensure_ascii=False) + "\n")

            top_score = scores[0] if scores else 0
            status = "OK" if hit_count > 0 else "EMPTY"
            print(f"  [{i + 1:2d}/{total_queries}] {status} "
                  f"hits={hit_count} top_score={top_score:.4f} "
                  f"latency={latency_ms:.1f}ms  {qid}")

            summary_rows.append({
                "query_id": qid,
                "query": query_text,
                "hit_count": hit_count,
                "top_score": round(scores[0], 4) if scores else 0,
                "latency_ms": latency_ms,
                "top_source_ids": source_ids[:3],
            })

    # ── 汇总结果 JSON ──────────────────────────────────────────────────────
    avg_latency = round(sum(t["latency_ms"] for t in all_traces) / total_queries, 2)
    trace_field_coverage = {
        "query": all("query" in t for t in all_traces),
        "top_k": all("top_k" in t for t in all_traces),
        "embedding_model": all("embedding_model" in t for t in all_traces),
        "collection_name": all("collection_name" in t for t in all_traces),
        "persist_dir": all("persist_dir" in t for t in all_traces),
        "retrieved_chunk_ids": all("retrieved_chunk_ids" in t for t in all_traces),
        "retrieved_source_ids": all("retrieved_source_ids" in t for t in all_traces),
        "scores": all("scores" in t for t in all_traces),
        "origin_urls": all("origin_urls" in t for t in all_traces),
        "heading_paths": all("heading_paths" in t for t in all_traces),
        "text_previews": all("text_previews" in t for t in all_traces),
        "latency_ms": all("latency_ms" in t for t in all_traces),
        "errors": all("errors" in t for t in all_traces),
    }

    results_summary = {
        "phase": "4E",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "environment": "HPC",
        "gpu": {"name": gpu_name, "memory_gb": gpu_mem_gb},
        "model": {"name": "bge-m3", "path": str(MODEL_PATH), "dim": dim, "load_time_s": load_s},
        "collection": {"name": COLLECTION_NAME, "persist_dir": str(CHROMA_DIR), "chunk_count": chunk_count},
        "source_url_map_entries": len(url_map),
        "smoke_test": {
            "total_queries": total_queries,
            "queries_with_results": queries_with_results,
            "queries_with_zero_results": total_queries - queries_with_results,
            "all_queries_pass": queries_with_results == total_queries,
            "avg_latency_ms": avg_latency,
            "top_k": TOP_K,
        },
        "trace_field_coverage": trace_field_coverage,
        "trace_all_fields_complete": all(trace_field_coverage.values()),
        "summary": summary_rows,
    }

    with open(results_path, "w", encoding="utf-8") as f:
        json.dump(results_summary, f, ensure_ascii=False, indent=2)

    print(f"\n{'=' * 60}")
    print(f"Total: {total_queries} queries, {queries_with_results} with results")
    print(f"All pass: {queries_with_results == total_queries}")
    print(f"Trace fields all complete: {results_summary['trace_all_fields_complete']}")
    print(f"Avg latency: {avg_latency}ms")
    print(f"Trace:       {trace_path}")
    print(f"Results:     {results_path}")
    print(f"{'=' * 60}")
    print("DONE: Phase 4E HPC Runtime Retrieval Smoke Test")


if __name__ == "__main__":
    main()
