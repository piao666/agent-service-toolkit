#!/usr/bin/env python3
"""Phase 6F-1: Build metadata index from chunk_manifest.jsonl.

不调用 LLM，不写 Chroma，不保存完整 chunk 正文。
输出 phase6f_metadata_index.json + phase6f_metadata_index_summary.json
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "data" / "knowledge_base" / "manifests" / "chunk_manifest.jsonl"
EVAL = ROOT / "data" / "knowledge_base" / "evaluation"
OUT_INDEX = EVAL / "phase6f_metadata_index.json"
OUT_SUMMARY = EVAL / "phase6f_metadata_index_summary.json"

METADATA_FIELDS = [
    "source_id", "doc_type", "domain", "language", "title",
    "section_path", "chunk_id", "normalized_id", "source_url",
    "review_status", "ingest_candidate",
]
PREVIEW_LEN = 200


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def main():
    chunks = load_jsonl(MANIFEST_PATH)
    print(f"Loaded {len(chunks)} chunks from {MANIFEST_PATH}")

    # ── Build per-source metadata index ──
    source_index: dict[str, dict[str, Any]] = {}
    missing_counts: Counter = Counter()
    doc_types: set[str] = set()
    domains: set[str] = set()
    chunk_count = 0

    for c in chunks:
        sid = c.get("source_id", "")
        for f in ["source_id", "doc_type", "domain", "language", "title", "section_path", "chunk_id"]:
            if not c.get(f):
                missing_counts[f] += 1
        if not sid:
            continue

        if sid not in source_index:
            source_index[sid] = {
                "source_id": sid,
                "doc_types": set(),
                "domains": set(),
                "languages": set(),
                "titles": set(),
                "section_paths": set(),
                "source_urls": set(),
                "chunk_ids": [],
                "normalized_ids": set(),
                "review_statuses": set(),
                "sample_preview": "",
                "chunk_count": 0,
            }

        entry = source_index[sid]
        entry["chunk_count"] += 1
        chunk_count += 1

        field_map = {
            "doc_type": "doc_types", "domain": "domains", "language": "languages",
            "title": "titles", "source_url": "source_urls",
            "review_status": "review_statuses", "normalized_id": "normalized_ids",
        }
        for f, ek in field_map.items():
            val = c.get(f, "")
            if val:
                entry[ek].add(val)

        sp = c.get("section_path", "")
        if isinstance(sp, list):
            for s in sp:
                if s:
                    entry["section_paths"].add(s)
        elif sp:
            entry["section_paths"].add(sp)

        cid = c.get("chunk_id", "")
        if cid:
            entry["chunk_ids"].append(cid)

        if not entry["sample_preview"]:
            entry["sample_preview"] = (c.get("content_preview") or c.get("text") or "")[:PREVIEW_LEN]

    # Convert sets to sorted lists
    result_index = []
    for sid, entry in sorted(source_index.items()):
        result_index.append({
            "source_id": entry["source_id"],
            "doc_types": sorted(entry["doc_types"]),
            "domains": sorted(entry["domains"]),
            "languages": sorted(entry["languages"]),
            "titles": sorted(entry["titles"]),
            "section_paths": sorted(entry["section_paths"]),
            "source_urls": sorted(entry["source_urls"]),
            "chunk_ids": entry["chunk_ids"][:20],  # keep first 20
            "normalized_ids": sorted(entry["normalized_ids"]),
            "review_statuses": sorted(entry["review_statuses"]),
            "sample_preview": entry["sample_preview"],
            "chunk_count": entry["chunk_count"],
        })

    # ── Write index ──
    with OUT_INDEX.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(result_index, f, ensure_ascii=False, indent=2)

    # ── Build summary ──
    summary = {
        "total_chunks_scanned": len(chunks),
        "total_chunks_indexed": chunk_count,
        "source_id_count": len(source_index),
        "doc_type_count": len({d for e in source_index.values() for d in e["doc_types"]}),
        "domain_count": len({d for e in source_index.values() for d in e["domains"]}),
        "missing_fields": dict(missing_counts),
        "indexed_fields": METADATA_FIELDS,
        "metadata_index_ready": len(source_index) > 0,
        "calls_llm": False,
        "writes_chroma": False,
        "source_summary": {
            sid: {"chunk_count": e["chunk_count"], "doc_types": sorted(e["doc_types"])}
            for sid, e in list(source_index.items())[:20]
        },
    }

    with OUT_SUMMARY.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"  Sources indexed:   {len(source_index)}")
    print(f"  Chunks indexed:    {chunk_count}")
    print(f"  Doc types:         {summary['doc_type_count']}")
    print(f"  Domains:           {summary['domain_count']}")
    print(f"  Missing fields:    {dict(missing_counts)}")
    print(f"  Ready:             {summary['metadata_index_ready']}")
    print(f"  Output:            {OUT_INDEX}")
    print(f"  Summary:           {OUT_SUMMARY}")


if __name__ == "__main__":
    main()
