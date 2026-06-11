"""Build a local corpus review pack from Phase 6 manifests.

This script reads metadata-only manifests and writes local review artifacts.
It does not read raw document bodies, write Chroma, call embeddings, or call LLMs.
"""

from __future__ import annotations

import csv
import html
import json
import random
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_DIR = ROOT / "data" / "knowledge_base" / "manifests"
OUTPUT_DIR = ROOT / "outputs" / "corpus_review"

SAMPLE_MANIFEST = MANIFEST_DIR / "sample_manifest.jsonl"
NORMALIZED_MANIFEST = MANIFEST_DIR / "normalized_manifest.jsonl"
CHUNK_MANIFEST = MANIFEST_DIR / "chunk_manifest.jsonl"
CHUNK_QUALITY_REPORT = MANIFEST_DIR / "chunk_quality_report.json"

SENSITIVE_TERMS = (
    "api_key",
    "api key",
    "bearer",
    "sk-",
    ".env",
    "password",
    "secret",
)
NOISE_TERMS = (
    "404",
    "not found",
    "navigation",
    "sidebar",
    "menu",
    "footer",
)


@dataclass(frozen=True)
class SuspiciousChunk:
    chunk: dict[str, Any]
    reasons: list[str]


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            msg = f"Invalid JSON at {path.relative_to(ROOT)}:{line_no}: {exc}"
            raise ValueError(msg) from exc
    return rows


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return " > ".join(str(item) for item in value if item is not None)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def html_escape(value: Any) -> str:
    return html.escape(stringify(value))


def pick(row: dict[str, Any], fields: list[str]) -> dict[str, str]:
    return {field: stringify(row.get(field)) for field in fields}


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(pick(row, fields))


def find_duplicate_previews(chunks: list[dict[str, Any]]) -> set[str]:
    previews = Counter(
        stringify(chunk.get("content_preview")).strip()
        for chunk in chunks
        if stringify(chunk.get("content_preview")).strip()
    )
    return {preview for preview, count in previews.items() if count > 1}


def inspect_suspicious_chunks(chunks: list[dict[str, Any]]) -> list[SuspiciousChunk]:
    duplicate_previews = find_duplicate_previews(chunks)
    suspicious: list[SuspiciousChunk] = []

    for chunk in chunks:
        reasons: list[str] = []
        preview = stringify(chunk.get("content_preview")).strip()
        preview_lower = preview.lower()
        title = stringify(chunk.get("title")).strip()
        source_url = stringify(chunk.get("source_url")).strip()
        section_path = stringify(chunk.get("section_path")).strip()
        doc_type = stringify(chunk.get("doc_type")).strip()

        try:
            chunk_chars = int(chunk.get("chunk_chars") or 0)
        except (TypeError, ValueError):
            chunk_chars = 0

        if chunk_chars < 80:
            reasons.append("chunk_chars_lt_80")
        if any(term in preview_lower for term in NOISE_TERMS):
            reasons.append("preview_contains_navigation_or_error_text")
        if not title:
            reasons.append("empty_title")
        if doc_type == "html" and not source_url:
            reasons.append("html_missing_source_url")
        if not section_path:
            reasons.append("empty_section_path")
        if len(preview) < 30:
            reasons.append("preview_too_short")
        if preview and preview in duplicate_previews:
            reasons.append("duplicate_preview")
        if any(term in preview_lower for term in SENSITIVE_TERMS):
            reasons.append("preview_contains_sensitive_keyword")

        if reasons:
            suspicious.append(SuspiciousChunk(chunk=chunk, reasons=reasons))

    return suspicious


def sample_chunks_by_doc_type(
    chunks: list[dict[str, Any]],
    per_doc_type: int = 5,
) -> dict[str, list[dict[str, Any]]]:
    rng = random.Random(20260611)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for chunk in chunks:
        grouped[stringify(chunk.get("doc_type")) or "unknown"].append(chunk)

    sampled: dict[str, list[dict[str, Any]]] = {}
    for doc_type in sorted(grouped):
        rows = grouped[doc_type]
        if len(rows) <= per_doc_type:
            sampled[doc_type] = rows
        else:
            sampled[doc_type] = sorted(
                rng.sample(rows, per_doc_type),
                key=lambda row: stringify(row.get("chunk_id")),
            )
    return sampled


def table_html(title: str, rows: list[dict[str, Any]], fields: list[str]) -> str:
    header = "".join(f"<th>{html_escape(field)}</th>" for field in fields)
    body_rows = []
    for row in rows:
        cells = "".join(f"<td>{html_escape(row.get(field))}</td>" for field in fields)
        body_rows.append(f"<tr>{cells}</tr>")
    body = "\n".join(body_rows) or f"<tr><td colspan='{len(fields)}'>No rows</td></tr>"
    return f"""
    <section>
      <h2>{html_escape(title)}</h2>
      <div class="table-wrap">
        <table>
          <thead><tr>{header}</tr></thead>
          <tbody>{body}</tbody>
        </table>
      </div>
    </section>
    """


def summary_cards(quality_report: dict[str, Any], suspicious_count: int) -> str:
    fields = [
        "chunk_total",
        "chunk_chars_min",
        "chunk_chars_avg",
        "chunk_chars_max",
        "empty_chunk_count",
        "missing_metadata_count",
        "duplicate_chunk_hash_count",
        "quality_pass",
    ]
    cards = [
        f"<div class='metric'><span>{html_escape(field)}</span><strong>{html_escape(quality_report.get(field))}</strong></div>"
        for field in fields
    ]
    cards.append(
        "<div class='metric'><span>suspicious_chunk_count</span>"
        f"<strong>{html_escape(suspicious_count)}</strong></div>"
    )
    return "<div class='metrics'>" + "\n".join(cards) + "</div>"


def counter_table(title: str, values: dict[str, Any]) -> str:
    rows = [{"name": key, "count": value} for key, value in sorted(values.items())]
    return table_html(title, rows, ["name", "count"])


def build_review_html(
    sources: list[dict[str, Any]],
    normalized: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
    quality_report: dict[str, Any],
    suspicious: list[SuspiciousChunk],
) -> str:
    source_fields = [
        "source_id",
        "fetch_status",
        "source_url",
        "local_cache_alias",
        "size_bytes",
        "error_summary",
    ]
    normalized_fields = [
        "normalized_id",
        "doc_type",
        "source_id",
        "title",
        "content_chars",
        "heading_count",
        "paragraph_count",
        "code_block_count",
        "source_url",
        "content_cache_alias",
        "normalization_status",
        "filter_reason",
        "review_status",
        "ingest_candidate",
    ]
    chunk_fields = [
        "chunk_id",
        "doc_type",
        "source_id",
        "title",
        "section_path",
        "chunk_chars",
        "content_preview",
    ]

    sampled_rows: list[dict[str, Any]] = []
    for rows in sample_chunks_by_doc_type(chunks).values():
        sampled_rows.extend(rows)

    suspicious_rows = [
        {"reason": ";".join(item.reasons), **item.chunk}
        for item in suspicious[:200]
    ]
    suspicious_fields = ["reason", *chunk_fields, "source_url"]

    by_doc_type = quality_report.get("by_doc_type") or dict(
        Counter(stringify(chunk.get("doc_type")) for chunk in chunks)
    )
    by_source_id = quality_report.get("by_source_id") or dict(
        Counter(stringify(chunk.get("source_id")) for chunk in chunks)
    )
    approved_normalized = [
        row
        for row in normalized
        if row.get("normalization_status") == "pass"
        and row.get("review_status") == "approved"
        and row.get("ingest_candidate") is True
    ]
    needs_review_normalized = [
        row
        for row in normalized
        if row.get("normalization_status") == "pass"
        and row.get("review_status") == "needs_review"
    ]
    filtered_normalized = [
        row
        for row in normalized
        if row.get("normalization_status") != "pass"
        or row.get("review_status") == "rejected"
    ]

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Phase 6B-1.5 Corpus Review Pack</title>
  <style>
    body {{
      color: #1f2937;
      font-family: Arial, sans-serif;
      line-height: 1.45;
      margin: 24px;
    }}
    h1, h2 {{ color: #111827; }}
    section {{ margin: 28px 0; }}
    table {{
      border-collapse: collapse;
      font-size: 13px;
      width: 100%;
    }}
    th, td {{
      border: 1px solid #d1d5db;
      padding: 6px 8px;
      text-align: left;
      vertical-align: top;
    }}
    th {{ background: #f3f4f6; position: sticky; top: 0; }}
    .table-wrap {{ max-height: 520px; overflow: auto; }}
    .metrics {{
      display: grid;
      gap: 10px;
      grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    }}
    .metric {{
      border: 1px solid #d1d5db;
      padding: 10px;
    }}
    .metric span {{ color: #6b7280; display: block; font-size: 12px; }}
    .metric strong {{ display: block; font-size: 18px; margin-top: 4px; }}
  </style>
</head>
<body>
  <h1>Phase 6B-1.5 Corpus Review Pack</h1>
  <p>This local pack is generated from metadata manifests only. It does not write Chroma, call embeddings, or call LLMs.</p>
  <section>
    <h2>Chunk Quality Summary</h2>
    {summary_cards(quality_report, len(suspicious))}
  </section>
  {counter_table("Chunks by doc_type", by_doc_type)}
  {counter_table("Chunks by source_id", by_source_id)}
  {table_html("Source Samples", sources, source_fields)}
  {table_html("Approved Normalized Candidates", approved_normalized, normalized_fields)}
  {table_html("Needs Review Normalized Samples", needs_review_normalized, normalized_fields)}
  {table_html("Filtered / Rejected Samples", filtered_normalized, normalized_fields)}
  {table_html("Random Chunk Samples", sampled_rows, chunk_fields)}
  {table_html("Suspicious Chunks", suspicious_rows, suspicious_fields)}
</body>
</html>
"""


def write_suspicious_csv(path: Path, suspicious: list[SuspiciousChunk]) -> None:
    fields = [
        "reason",
        "chunk_id",
        "doc_type",
        "source_id",
        "title",
        "section_path",
        "chunk_chars",
        "content_preview",
        "source_url",
    ]
    rows = [{"reason": ";".join(item.reasons), **item.chunk} for item in suspicious]
    write_csv(path, rows, fields)


def build_summary(
    sources: list[dict[str, Any]],
    normalized: list[dict[str, Any]],
    chunks: list[dict[str, Any]],
    quality_report: dict[str, Any],
    suspicious: list[SuspiciousChunk],
) -> dict[str, Any]:
    reason_counts = Counter(reason for item in suspicious for reason in item.reasons)
    return {
        "source_review_count": len(sources),
        "normalized_review_count": len(normalized),
        "chunk_review_count": len(chunks),
        "approved_normalized_count": sum(
            1
            for row in normalized
            if row.get("review_status") == "approved" and row.get("ingest_candidate") is True
        ),
        "needs_review_normalized_count": sum(
            1 for row in normalized if row.get("review_status") == "needs_review"
        ),
        "filtered_or_rejected_normalized_count": sum(
            1
            for row in normalized
            if row.get("normalization_status") != "pass" or row.get("review_status") == "rejected"
        ),
        "suspicious_chunk_count": len(suspicious),
        "suspicious_reason_counts": dict(sorted(reason_counts.items())),
        "chunk_quality_report": quality_report,
        "outputs": {
            "review_index": "outputs/corpus_review/review_index.html",
            "source_review": "outputs/corpus_review/source_review.csv",
            "normalized_review": "outputs/corpus_review/normalized_review.csv",
            "chunk_review": "outputs/corpus_review/chunk_review.csv",
            "suspicious_chunks": "outputs/corpus_review/suspicious_chunks.csv",
        },
        "writes_chroma": False,
        "calls_embedding": False,
        "calls_llm": False,
    }


def main() -> None:
    sources = read_jsonl(SAMPLE_MANIFEST)
    normalized = read_jsonl(NORMALIZED_MANIFEST)
    chunks = read_jsonl(CHUNK_MANIFEST)
    quality_report = read_json(CHUNK_QUALITY_REPORT)
    suspicious = inspect_suspicious_chunks(chunks)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    write_csv(
        OUTPUT_DIR / "source_review.csv",
        sources,
        [
            "sample_id",
            "source_id",
            "fetch_status",
            "source_url",
            "local_cache_alias",
            "size_bytes",
            "error_type",
            "error_summary",
            "format",
        ],
    )
    write_csv(
        OUTPUT_DIR / "normalized_review.csv",
        normalized,
        [
            "normalized_id",
            "doc_type",
            "source_id",
            "sample_id",
            "title",
            "content_chars",
            "heading_count",
            "paragraph_count",
            "code_block_count",
            "link_count",
            "source_url",
            "content_cache_alias",
            "normalization_status",
            "filter_reason",
            "review_status",
            "ingest_candidate",
        ],
    )
    write_csv(
        OUTPUT_DIR / "chunk_review.csv",
        chunks,
        [
            "chunk_id",
            "normalized_id",
            "doc_type",
            "source_id",
            "sample_id",
            "title",
            "section_path",
            "chunk_index",
            "chunk_chars",
            "content_preview",
            "source_url",
            "normalization_status",
            "filter_reason",
            "review_status",
            "ingest_candidate",
            "embedding_written",
            "chroma_written",
        ],
    )
    write_suspicious_csv(OUTPUT_DIR / "suspicious_chunks.csv", suspicious)

    review_html = build_review_html(sources, normalized, chunks, quality_report, suspicious)
    (OUTPUT_DIR / "review_index.html").write_text(review_html, encoding="utf-8")

    summary = build_summary(sources, normalized, chunks, quality_report, suspicious)
    (OUTPUT_DIR / "review_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(f"review_index={OUTPUT_DIR / 'review_index.html'}")
    print(f"source_review_count={len(sources)}")
    print(f"normalized_review_count={len(normalized)}")
    print(f"chunk_review_count={len(chunks)}")
    print(f"suspicious_chunk_count={len(suspicious)}")
    print(
        "suspicious_reason_counts="
        + json.dumps(summary["suspicious_reason_counts"], ensure_ascii=False, sort_keys=True)
    )
    print("writes_chroma=false")
    print("calls_embedding=false")
    print("calls_llm=false")


if __name__ == "__main__":
    main()
