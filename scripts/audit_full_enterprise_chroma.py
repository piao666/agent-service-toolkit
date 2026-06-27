"""审计 full enterprise Chroma corpus 的结构完整性。"""
import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]

try:
    from datetime import UTC as DATETIME_UTC
except ImportError:
    DATETIME_UTC = timezone.utc

import chromadb

DEFAULT_PERSIST = "./chroma_enterprise_full"
DEFAULT_COLLECTION = "enterprise_knowledge_base_full"
DEFAULT_OUTPUT = ROOT_DIR / "data/knowledge_base/evaluation/full_chroma_audit.json"
DEFAULT_SAMPLES = ROOT_DIR / "data/knowledge_base/evaluation/full_chroma_samples.json"
DEMO_PERSIST = "./chroma_enterprise_final"
DEMO_COLLECTION = "enterprise_knowledge_base"


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--persist-dir", default=DEFAULT_PERSIST)
    p.add_argument("--collection-name", default=DEFAULT_COLLECTION)
    p.add_argument("--output", default=str(DEFAULT_OUTPUT))
    p.add_argument("--samples-output", default=str(DEFAULT_SAMPLES))
    return p.parse_args()


def _audit(persist: str, collection: str) -> dict[str, Any]:
    resolved = ROOT_DIR / persist
    if not resolved.exists():
        return {"error": f"Chroma dir not found: {resolved}"}

    client = chromadb.PersistentClient(path=str(resolved))
    try:
        coll = client.get_collection(collection)
    except Exception as exc:
        return {"error": f"Collection not found: {exc}"}

    count = coll.count()
    result = coll.get(include=["documents", "metadatas"])
    ids = result.get("ids") or []
    docs = result.get("documents") or []
    metas = result.get("metadatas") or []

    # 基础统计
    sid_counter = Counter()
    doc_type_counter = Counter()
    title_counter = Counter()
    chunk_lengths = []
    unknown_source = 0
    empty_text = 0
    id_counts = Counter(ids)
    dup_ids = {k: v for k, v in id_counts.items() if v > 1}

    all_keys = set()
    per_source_lens: dict[str, list[int]] = {}

    samples = []
    for i, (cid, doc, meta) in enumerate(zip(ids, docs, metas)):
        sid = meta.get("source_id", "")
        if not sid or sid == "unknown":
            unknown_source += 1
        sid_counter[sid] += 1
        dt = meta.get("doc_type", "")
        if dt:
            doc_type_counter[dt] += 1
        title = meta.get("title", "")
        if title:
            title_counter[title] += 1
        text = doc or ""
        if not text.strip():
            empty_text += 1
        cl = len(text)
        chunk_lengths.append(cl)
        if sid not in per_source_lens:
            per_source_lens[sid] = []
        per_source_lens[sid].append(cl)
        all_keys.update(meta.keys())
        if len(samples) < 30:
            samples.append({
                "source_id": sid,
                "title": title,
                "doc_type": dt,
                "chunk_id": cid,
                "chunk_index": meta.get("chunk_index"),
                "text_len": cl,
                "text_preview": text[:200],
                "metadata": {str(k): str(v)[:100] for k, v in meta.items()},
            })

    return {
        "collection_count": count,
        "unknown_source_count": unknown_source,
        "duplicate_chunk_id_count": len(dup_ids),
        "duplicate_chunk_ids": list(dup_ids.keys())[:10] if dup_ids else [],
        "empty_text_count": empty_text,
        "chunk_length": {
            "min": min(chunk_lengths) if chunk_lengths else 0,
            "max": max(chunk_lengths) if chunk_lengths else 0,
            "avg": round(sum(chunk_lengths) / len(chunk_lengths), 1) if chunk_lengths else 0,
            "total_chars": sum(chunk_lengths),
        },
        "source_id_distribution": dict(sid_counter.most_common()),
        "doc_type_distribution": dict(doc_type_counter.most_common()),
        "title_distribution_top30": dict(title_counter.most_common(30)),
        "per_source_chunk_length_stats": {
            sid: {
                "count": len(lens), "min": min(lens), "max": max(lens),
                "avg": round(sum(lens) / len(lens), 1),
            }
            for sid, lens in per_source_lens.items()
        },
        "metadata_key_coverage": sorted(all_keys),
        "samples": samples,
    }


def _compare_with_demo(full_info: dict[str, Any]) -> dict[str, Any]:
    """对比 full corpus 与 demo corpus 的 source 级覆盖。"""
    demo_resolved = ROOT_DIR / DEMO_PERSIST
    if not demo_resolved.exists():
        return {"error": "Demo Chroma not found"}

    client = chromadb.PersistentClient(path=str(demo_resolved))
    try:
        dcoll = client.get_collection(DEMO_COLLECTION)
    except Exception:
        return {"error": "Demo collection not found"}

    dresult = dcoll.get(include=["metadatas"])
    dmetas = dresult.get("metadatas") or []
    demo_sids = Counter(m.get("source_id", "") for m in dmetas)

    full_sids = full_info.get("source_id_distribution", {})
    all_sids = sorted(set(list(demo_sids.keys()) + list(full_sids.keys())))

    comparison = {}
    for sid in all_sids:
        d_count = demo_sids.get(sid, 0)
        f_count = full_sids.get(sid, 0)
        comparison[sid] = {
            "demo_chunks": d_count,
            "full_chunks": f_count,
            "delta": f_count - d_count,
        }

    return {
        "demo_collection_count": dcoll.count(),
        "full_collection_count": full_info.get("collection_count", 0),
        "per_source_comparison": comparison,
    }


def main() -> None:
    args = _parse_args()
    now = datetime.now(DATETIME_UTC).isoformat()

    print(f"[信息] 审计 {args.persist_dir}/{args.collection_name} ...")
    audit = _audit(args.persist_dir, args.collection_name)
    comparison = _compare_with_demo(audit)

    # Write samples
    Path(args.samples_output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.samples_output).write_text(
        json.dumps(audit.get("samples", []), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    # Write full audit
    report = {
        "generated_at": now,
        "persist_dir": args.persist_dir,
        "collection_name": args.collection_name,
        "audit": {k: v for k, v in audit.items() if k != "samples"},
        "demo_vs_full_comparison": comparison,
        "calls_llm": False,
        "writes_chroma": False,
    }
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"  count={audit['collection_count']}")
    print(f"  unknown_source={audit['unknown_source_count']}")
    print(f"  duplicate_ids={audit['duplicate_chunk_id_count']}")
    print(f"  empty_text={audit['empty_text_count']}")
    print(f"  chunk_len avg={audit['chunk_length']['avg']}")
    print(f"  sources={len(audit['source_id_distribution'])}")
    print(f"  doc_types={dict(audit['doc_type_distribution'])}")
    print(f"\n[信息] 输出: {args.output}")
    print(f"[信息] 样本: {args.samples_output}")


if __name__ == "__main__":
    main()
