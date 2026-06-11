from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from datetime import UTC as DATETIME_UTC
except ImportError:  # pragma: no cover - Python 3.10 compatibility.
    DATETIME_UTC = timezone.utc  # noqa: UP017


REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_DIR = REPO_ROOT / "data" / "knowledge_base" / "manifests"
NORMALIZED_MANIFEST_PATH = MANIFEST_DIR / "normalized_manifest.jsonl"
CHUNK_MANIFEST_PATH = MANIFEST_DIR / "chunk_manifest.jsonl"
DEFAULT_CHUNK_SIZE = 900
DEFAULT_OVERLAP = 100


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build Phase 6 chunk manifest without embedding or Chroma writes."
    )
    parser.add_argument("--chunk-size", type=int, default=DEFAULT_CHUNK_SIZE)
    parser.add_argument("--chunk-overlap", type=int, default=DEFAULT_OVERLAP)
    return parser.parse_args()


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            if line.strip():
                records.append(json.loads(line))
    return records


def _write_jsonl(records: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as file:
        for record in records:
            file.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _metadata_preview(doc_type: str, chunk_index: int, chunk_hash: str) -> str:
    preview = f"metadata-only preview: {doc_type} chunk {chunk_index}, sha256={chunk_hash[:12]}"
    return _sanitize_display_text(preview)


def _sanitize_display_text(text: str) -> str:
    replacements = {
        ".env": "[CONFIG_FILE]",
        "API key": "[SECRET_PLACEHOLDER]",
        "API keys": "[SECRET_PLACEHOLDER]",
        "API_KEY": "[SECRET_PLACEHOLDER]",
        "api_key": "[SECRET_PLACEHOLDER]",
        "Bearer": "[SECRET_PLACEHOLDER]",
    }
    sanitized = text
    for needle, replacement in replacements.items():
        sanitized = sanitized.replace(needle, replacement)
    return sanitized


def _split_long_text(text: str, size: int, overlap: int) -> list[str]:
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end == len(text):
            break
        start = max(end - overlap, start + 1)
    return chunks


def _paragraph_chunks(text: str, size: int, overlap: int) -> list[str]:
    paragraphs = [part.strip() for part in re.split(r"\n{2,}", text) if part.strip()]
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for paragraph in paragraphs:
        if len(paragraph) > size:
            if current:
                chunks.append("\n\n".join(current).strip())
                current = []
                current_len = 0
            chunks.extend(_split_long_text(paragraph, size=size, overlap=overlap))
            continue
        projected_len = current_len + len(paragraph) + (2 if current else 0)
        if current and projected_len > size:
            chunks.append("\n\n".join(current).strip())
            tail = chunks[-1][-overlap:].strip() if overlap else ""
            current = [tail, paragraph] if tail else [paragraph]
            current_len = sum(len(part) for part in current) + 2 * (len(current) - 1)
        else:
            current.append(paragraph)
            current_len = projected_len
    if current:
        chunks.append("\n\n".join(current).strip())
    return [chunk for chunk in chunks if chunk.strip()]


def _page_for_chunk(chunk: str) -> tuple[int | None, int | None]:
    markers = [int(value) for value in re.findall(r"\[page:(\d+)\]", chunk)]
    if not markers:
        return None, None
    return min(markers), max(markers)


def _chunk_strategy(doc_type: str) -> str:
    if doc_type in {"html", "markdown"}:
        return "heading_aware"
    if doc_type == "pdf":
        return "page_paragraph"
    if doc_type in {"json", "yaml"}:
        return "schema_key_aware"
    return "paragraph_aware"


def _section_path(doc_type: str, chunk: str, title: str) -> list[str]:
    headings = [
        line.lstrip("#").strip()
        for line in chunk.splitlines()
        if line.lstrip().startswith("#")
    ]
    if headings:
        return [_sanitize_display_text(heading) for heading in headings[:4]]
    return [title] if title else [doc_type]


def build_chunks(args: argparse.Namespace) -> list[dict[str, Any]]:
    normalized_records = [
        record
        for record in _load_jsonl(NORMALIZED_MANIFEST_PATH)
        if record.get("normalization_status") == "pass" and record.get("content_cache_alias")
    ]
    chunk_records: list[dict[str, Any]] = []
    seen_chunk_hashes: set[str] = set()

    for normalized in normalized_records:
        cache_path = REPO_ROOT / "data" / "knowledge_base" / str(normalized["content_cache_alias"])
        if not cache_path.exists():
            continue
        text = cache_path.read_text(encoding="utf-8", errors="ignore").strip()
        if not text:
            continue
        doc_type = str(normalized.get("doc_type") or "unknown")
        chunks = _paragraph_chunks(text, size=args.chunk_size, overlap=args.chunk_overlap)
        strategy = _chunk_strategy(doc_type)
        title = str(normalized.get("title") or "")
        emitted_index = 0
        for chunk in chunks:
            page_start, page_end = _page_for_chunk(chunk)
            chunk_hash = _sha256_text(chunk)
            if chunk_hash in seen_chunk_hashes:
                continue
            seen_chunk_hashes.add(chunk_hash)
            chunk_records.append(
                {
                    "chunk_id": f"chunk_{normalized['normalized_id']}_{emitted_index:04d}",
                    "normalized_id": normalized["normalized_id"],
                    "doc_id": normalized.get("doc_id"),
                    "source_id": normalized.get("source_id"),
                    "sample_id": normalized.get("sample_id"),
                    "doc_type": doc_type,
                    "domain": normalized.get("domain"),
                    "language": normalized.get("language"),
                    "title": title,
                    "section_path": _section_path(doc_type, chunk, title),
                    "source_url": normalized.get("source_url"),
                    "page_start": page_start,
                    "page_end": page_end,
                    "chunk_index": emitted_index,
                    "chunk_size": args.chunk_size,
                    "chunk_overlap": args.chunk_overlap,
                    "chunk_chars": len(chunk),
                    "chunk_sha256": chunk_hash,
                    "content_sha256": chunk_hash,
                    "content_preview": _metadata_preview(doc_type, emitted_index, chunk_hash),
                    "normalization_status": normalized.get("normalization_status"),
                    "filter_reason": normalized.get("filter_reason"),
                    "review_status": normalized.get("review_status"),
                    "ingest_candidate": bool(normalized.get("ingest_candidate")),
                    "metadata": {
                        "parser": normalized.get("parser"),
                        "normalizer": normalized.get("normalizer"),
                        "chunk_strategy": strategy,
                        "content_cache_alias": normalized.get("content_cache_alias"),
                        "link_count": normalized.get("link_count"),
                        "code_block_count": normalized.get("code_block_count"),
                    },
                    "embedding_written": False,
                    "chroma_written": False,
                    "created_at": datetime.now(DATETIME_UTC).isoformat(),
                }
            )
            emitted_index += 1
    return chunk_records


def main() -> None:
    args = parse_args()
    records = build_chunks(args)
    _write_jsonl(records, CHUNK_MANIFEST_PATH)
    summary = {
        "chunk_record_count": len(records),
        "manifest_path": str(CHUNK_MANIFEST_PATH.relative_to(REPO_ROOT)),
        "writes_chroma": False,
        "calls_embedding": False,
        "calls_llm": False,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))  # noqa: T201


if __name__ == "__main__":
    main()
