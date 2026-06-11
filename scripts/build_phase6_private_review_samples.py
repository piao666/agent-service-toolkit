"""Build local-only private text samples for manual corpus review.

The output is intentionally ignored by Git. This script reads local normalized
text cache to show short sanitized snippets for human quality review only.
It does not write Chroma, call embeddings, or call LLMs.
"""

from __future__ import annotations

import csv
import html
import json
import random
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

from build_phase6_chunks import _paragraph_chunks, _sha256_text

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_DIR = ROOT / "data" / "knowledge_base" / "manifests"
CHUNK_MANIFEST = MANIFEST_DIR / "chunk_manifest.jsonl"
OUTPUT_DIR = ROOT / "outputs" / "corpus_review_private"


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return " > ".join(str(item) for item in value if item is not None)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def sanitize_private_text(text: str) -> str:
    sanitized = re.sub(r"sk-[A-Za-z0-9_\-]{4,}", "[SECRET_PLACEHOLDER]", text)
    sanitized = re.sub(
        r"Authorization:\s*Bearer\s+<[^>]+>",
        "Authorization: Bearer [SECRET_PLACEHOLDER]",
        sanitized,
        flags=re.IGNORECASE,
    )
    sanitized = re.sub(
        r"Authorization:\s*Bearer\s+[A-Za-z0-9._\-]+",
        "Authorization: Bearer [SECRET_PLACEHOLDER]",
        sanitized,
        flags=re.IGNORECASE,
    )
    sanitized = re.sub(
        r"API[\s_\x00-\x1f]*keys?",
        "[SECRET_FIELD]",
        sanitized,
        flags=re.IGNORECASE,
    )
    sanitized = re.sub(r"[A-Za-z]:\\[^\s\"'<>]+", "[LOCAL_PATH]", sanitized)
    sanitized = re.sub(r"/(?:Users|home|mnt|var|tmp)/[^\s\"'<>]+", "[LOCAL_PATH]", sanitized)
    return sanitized


def select_chunks(chunks: list[dict[str, Any]], per_source: int = 3) -> list[dict[str, Any]]:
    rng = random.Random(20260611)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for chunk in chunks:
        grouped[stringify(chunk.get("source_id")) or "unknown"].append(chunk)

    selected: list[dict[str, Any]] = []
    for source_id in sorted(grouped):
        rows = grouped[source_id]
        if len(rows) <= per_source:
            picked = rows
        else:
            picked = rng.sample(rows, per_source)
        selected.extend(sorted(picked, key=lambda row: stringify(row.get("chunk_id"))))
    return selected


def recover_chunk_text(chunk: dict[str, Any]) -> str:
    metadata = chunk.get("metadata") if isinstance(chunk.get("metadata"), dict) else {}
    alias = stringify(metadata.get("content_cache_alias"))
    if not alias:
        return ""
    cache_path = ROOT / "data" / "knowledge_base" / alias
    if not cache_path.exists():
        return ""

    text = cache_path.read_text(encoding="utf-8", errors="ignore").strip()
    size = int(chunk.get("chunk_size") or 900)
    overlap = int(chunk.get("chunk_overlap") or 100)
    expected_hash = stringify(chunk.get("chunk_sha256"))
    for candidate in _paragraph_chunks(text, size=size, overlap=overlap):
        if _sha256_text(candidate) == expected_hash:
            return candidate
    return ""


def snippet(text: str, max_chars: int = 500) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    if not compact:
        return ""
    return sanitize_private_text(compact[:max_chars])


def build_rows(chunks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for chunk in select_chunks(chunks):
        rows.append(
            {
                "chunk_id": stringify(chunk.get("chunk_id")),
                "doc_type": stringify(chunk.get("doc_type")),
                "source_id": stringify(chunk.get("source_id")),
                "title": stringify(chunk.get("title")),
                "section_path": stringify(chunk.get("section_path")),
                "chunk_chars": stringify(chunk.get("chunk_chars")),
                "source_url": stringify(chunk.get("source_url")),
                "text_sample": snippet(recover_chunk_text(chunk)),
            }
        )
    return rows


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    fields = [
        "chunk_id",
        "doc_type",
        "source_id",
        "title",
        "section_path",
        "chunk_chars",
        "source_url",
        "text_sample",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def write_html(path: Path, rows: list[dict[str, str]]) -> None:
    fields = [
        "chunk_id",
        "doc_type",
        "source_id",
        "title",
        "section_path",
        "chunk_chars",
        "source_url",
        "text_sample",
    ]
    header = "".join(f"<th>{html.escape(field)}</th>" for field in fields)
    body = "\n".join(
        "<tr>"
        + "".join(f"<td>{html.escape(row.get(field, ''))}</td>" for field in fields)
        + "</tr>"
        for row in rows
    )
    path.write_text(
        f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Private Corpus Text Samples</title>
  <style>
    body {{ color: #111827; font-family: Arial, sans-serif; margin: 24px; }}
    table {{ border-collapse: collapse; font-size: 13px; width: 100%; }}
    th, td {{ border: 1px solid #d1d5db; padding: 6px 8px; vertical-align: top; }}
    th {{ background: #f3f4f6; position: sticky; top: 0; }}
    .table-wrap {{ max-height: 760px; overflow: auto; }}
  </style>
</head>
<body>
  <h1>Private Corpus Text Samples</h1>
  <p>Local-only review output. Sanitized snippets are not intended for Git.</p>
  <div class="table-wrap"><table><thead><tr>{header}</tr></thead><tbody>{body}</tbody></table></div>
</body>
</html>
""",
        encoding="utf-8",
    )


def main() -> None:
    chunks = read_jsonl(CHUNK_MANIFEST)
    rows = build_rows(chunks)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    write_csv(OUTPUT_DIR / "private_text_samples.csv", rows)
    write_html(OUTPUT_DIR / "private_text_samples.html", rows)
    print(f"private_text_samples={OUTPUT_DIR / 'private_text_samples.html'}")
    print(f"private_text_sample_count={len(rows)}")
    print("writes_chroma=false")
    print("calls_embedding=false")
    print("calls_llm=false")


if __name__ == "__main__":
    main()
