"""构建最终统一企业知识库 Chroma 索引。

合并来源：
  1. chroma_enterprise_phase6 / enterprise_ai_learning_kb_reviewed（技术课程资料）
  2. data/enterprise_docs/*.md（项目说明文档）

输出：
  chroma_enterprise_final / enterprise_knowledge_base

用法：
  python scripts/build_final_enterprise_chroma.py              # dry-run
  python scripts/build_final_enterprise_chroma.py --dry-run    # 显式 dry-run
  python scripts/build_final_enterprise_chroma.py --execute --reset-final  # 实际写入

不调用 LLM，不提交 Chroma 数据库目录。
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

# 常量
PHASE6_PERSIST_DIR = "chroma_enterprise_phase6"
PHASE6_COLLECTION = "enterprise_ai_learning_kb_reviewed"
ENTERPRISE_DOCS_DIR = "data/enterprise_docs"
FINAL_PERSIST_DIR = "chroma_enterprise_final"
FINAL_COLLECTION = "enterprise_knowledge_base"

MANIFEST_DIR = ROOT_DIR / "data" / "knowledge_base" / "manifests"
AUDIT_OUTPUT_PATH = (
    ROOT_DIR / "data" / "knowledge_base" / "evaluation" / "final_chroma_index_audit.json"
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="构建最终统一企业知识库 Chroma 索引。"
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", default=True,
                      help="仅计划不写入 (默认)")
    mode.add_argument("--execute", action="store_true",
                      help="实际写入 Chroma")
    parser.add_argument("--reset-final", action="store_true",
                        help="写入前清空 final 目录 (需配合 --execute)")
    parser.add_argument("--phase6-dir", default=PHASE6_PERSIST_DIR)
    parser.add_argument("--phase6-collection", default=PHASE6_COLLECTION)
    parser.add_argument("--docs-dir", default=ENTERPRISE_DOCS_DIR)
    parser.add_argument("--final-dir", default=FINAL_PERSIST_DIR)
    parser.add_argument("--final-collection", default=FINAL_COLLECTION)
    parser.add_argument("--model-path", default=None)
    return parser.parse_args()


# ═══════════════════════════════════════════════════════════════
# Phase6 数据读取
# ═══════════════════════════════════════════════════════════════

def _read_phase6_chunks(persist_dir: str, collection_name: str) -> list[dict[str, Any]]:
    """从 phase6 Chroma 读取全部 chunk (documents + metadatas)。"""
    client = chromadb.PersistentClient(path=str(ROOT_DIR / persist_dir))
    try:
        coll = client.get_collection(collection_name)
    except Exception as exc:
        print(f"[错误] 无法读取 phase6 collection: {exc}", file=sys.stderr)
        return []

    count = coll.count()
    if count == 0:
        print("[信息] phase6 collection 为空。")
        return []

    result = coll.get(include=["documents", "metadatas"])
    ids = result.get("ids") or []
    documents = result.get("documents") or []
    metadatas = result.get("metadatas") or []

    chunks: list[dict[str, Any]] = []
    for i, (cid, doc, meta) in enumerate(zip(ids, documents, metadatas)):
        chunks.append({
            "chunk_id": cid,
            "page_content": doc or "",
            "metadata": dict(meta or {}),
        })
    print(f"[信息] 从 phase6 读取 {len(chunks)} 条 chunks。")
    return chunks


# ═══════════════════════════════════════════════════════════════
# Enterprise docs 加载与分块
# ═══════════════════════════════════════════════════════════════

def _load_enterprise_docs_chunks(docs_dir: str) -> list[dict[str, Any]]:
    """加载 data/enterprise_docs 并分块，返回与 phase6 兼容的结构。"""
    docs_path = ROOT_DIR / docs_dir
    if not docs_path.exists():
        print(f"[信息] enterprise_docs 目录不存在: {docs_path}")
        return []

    documents = load_documents(str(docs_path))
    if not documents:
        print("[信息] enterprise_docs 中无文档。")
        return []

    chunks = split_documents(documents)
    result: list[dict[str, Any]] = []
    for chunk in chunks:
        meta = dict(chunk.metadata)
        # 补充 phase6 兼容字段
        source = meta.get("source", "unknown")
        # 从文件路径派生 source_id
        stem = Path(source).stem if source != "unknown" else "unknown"
        meta.setdefault("source_id", stem)
        meta.setdefault("source_url", "")
        meta.setdefault("section_path", stem)
        meta.setdefault("domain", "enterprise_project")
        meta.setdefault("normalized_id", stem)
        meta.setdefault("language", "zh")
        meta.setdefault("review_status", "approved")
        meta.setdefault("ingest_candidate", True)
        result.append({
            "chunk_id": meta.get("chunk_id", ""),
            "page_content": chunk.page_content,
            "metadata": meta,
        })
    print(f"[信息] 从 enterprise_docs 加载 {len(documents)} 篇文档，分 {len(result)} 个 chunks。")
    return result


# ═══════════════════════════════════════════════════════════════
# 合并与去重
# ═══════════════════════════════════════════════════════════════

def _merge_and_dedup(
    phase6_chunks: list[dict[str, Any]],
    enterprise_chunks: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """合并两组 chunks，按 chunk_id 去重。"""
    seen_ids: set[str] = set()
    merged: list[dict[str, Any]] = []
    phase6_deduped = 0
    enterprise_deduped = 0
    enterprise_added = 0

    for chunk in phase6_chunks:
        cid = chunk["chunk_id"]
        if cid and cid in seen_ids:
            phase6_deduped += 1
            continue
        seen_ids.add(cid)
        merged.append(chunk)

    for chunk in enterprise_chunks:
        cid = chunk["chunk_id"]
        if cid and cid in seen_ids:
            enterprise_deduped += 1
            continue
        seen_ids.add(cid)
        merged.append(chunk)
        enterprise_added += 1

    stats = {
        "phase6_total": len(phase6_chunks),
        "enterprise_total": len(enterprise_chunks),
        "merged_total": len(merged),
        "phase6_deduped": phase6_deduped,
        "enterprise_deduped": enterprise_deduped,
        "enterprise_added": enterprise_added,
    }
    print(f"[信息] 合并后共 {len(merged)} 条 chunks "
          f"(phase6={len(phase6_chunks)}, enterprise={len(enterprise_chunks)}, "
          f"enterprise 新增={enterprise_added})。")
    return merged, stats


# ═══════════════════════════════════════════════════════════════
# 写入 Chroma
# ═══════════════════════════════════════════════════════════════

def _write_final_chroma(
    chunks: list[dict[str, Any]],
    final_dir: str,
    final_collection: str,
    reset: bool,
    model_path: str | None = None,
) -> dict[str, Any]:
    """将合并后的 chunks 写入最终 Chroma 库。"""
    resolved_dir = ROOT_DIR / final_dir
    if reset and resolved_dir.exists():
        shutil.rmtree(resolved_dir)
        print(f"[信息] 已清空 {final_dir}。")

    resolved_dir.mkdir(parents=True, exist_ok=True)
    embedding_model = get_embedding_model(model_path=model_path)

    client = chromadb.PersistentClient(path=str(resolved_dir))
    try:
        client.delete_collection(final_collection)
    except Exception:
        pass
    coll = client.create_collection(
        name=final_collection,
        metadata={"hnsw:space": "cosine"},
    )

    # 批量写入（chromadb 原生 API 避免 langchain_chroma 包装）
    batch_size = 50
    written = 0
    for i in range(0, len(chunks), batch_size):
        batch = chunks[i:i + batch_size]
        ids = [c["chunk_id"] for c in batch]
        texts = [c["page_content"] for c in batch]
        metas = [c["metadata"] for c in batch]
        # 生成 embedding
        embeddings = embedding_model.embed_documents(texts)
        coll.add(ids=ids, embeddings=embeddings, documents=texts, metadatas=metas)
        written += len(batch)

    return {
        "final_dir": final_dir,
        "final_collection": final_collection,
        "chunks_written": written,
        "final_count": coll.count(),
    }


# ═══════════════════════════════════════════════════════════════
# source_id 分布分析
# ═══════════════════════════════════════════════════════════════

def _source_id_distribution(chunks: list[dict[str, Any]]) -> dict[str, int]:
    counter: Counter = Counter()
    for chunk in chunks:
        sid = (
            chunk["metadata"].get("source_id")
            or chunk["metadata"].get("source")
            or "unknown"
        )
        counter[sid] += 1
    return dict(counter.most_common())


def _key_doc_coverage(chunks: list[dict[str, Any]]) -> dict[str, bool]:
    sids = set()
    for chunk in chunks:
        sid = (
            chunk["metadata"].get("source_id")
            or chunk["metadata"].get("source")
            or ""
        )
        sids.add(sid)
    return {
        "fastapi_docs": "fastapi_docs" in sids,
        "enterprise_rag_pipeline": "enterprise_rag_pipeline" in sids,
        "enterprise_agent_overview": "enterprise_agent_overview" in sids,
    }


# ═══════════════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════════════

def main() -> None:
    load_dotenv()
    args = _parse_args()
    execute = bool(args.execute)
    dry_run = not execute

    now = datetime.now(DATETIME_UTC).isoformat()

    # 读取 phase6
    phase6_chunks = _read_phase6_chunks(args.phase6_dir, args.phase6_collection)

    # 加载 enterprise docs
    enterprise_chunks = _load_enterprise_docs_chunks(args.docs_dir)

    # 合并去重
    merged, merge_stats = _merge_and_dedup(phase6_chunks, enterprise_chunks)

    # source_id 分布
    sid_dist = _source_id_distribution(merged)
    key_coverage = _key_doc_coverage(merged)

    # 构建报告
    report: dict[str, Any] = {
        "generated_at": now,
        "execute": execute,
        "dry_run": dry_run,
        "sources": {
            "phase6": {
                "persist_dir": args.phase6_dir,
                "collection": args.phase6_collection,
                "chunk_count": len(phase6_chunks),
            },
            "enterprise_docs": {
                "docs_dir": args.docs_dir,
                "chunk_count": len(enterprise_chunks),
            },
        },
        "merge_stats": merge_stats,
        "final": {
            "persist_dir": args.final_dir,
            "collection": args.final_collection,
            "planned_chunk_count": len(merged),
            "source_id_distribution_top15": dict(list(sid_dist.items())[:15]),
            "unique_source_count": len(sid_dist),
            "key_document_coverage": key_coverage,
        },
        "calls_llm": False,
        "calls_embedding": execute,
        "writes_chroma": execute,
        "reset_final": bool(args.reset_final) if execute else False,
    }

    # 执行写入
    if execute and merged:
        if not args.reset_final:
            print("[警告] 使用 --reset-final 以清空目标目录后重新构建。", file=sys.stderr)
            print("[警告] 如不清空，可能会与已有数据冲突。", file=sys.stderr)

        write_result = _write_final_chroma(
            merged, args.final_dir, args.final_collection,
            reset=bool(args.reset_final),
            model_path=args.model_path,
        )
        report["final"].update(write_result)

        # 写入 audit JSON
        AUDIT_OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        AUDIT_OUTPUT_PATH.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"[信息] 审计报告已写入: {AUDIT_OUTPUT_PATH}")
    elif execute:
        print("[错误] 没有可写入的 chunks。", file=sys.stderr)

    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
