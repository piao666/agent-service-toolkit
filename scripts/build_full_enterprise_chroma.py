"""构建 full/eval Chroma corpus (~581 chunks)。

步骤:
1. 用 ingest_phase6_chroma.py 函数写入 phase6 full Chroma (limit=100000, 实际约 575)
2. 用 build_final_enterprise_chroma.py 的合并逻辑合并 enterprise_docs → final full Chroma

不修改任何核心链路文件。
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

try:
    from datetime import UTC as DATETIME_UTC
except ImportError:
    DATETIME_UTC = timezone.utc

import chromadb  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

from rag.document_loader import load_documents  # noqa: E402
from rag.embeddings import get_embedding_model  # noqa: E402
from rag.splitter import split_documents  # noqa: E402

# ── 复用现有脚本的函数 ──
from ingest_phase6_chroma import (  # noqa: E402
    _build_records,
    _clear_collection,
    _is_allowed_candidate,
    _load_jsonl,
    _metadata,
    _recover_chunk_text,
)

PHASE6_FULL_DIR = "chroma_enterprise_phase6_full"
PHASE6_FULL_COLLECTION = "enterprise_ai_learning_kb_reviewed"
FINAL_FULL_DIR = "chroma_enterprise_full"
FINAL_FULL_COLLECTION = "enterprise_knowledge_base_full"
ENTERPRISE_DOCS_DIR = "data/enterprise_docs"
CHUNK_MANIFEST = ROOT_DIR / "data" / "knowledge_base" / "manifests" / "chunk_manifest.jsonl"


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build full/eval enterprise Chroma corpus.")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", default=True, help="Plan only (default)")
    mode.add_argument("--execute", action="store_true", help="Write Chroma")
    p.add_argument("--reset-final", action="store_true", help="Clear target dirs before writing (needs --execute)")
    p.add_argument("--device", default="cpu")
    p.add_argument("--limit", type=int, default=100000, help="Max phase6 candidates (default: all ~575)")
    return p.parse_args()


def _build_phase6_full_chroma(limit: int, device: str, execute: bool, reset: bool) -> dict[str, Any]:
    """构建 phase6 full Chroma (无 80-chunk limit)。"""
    chunks_data = _load_jsonl(CHUNK_MANIFEST)
    eligible = [c for c in chunks_data if _is_allowed_candidate(c)]
    info = {
        "manifest_total": len(chunks_data),
        "eligible_count": len(eligible),
        "limit": limit,
    }

    if not execute:
        info["phase6_full_dir"] = PHASE6_FULL_DIR
        info["phase6_full_collection"] = PHASE6_FULL_COLLECTION
        info["phase6_planned_count"] = min(len(eligible), limit)
        return info

    # 写入 phase6 full Chroma
    target_dir = ROOT_DIR / PHASE6_FULL_DIR
    if reset and target_dir.exists():
        shutil.rmtree(target_dir)

    embeddings = get_embedding_model(device=device)
    client = chromadb.PersistentClient(path=str(target_dir))
    try:
        client.delete_collection(PHASE6_FULL_COLLECTION)
    except Exception:
        pass
    coll = client.create_collection(name=PHASE6_FULL_COLLECTION, metadata={"hnsw:space": "cosine"})

    written = 0
    failed = 0
    batch_ids, batch_texts, batch_metas, batch_embs = [], [], [], []
    batch_size = 20

    for chunk in eligible:
        if written >= limit:
            break
        text, error = _recover_chunk_text(chunk)
        if text is None:
            failed += 1
            continue
        meta = _metadata(chunk)
        cid = str(meta.get("chunk_id", ""))
        batch_ids.append(cid)
        batch_texts.append(text)
        batch_metas.append(meta)

        if len(batch_ids) >= batch_size:
            embs = embeddings.embed_documents(batch_texts)
            coll.add(ids=batch_ids, embeddings=embs, documents=batch_texts, metadatas=batch_metas)
            written += len(batch_ids)
            batch_ids, batch_texts, batch_metas = [], [], []

    if batch_ids:
        embs = embeddings.embed_documents(batch_texts)
        coll.add(ids=batch_ids, embeddings=embs, documents=batch_texts, metadatas=batch_metas)
        written += len(batch_ids)

    info["phase6_chunks_written"] = written
    info["phase6_text_recover_failed"] = failed
    info["phase6_final_count"] = coll.count()
    info["phase6_full_dir"] = PHASE6_FULL_DIR
    info["phase6_full_collection"] = PHASE6_FULL_COLLECTION
    return info


def _merge_into_final_full(execute: bool, reset: bool, device: str) -> dict[str, Any]:
    """从 phase6 full Chroma 读取 + enterprise_docs → final full Chroma。"""
    # 读取 phase6 full
    phase6_dir = ROOT_DIR / PHASE6_FULL_DIR
    client = chromadb.PersistentClient(path=str(phase6_dir))
    try:
        pcoll = client.get_collection(PHASE6_FULL_COLLECTION)
    except Exception:
        return {"error": f"Phase6 full Chroma not found at {PHASE6_FULL_DIR}"}

    result = pcoll.get(include=["documents", "metadatas"])
    pchunks = []
    for i, (cid, doc, meta) in enumerate(zip(result["ids"], result["documents"] or [], result["metadatas"] or [])):
        pchunks.append({"chunk_id": cid, "page_content": doc or "", "metadata": dict(meta or {})})

    # 加载 enterprise_docs
    docs_path = ROOT_DIR / ENTERPRISE_DOCS_DIR
    echunks = []
    if docs_path.exists():
        docs = load_documents(str(docs_path))
        for chunk in split_documents(docs):
            meta = dict(chunk.metadata)
            stem = Path(meta.get("source", "unknown")).stem
            meta.setdefault("source_id", stem)
            meta.setdefault("source_url", "")
            meta.setdefault("section_path", stem)
            meta.setdefault("domain", "enterprise_project")
            meta.setdefault("normalized_id", stem)
            meta.setdefault("language", "zh")
            meta.setdefault("review_status", "approved")
            meta.setdefault("ingest_candidate", True)
            echunks.append({"chunk_id": meta.get("chunk_id", ""), "page_content": chunk.page_content, "metadata": meta})

    # 去重合并
    seen = set()
    merged = []
    for c in pchunks + echunks:
        cid = c["chunk_id"]
        if cid and cid in seen:
            continue
        seen.add(cid)
        merged.append(c)

    info = {
        "phase6_chunks": len(pchunks),
        "enterprise_chunks": len(echunks),
        "merged_total": len(merged),
    }

    if not execute:
        info["final_full_dir"] = FINAL_FULL_DIR
        info["final_full_collection"] = FINAL_FULL_COLLECTION
        info["final_planned_count"] = len(merged)
        return info

    final_dir = ROOT_DIR / FINAL_FULL_DIR
    if reset and final_dir.exists():
        shutil.rmtree(final_dir)
    final_dir.mkdir(parents=True, exist_ok=True)

    embeddings = get_embedding_model(device=device)
    fclient = chromadb.PersistentClient(path=str(final_dir))
    try:
        fclient.delete_collection(FINAL_FULL_COLLECTION)
    except Exception:
        pass
    fcoll = fclient.create_collection(name=FINAL_FULL_COLLECTION, metadata={"hnsw:space": "cosine"})

    batch_size = 50
    written = 0
    for i in range(0, len(merged), batch_size):
        batch = merged[i:i + batch_size]
        ids = [c["chunk_id"] for c in batch]
        texts = [c["page_content"] for c in batch]
        metas = [c["metadata"] for c in batch]
        embs = embeddings.embed_documents(texts)
        fcoll.add(ids=ids, embeddings=embs, documents=texts, metadatas=metas)
        written += len(batch)

    info["final_chunks_written"] = written
    info["final_count"] = fcoll.count()
    info["final_full_dir"] = FINAL_FULL_DIR
    info["final_full_collection"] = FINAL_FULL_COLLECTION
    return info


def main() -> None:
    load_dotenv()
    args = _parse_args()
    execute = bool(args.execute)
    dry_run = not execute
    now = datetime.now(DATETIME_UTC).isoformat()

    print(f"[信息] {'DRY-RUN' if dry_run else 'EXECUTE'} mode, limit={args.limit}")

    # Step 1: phase6 full
    print("[信息] 构建 phase6 full Chroma...")
    p6_info = _build_phase6_full_chroma(args.limit, args.device, execute, bool(args.reset_final))
    for k, v in p6_info.items():
        print(f"  {k}: {v}")

    # Step 2: merge into final full
    print("[信息] 合并为 final full Chroma...")
    merge_info = _merge_into_final_full(execute, bool(args.reset_final), args.device)
    for k, v in merge_info.items():
        print(f"  {k}: {v}")

    report = {
        "generated_at": now,
        "execute": execute,
        "dry_run": dry_run,
        "phase6_full": p6_info,
        "final_full": merge_info,
        "calls_llm": False,
        "calls_embedding": execute,
        "writes_chroma": execute,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
