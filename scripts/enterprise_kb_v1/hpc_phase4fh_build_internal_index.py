#!/usr/bin/env python3
"""Phase 4F HPC: Build internal_engineering_docs bge-m3 index.

HPC 独立运行，参照 hpc_phase4d_build_bge_m3_index.py 模式。
输出 phase4fh_internal_index_manifest.json 到 A_DIR。
"""

import json, sys, time
from datetime import datetime, timezone
from pathlib import Path

import torch
from sentence_transformers import SentenceTransformer
import chromadb

# ── HPC 路径常量 ──────────────────────────────────────────────────────────
PROJECT = Path.home() / "jupyterlab" / "RAG" / "agent-service-toolkit-clean"
A_DIR = Path.home() / "jupyterlab" / "RAG" / "A"
MODEL_ROOT = Path.home() / "jupyterlab" / "models"
MODEL_PATH = MODEL_ROOT / "bge-m3"
COLLECTION_NAME = "enterprise_kb_v1_internal_engineering_bge_m3"
PERSIST_DIR = str(PROJECT / "storage" / "chroma_enterprise_kb_v1_internal_bge_m3")
CHUNKS_PATH = PROJECT / "data" / "enterprise_kb_v1" / "chunks" / "internal_engineering_docs" / "all_chunks.jsonl"

BATCH_SIZE = 100


def main() -> None:
    print("=" * 60)
    print("Phase 4F HPC: Build Internal Engineering Index")
    print(f"Model: {MODEL_PATH}")
    print(f"Collection: {COLLECTION_NAME}")
    print(f"Persist: {PERSIST_DIR}")
    print("=" * 60)

    if not torch.cuda.is_available():
        print("FATAL: CUDA not available"); sys.exit(1)
    gpu_name = torch.cuda.get_device_name(0)
    gpu_mem = round(torch.cuda.get_device_properties(0).total_memory / 1e9, 1)
    print(f"GPU: {gpu_name} ({gpu_mem} GB)")

    # ── Load chunks ────────────────────────────────────────────────────
    if not CHUNKS_PATH.exists():
        print(f"FATAL: chunks not found: {CHUNKS_PATH}"); sys.exit(1)
    chunks = []
    with open(CHUNKS_PATH, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                chunks.append(json.loads(line))
    print(f"Chunks loaded: {len(chunks)}")

    # ── Load model ─────────────────────────────────────────────────────
    t0 = time.perf_counter()
    print(f"Loading model: {MODEL_PATH}")
    model = SentenceTransformer(str(MODEL_PATH), device="cuda")
    dim = model.get_embedding_dimension()
    load_s = round(time.perf_counter() - t0, 1)
    print(f"Model: dim={dim}, load_time={load_s}s")

    # ── Build Chroma index ─────────────────────────────────────────────
    torch.cuda.reset_peak_memory_stats()
    client = chromadb.PersistentClient(path=PERSIST_DIR)
    try:
        client.delete_collection(COLLECTION_NAME)
    except Exception:
        pass
    col = client.create_collection(COLLECTION_NAME, metadata={"hnsw:space": "cosine"})

    t_build = time.perf_counter()
    source_ids: set[str] = set()
    failed = 0
    for i in range(0, len(chunks), BATCH_SIZE):
        batch = chunks[i : i + BATCH_SIZE]
        texts = [c["text"] for c in batch]
        ids_list = [c["chunk_id"] for c in batch]
        metadatas = [
            {
                "chunk_id": c["chunk_id"],
                "source_id": c["source_id"],
                "corpus": c.get("corpus", "internal_engineering_docs"),
                "source_type": c.get("source_type", ""),
                "domain": c.get("domain", ""),
                "title": c.get("title", ""),
                "local_path": c.get("local_path", ""),
                "heading_path": c.get("heading_path", ""),
                "answer_scope": c.get("answer_scope", ""),
                "version": c.get("version", "v1"),
            }
            for c in batch
        ]
        try:
            embeddings = model.encode(texts, show_progress_bar=False).tolist()
            col.add(ids=ids_list, documents=texts, metadatas=metadatas, embeddings=embeddings)
            for c in batch:
                source_ids.add(c["source_id"])
        except Exception as e:
            print(f"  batch {i // BATCH_SIZE} failed: {e}")
            failed += len(batch)

    build_s = round(time.perf_counter() - t_build, 1)
    gpu_used = round(torch.cuda.max_memory_allocated() / 1e9, 2)

    # ── Manifest ───────────────────────────────────────────────────────
    manifest = {
        "phase": "4F",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "embedding_model": "bge-m3",
        "embedding_dimension": dim,
        "collection_name": COLLECTION_NAME,
        "persist_dir": PERSIST_DIR,
        "indexed_source_count": len(source_ids),
        "indexed_chunk_count": col.count(),
        "failed_chunks": failed,
        "build_time_seconds": build_s,
        "gpu_name": gpu_name,
        "gpu_memory_used_gb": gpu_used,
    }

    A_DIR.mkdir(parents=True, exist_ok=True)
    manifest_path = A_DIR / "phase4fh_internal_index_manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    print(f"\nIndexed: {manifest['indexed_chunk_count']} chunks from {manifest['indexed_source_count']} sources")
    print(f"Build time: {build_s}s, GPU mem: {gpu_used}GB")
    print(f"Failed chunks: {failed}")
    print(f"Manifest → {manifest_path}")
    print("DONE: Phase 4F HPC Index Build")


if __name__ == "__main__":
    main()
