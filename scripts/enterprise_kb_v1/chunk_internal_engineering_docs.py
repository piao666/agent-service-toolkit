#!/usr/bin/env python3
"""Phase 4F: Build internal engineering corpus — normalize + chunk + audit.

本地执行，不依赖 GPU。读取 source_registry + 源文件，输出：
- data/enterprise_kb_v1/internal_engineering_corpus/v1/{source_id}/
    - normalized.md, text_metadata.json, audit.json
- data/enterprise_kb_v1/chunks/internal_engineering_docs/all_chunks.jsonl (聚合)
- phase4fh_internal_chunk_manifest.json
"""

import hashlib
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

# ── 路径常量 ──────────────────────────────────────────────────────────────
PROJECT = Path(__file__).resolve().parent.parent.parent  # agent-service-toolkit-clean/
DATA = PROJECT / "data" / "enterprise_kb_v1"
REGISTRY = DATA / "source_registry" / "internal_engineering_sources.yaml"
CORPUS_DIR = DATA / "internal_engineering_corpus" / "v1"
CHUNKS_DIR = DATA / "chunks" / "internal_engineering_docs"
MANIFEST_DIR = DATA / "manifests"

# ── Chunking 参数 ─────────────────────────────────────────────────────────
CHUNK_SIZE_MIN = 800
CHUNK_SIZE_MAX = 1200
OVERLAP = 200


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9_-]", "_", text.lower().strip())[:64]


def _hash_id(text: str, prefix: str = "") -> str:
    h = hashlib.md5(text.encode(), usedforsecurity=False).hexdigest()[:12]
    return f"{prefix}_{h}" if prefix else h


def _heading_path(heading_stack: list[str]) -> str:
    return " > ".join(h for h in heading_stack if h)


def normalize_source(source: dict) -> dict | None:
    """读源文件 → 规范化 → 输出 normalized.md + metadata.json + audit.json。"""
    sid = source["source_id"]
    local_path = PROJECT / source["local_path"]

    audit: dict = {"source_id": sid, "warnings": [], "blockers": []}

    if not local_path.exists():
        audit["blockers"].append(f"file not found: {local_path}")
        return None

    text = local_path.read_text(encoding="utf-8")
    char_count = len(text)

    # 提取标题
    headings = re.findall(r"^#{1,6}\s+(.+)$", text, re.MULTILINE)
    heading_count = len(headings)

    # 提取代码块
    code_blocks = re.findall(r"```[\s\S]*?```", text)
    code_block_count = len(code_blocks)

    # 分段（按双换行）
    sections = re.split(r"\n\n+", text)
    section_count = len(sections)

    # Audit checks
    if char_count < 300:
        audit["warnings"].append(f"short doc: {char_count} chars")
    if heading_count == 0 and char_count < 300:
        audit["warnings"].append("no headings (may be acceptable for short notes)")
    elif heading_count == 0:
        audit["blockers"].append("no headings in substantial document")

    out_dir = CORPUS_DIR / sid
    out_dir.mkdir(parents=True, exist_ok=True)

    # 写 normalized.md（原始内容，不做变换）
    (out_dir / "normalized.md").write_text(text, encoding="utf-8")

    # 写 metadata
    metadata = {
        "source_id": sid,
        "source_type": source.get("source_type", ""),
        "domain": source.get("domain", ""),
        "title": source.get("title", ""),
        "local_path": source.get("local_path", ""),
        "corpus": source.get("corpus", "internal_engineering_docs"),
        "char_count": char_count,
        "heading_count": heading_count,
        "code_block_count": code_block_count,
        "section_count": section_count,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "audit_status": "blockers" if audit["blockers"] else ("warnings" if audit["warnings"] else "ok"),
    }
    (out_dir / "text_metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # 写 audit
    audit["metadata_summary"] = {
        k: metadata[k] for k in ["char_count", "heading_count", "code_block_count", "section_count"]
    }
    (out_dir / "audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    return metadata


def chunk_source(source: dict) -> list[dict]:
    """对单个 source 做 heading-aware chunking。"""
    sid = source["source_id"]
    local_path = PROJECT / source["local_path"]
    if not local_path.exists():
        return []

    text = local_path.read_text(encoding="utf-8")
    domain = source.get("domain", "")
    title = source.get("title", "")
    local_path_str = source.get("local_path", "")

    # Markdown heading split
    chunks_out: list[dict] = []
    heading_stack: list[tuple[str, int]] = []  # (heading_text, level)
    current_section_lines: list[str] = []
    offset = 0

    for line in text.split("\n"):
        m = re.match(r"^(#{1,6})\s+(.+)$", line)
        if m:
            # Flush current section
            if current_section_lines:
                section_text = "\n".join(current_section_lines)
                _split_section_into_chunks(
                    section_text, offset, chunks_out, sid, domain, title,
                    local_path_str, _heading_path([h for h, _ in heading_stack]),
                )
                offset += len(section_text) + 1
                current_section_lines = []

            level = len(m.group(1))
            h_text = m.group(2).strip()
            # Pop headings of same or higher level
            while heading_stack and heading_stack[-1][1] >= level:
                heading_stack.pop()
            heading_stack.append((h_text, level))
            continue

        current_section_lines.append(line)

    # Flush remaining
    if current_section_lines:
        section_text = "\n".join(current_section_lines)
        _split_section_into_chunks(
            section_text, offset, chunks_out, sid, domain, title,
            local_path_str, _heading_path([h for h, _ in heading_stack]),
        )

    return chunks_out


def _split_section_into_chunks(
    text: str, base_offset: int, out: list, sid: str, domain: str,
    title: str, local_path: str, heading_path: str,
) -> None:
    """将单节文本切分为 chunk。"""
    if not text.strip():
        return

    text_len = len(text)
    if text_len <= CHUNK_SIZE_MAX:
        chunk_text = text
        out.append(_make_chunk(chunk_text, base_offset, sid, domain, title, local_path, heading_path))
        return

    # 超长节：按 paragraph 边界切分
    paragraphs = re.split(r"\n\n+", text)
    current = ""
    current_start = base_offset
    pos = base_offset

    for para in paragraphs:
        if len(current) + len(para) + 2 <= CHUNK_SIZE_MAX:
            current += ("\n\n" + para) if current else para
        else:
            if current.strip():
                out.append(_make_chunk(current, current_start, sid, domain, title, local_path, heading_path))
            # 重叠：从前一个 chunk 的倒数第 OVERLAP 字符处开始
            overlap_start = max(0, len(current) - OVERLAP)
            current = current[overlap_start:] + "\n\n" + para
            current_start = pos - len(current.encode()) if overlap_start > 0 else pos
        pos += len(para.encode("utf-8")) + 2

    if current.strip():
        out.append(_make_chunk(current, current_start, sid, domain, title, local_path, heading_path))


def _make_chunk(
    text: str, offset: int, sid: str, domain: str, title: str,
    local_path: str, heading_path: str,
) -> dict:
    chunk_id = _hash_id(f"{sid}:{offset}")
    char_count = len(text)
    contains_code = "```" in text
    return {
        "chunk_id": chunk_id,
        "source_id": sid,
        "corpus": "internal_engineering_docs",
        "source_type": "internal_engineering_docs",
        "domain": domain,
        "title": title,
        "local_path": local_path,
        "heading_path": heading_path,
        "text": text,
        "char_count": char_count,
        "start_offset": offset,
        "end_offset": offset + char_count,
        "contains_code": contains_code,
        "answer_scope": "project_engineering_reference",
        "version": "v1",
    }


def main() -> None:
    print("Phase 4F: Build Internal Engineering Corpus")
    print(f"Registry: {REGISTRY}")

    if not REGISTRY.exists():
        print("FATAL: source_registry not found"); sys.exit(1)

    with open(REGISTRY, encoding="utf-8") as f:
        registry = yaml.safe_load(f)

    sources = registry.get("sources", [])
    print(f"Sources in registry: {len(sources)}")

    # Step 1: Normalize
    norm_ok = 0
    for src in sources:
        sid = src.get("source_id", "")
        if not sid:
            continue
        meta = normalize_source(src)
        if meta:
            print(f"  norm OK: {sid} ({meta['char_count']} chars, {meta['heading_count']} headings)")
            norm_ok += 1
        else:
            print(f"  norm SKIP: {sid} (blockers)")

    print(f"\nNormalized: {norm_ok}/{len(sources)} sources")

    # Step 2: Chunk
    CHUNKS_DIR.mkdir(parents=True, exist_ok=True)
    all_chunks: list[dict] = []
    source_chunk_counts: dict[str, int] = {}

    for src in sources:
        sid = src.get("source_id", "")
        if not sid:
            continue
        chunks = chunk_source(src)
        all_chunks.extend(chunks)
        source_chunk_counts[sid] = len(chunks)
        print(f"  chunk: {sid} → {len(chunks)} chunks")

    # 去重
    seen_ids: set[str] = set()
    unique_chunks: list[dict] = []
    for c in all_chunks:
        if c["chunk_id"] not in seen_ids:
            seen_ids.add(c["chunk_id"])
            unique_chunks.append(c)

    dupes = len(all_chunks) - len(unique_chunks)
    print(f"\nTotal chunks: {len(all_chunks)} ({len(unique_chunks)} unique, {dupes} dupes)")

    # 输出聚合 JSONL
    chunks_path = CHUNKS_DIR / "all_chunks.jsonl"
    with open(chunks_path, "w", encoding="utf-8") as f:
        for c in unique_chunks:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")

    # 输出 manifest
    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    manifest = {
        "phase": "4F",
        "corpus": "internal_engineering_docs",
        "chunk_strategy": {"chunk_size_min": CHUNK_SIZE_MIN, "chunk_size_max": CHUNK_SIZE_MAX, "overlap": OVERLAP},
        "indexed_source_count": norm_ok,
        "indexed_chunk_count": len(unique_chunks),
        "failed_chunks": 0,
        "duplicate_chunks_removed": dupes,
        "per_source_counts": source_chunk_counts,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    manifest_path = MANIFEST_DIR / "phase4fh_internal_chunk_manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    print(f"\nChunks → {chunks_path}")
    print(f"Manifest → {manifest_path}")
    print("DONE: Phase 4F corpus build")


if __name__ == "__main__":
    main()
