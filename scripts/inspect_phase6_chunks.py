from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any

try:
    from datetime import UTC as DATETIME_UTC
except ImportError:  # pragma: no cover - Python 3.10 compatibility.
    DATETIME_UTC = timezone.utc  # noqa: UP017


REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_DIR = REPO_ROOT / "data" / "knowledge_base" / "manifests"
CHUNK_MANIFEST_PATH = MANIFEST_DIR / "chunk_manifest.jsonl"
QUALITY_REPORT_PATH = MANIFEST_DIR / "chunk_quality_report.json"
CHUNKING_DOC_PATH = REPO_ROOT / "docs" / "enterprise_rag_backend" / "CHUNKING_VALIDATION.md"
REQUIRED_METADATA_FIELDS = ("source_id", "normalized_id", "doc_type", "title")
PREVIEW_MAX_CHARS = 200
LONG_CHUNK_THRESHOLD = 1400


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Inspect Phase 6 chunk manifest quality.")
    parser.add_argument("--chunk-manifest", type=Path, default=CHUNK_MANIFEST_PATH)
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


def _counter(records: list[dict[str, Any]], key: str) -> dict[str, int]:
    return dict(Counter(str(record.get(key) or "unknown") for record in records))


def _duplicate_count(values: list[str]) -> int:
    counts = Counter(values)
    return sum(count - 1 for count in counts.values() if count > 1)


def inspect_chunks(records: list[dict[str, Any]]) -> dict[str, Any]:
    chunk_chars = [int(record.get("chunk_chars") or 0) for record in records]
    chunk_hashes = [str(record.get("chunk_sha256") or "") for record in records]
    empty_chunk_count = sum(1 for value in chunk_chars if value <= 0)
    missing_metadata_count = sum(
        1
        for record in records
        if any(not record.get(field) for field in REQUIRED_METADATA_FIELDS)
    )
    preview_lengths = [len(str(record.get("content_preview") or "")) for record in records]
    too_long_count = sum(1 for value in chunk_chars if value > LONG_CHUNK_THRESHOLD)
    preview_too_long_count = sum(1 for value in preview_lengths if value > PREVIEW_MAX_CHARS)
    duplicate_chunk_hash_count = _duplicate_count(
        [chunk_hash for chunk_hash in chunk_hashes if chunk_hash]
    )
    return {
        "generated_at": datetime.now(DATETIME_UTC).isoformat(),
        "chunk_total": len(records),
        "by_doc_type": _counter(records, "doc_type"),
        "by_source_id": _counter(records, "source_id"),
        "by_domain": _counter(records, "domain"),
        "chunk_chars_min": min(chunk_chars) if chunk_chars else 0,
        "chunk_chars_avg": round(mean(chunk_chars), 2) if chunk_chars else 0,
        "chunk_chars_max": max(chunk_chars) if chunk_chars else 0,
        "empty_chunk_count": empty_chunk_count,
        "missing_metadata_count": missing_metadata_count,
        "duplicate_chunk_hash_count": duplicate_chunk_hash_count,
        "too_long_chunk_count": too_long_count,
        "preview_max_chars": max(preview_lengths) if preview_lengths else 0,
        "preview_too_long_count": preview_too_long_count,
        "quality_pass": (
            empty_chunk_count == 0
            and missing_metadata_count == 0
            and preview_too_long_count == 0
        ),
        "writes_chroma": False,
        "calls_embedding": False,
        "calls_llm": False,
    }


def _write_report(report: dict[str, Any], path: Path = QUALITY_REPORT_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_doc(report: dict[str, Any], path: Path = CHUNKING_DOC_PATH) -> None:
    by_doc_type = report.get("by_doc_type", {})
    lines = [
        "# Chunking Validation",
        "",
        "## Phase 6B-1 Goal",
        "",
        "Phase 6B-1 converts parser-passed samples into normalized metadata records and a "
        "chunk manifest for later vector-store ingestion. This phase does not write Chroma, "
        "call an embedding model, call an LLM, or run QA evaluation.",
        "",
        "## Normalization Design",
        "",
        "Normalization creates one metadata record per parser-passed sample. Full normalized "
        "text is written only to local cache under `data/knowledge_base/normalized/`, which is "
        "ignored by Git. Manifests store aliases, hashes, counts, source ids, source urls, and "
        "parser metadata.",
        "",
        "## Raw Text Policy",
        "",
        "Raw files, normalized text cache, and full chunk bodies are not committed because they "
        "may be large, licensed, or local-only. The committed manifests keep source tracing "
        "without storing full copyrighted or private text.",
        "",
        "## Chunk Strategy",
        "",
        "- DOCX: paragraph-aware aggregation with overlap.",
        "- PDF: page-marker and paragraph-aware aggregation for text-extractable samples.",
        "- HTML and Markdown: heading-aware metadata when headings are present.",
        "- JSON and YAML: schema/key-aware text representation and metadata.",
        "- CSV: skipped when no parser-passed CSV sample is available.",
        "",
        "## Metadata Fields",
        "",
        "Each chunk stores `chunk_id`, `normalized_id`, `source_id`, `sample_id`, `doc_type`, "
        "`domain`, `language`, `title`, `section_path`, optional `source_url`, optional page "
        "range, hash, metadata-only preview, parser metadata, and `embedding_written=false` / "
        "`chroma_written=false`.",
        "",
        "## Quality Summary",
        "",
        f"- Total chunks: {report.get('chunk_total')}",
        f"- Chunk char min/avg/max: {report.get('chunk_chars_min')} / "
        f"{report.get('chunk_chars_avg')} / {report.get('chunk_chars_max')}",
        f"- Empty chunks: {report.get('empty_chunk_count')}",
        f"- Missing metadata: {report.get('missing_metadata_count')}",
        f"- Duplicate chunk hashes: {report.get('duplicate_chunk_hash_count')}",
        f"- Preview max chars: {report.get('preview_max_chars')}",
        f"- Quality pass: {report.get('quality_pass')}",
        "",
        "## Distribution By Format",
        "",
        "| Format | Chunk Count |",
        "| --- | ---: |",
    ]
    for doc_type, count in sorted(by_doc_type.items()):
        lines.append(f"| {doc_type} | {count} |")
    lines.extend(
        [
            "",
            "## Current Limits",
            "",
            "- HTML samples are normalized when parser validation marks them as pass or when "
            "the local ignored HTML cache exists for a cataloged sample and the committed "
            "manifest is stale.",
            "- CSV, PPTX, and OCR are not forced when no parser-passed sample is available.",
            "- No retrieval quality or answer quality claims are made in this phase.",
            "",
            "## Phase 6B-2 Plan",
            "",
            "Phase 6B-2 should review chunk quality, adjust chunk sizes or section metadata if "
            "needed, and prepare a controlled local-only ingestion dry-run. Chroma and embedding "
            "should remain disabled until explicitly approved.",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def main() -> None:
    args = parse_args()
    records = _load_jsonl(args.chunk_manifest)
    report = inspect_chunks(records)
    _write_report(report)
    _write_doc(report)
    print(json.dumps(report, ensure_ascii=False, indent=2))  # noqa: T201


if __name__ == "__main__":
    main()
