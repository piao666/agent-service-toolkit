from __future__ import annotations

import argparse
import csv
import hashlib
import importlib.util
import json
import os
import re
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

try:
    from datetime import UTC as DATETIME_UTC
except ImportError:  # pragma: no cover - Python 3.10 compatibility.
    DATETIME_UTC = timezone.utc  # noqa: UP017

try:
    from pypdf import PdfReader
except Exception:  # pragma: no cover - optional parser dependency.
    PdfReader = None  # type: ignore[assignment]

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover - supports bare Python script runs.
    yaml = None  # type: ignore[assignment]


REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_DIR = REPO_ROOT / "data" / "knowledge_base" / "manifests"
SAMPLE_MANIFEST_PATH = MANIFEST_DIR / "sample_manifest.jsonl"
PARSER_MANIFEST_PATH = MANIFEST_DIR / "parser_validation.jsonl"
PARSER_REPORT_PATH = REPO_ROOT / "docs" / "enterprise_rag_backend" / "PARSER_VALIDATION.md"
RAW_WEB_ROOT = REPO_ROOT / "data" / "knowledge_base" / "raw" / "web_html"
DEFAULT_SUBDIRS = ("DL", "NLP", "Agent")
SKIP_DIR_NAMES = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".uv-cache",
    ".venv",
    "__pycache__",
    "env",
    "site-packages",
    "venv",
}
MAX_LOCAL_DOCX = 3
MAX_LOCAL_PDF = 3


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate Phase 6A-2 parsers without chunking, embedding, Chroma, or LLM calls."
    )
    parser.add_argument("--course-root", type=Path, default=_default_course_root())
    parser.add_argument("--max-local-docx", type=int, default=MAX_LOCAL_DOCX)
    parser.add_argument("--max-local-pdf", type=int, default=MAX_LOCAL_PDF)
    return parser.parse_args()


def _default_course_root() -> Path:
    configured_root = os.getenv("COURSE_DOC_ROOT")
    if configured_root:
        return Path(configured_root)
    current_anchor = Path.cwd().anchor
    if current_anchor:
        return Path(current_anchor) / "python"
    return Path("python")


def _sha256_text(text: str) -> str | None:
    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized:
        return None
    return hashlib.sha256(normalized[:2000].encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _base_record(
    validation_id: str,
    sample_id: str,
    doc_type: str,
    parser: str,
    notes: str,
) -> dict[str, Any]:
    return {
        "validation_id": validation_id,
        "sample_id": sample_id,
        "doc_type": doc_type,
        "parser": parser,
        "status": "fail",
        "title_count": None,
        "paragraph_count": None,
        "table_count": None,
        "page_count": None,
        "line_count": None,
        "field_count": None,
        "top_level_keys": None,
        "text_extractable": None,
        "body_preview_hash": None,
        "content_sha256": None,
        "error_type": None,
        "error_summary": None,
        "notes": notes,
        "validated_at": datetime.now(DATETIME_UTC).isoformat(),
    }


def _error_record(
    record: dict[str, Any],
    exc: Exception,
    *,
    status: str = "fail",
) -> dict[str, Any]:
    return {
        **record,
        "status": status,
        "error_type": type(exc).__name__,
        "error_summary": str(exc).replace("\n", " ").strip()[:240],
    }


def _is_skipped(path: Path) -> bool:
    return any(part in SKIP_DIR_NAMES for part in path.parts)


def _iter_course_files(course_root: Path, suffix: str, limit: int) -> list[Path]:
    files: list[Path] = []
    for subdir in DEFAULT_SUBDIRS:
        scan_root = course_root / subdir
        if not scan_root.exists():
            continue
        for path in sorted(scan_root.rglob(f"*{suffix}")):
            if len(files) >= limit:
                return files
            if path.is_file() and not _is_skipped(path):
                files.append(path)
    return files


def _docx_validation(path: Path, index: int) -> dict[str, Any]:
    record = _base_record(
        validation_id=f"parser_docx_{index:03d}",
        sample_id=f"local_course_docx_{index:03d}",
        doc_type="docx",
        parser="docx-zip-xml",
        notes="Local course metadata only. No raw text or local path stored.",
    )
    try:
        with zipfile.ZipFile(path) as archive:
            xml_bytes = archive.read("word/document.xml")
        root = ElementTree.fromstring(xml_bytes)
        namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        paragraphs = root.findall(".//w:p", namespace)
        tables = root.findall(".//w:tbl", namespace)
        preview_parts: list[str] = []
        title_count = 0
        for paragraph in paragraphs:
            texts = [
                text_node.text or ""
                for text_node in paragraph.findall(".//w:t", namespace)
                if text_node.text
            ]
            paragraph_text = "".join(texts).strip()
            if paragraph_text and len(preview_parts) < 8:
                preview_parts.append(paragraph_text)
            styles = paragraph.findall(".//w:pStyle", namespace)
            for style in styles:
                style_value = style.attrib.get(
                    "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val",
                    "",
                )
                if style_value.lower().startswith("heading") or "标题" in style_value:
                    title_count += 1
        return {
            **record,
            "status": "pass",
            "title_count": title_count,
            "paragraph_count": len(paragraphs),
            "table_count": len(tables),
            "text_extractable": bool(preview_parts),
            "body_preview_hash": _sha256_text(" ".join(preview_parts)),
            "content_sha256": _sha256_file(path),
        }
    except Exception as exc:
        return _error_record(record, exc)


def _pdf_page_count_by_marker(path: Path) -> int | None:
    try:
        content = path.read_bytes()
    except Exception:
        return None
    count = len(re.findall(rb"/Type\s*/Page\b", content))
    return count or None


def _pdf_validation(path: Path, index: int) -> dict[str, Any]:
    parser_name = "pypdf" if PdfReader is not None else "pdf-marker-metadata"
    record = _base_record(
        validation_id=f"parser_pdf_{index:03d}",
        sample_id=f"local_course_pdf_{index:03d}",
        doc_type="pdf",
        parser=parser_name,
        notes="Local course metadata and text-extractability check only. No raw text stored.",
    )
    try:
        page_count = None
        text_preview = ""
        if PdfReader is not None:
            reader = PdfReader(str(path))
            page_count = len(reader.pages)
            for page in reader.pages[:3]:
                text_preview += page.extract_text() or ""
                if len(text_preview) > 2000:
                    break
        else:
            page_count = _pdf_page_count_by_marker(path)
        text_extractable = bool(re.sub(r"\s+", "", text_preview))
        suspected_scanned = page_count is not None and not text_extractable and PdfReader is not None
        note = record["notes"]
        if suspected_scanned:
            note = f"{note} Suspected scanned PDF or image-heavy PDF."
        if PdfReader is None:
            note = f"{note} pypdf not available; text extraction was not attempted."
        return {
            **record,
            "status": "pass",
            "page_count": page_count,
            "text_extractable": text_extractable,
            "body_preview_hash": _sha256_text(text_preview),
            "content_sha256": _sha256_file(path),
            "notes": note,
        }
    except Exception as exc:
        return _error_record(record, exc)


class MinimalHTMLStatsParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.title = ""
        self.headings: list[str] = []
        self.body_text_parts: list[str] = []
        self.code_block_count = 0
        self.link_count = 0
        self._current_tag: str | None = None
        self._title_parts: list[str] = []
        self._heading_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._current_tag = tag
        if tag in {"pre", "code"}:
            self.code_block_count += 1
        if tag == "a":
            self.link_count += 1

    def handle_endtag(self, tag: str) -> None:
        if tag == "title":
            self.title = " ".join(self._title_parts).strip()
            self._title_parts = []
        if tag in {"h1", "h2", "h3"} and self._heading_parts:
            heading = " ".join(self._heading_parts).strip()
            if heading:
                self.headings.append(heading)
            self._heading_parts = []
        self._current_tag = None

    def handle_data(self, data: str) -> None:
        clean = re.sub(r"\s+", " ", data).strip()
        if not clean:
            return
        if self._current_tag == "title":
            self._title_parts.append(clean)
        elif self._current_tag in {"h1", "h2", "h3"}:
            self._heading_parts.append(clean)
        elif self._current_tag not in {"script", "style"}:
            self.body_text_parts.append(clean)

    @property
    def body_text_length(self) -> int:
        return len(" ".join(self.body_text_parts))


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            if line.strip():
                records.append(json.loads(line))
    return records


def _html_validation(sample_record: dict[str, Any], index: int) -> dict[str, Any]:
    record = _base_record(
        validation_id=f"parser_html_{index:03d}",
        sample_id=str(sample_record.get("sample_id") or f"html_{index:03d}"),
        doc_type="html",
        parser="html.parser",
        notes="Seed page only. No raw HTML body stored in manifests or report.",
    )
    if sample_record.get("fetch_status") != "ok":
        return {
            **record,
            "status": "not_available",
            "error_type": sample_record.get("error_type"),
            "error_summary": sample_record.get("error_summary") or "sample fetch did not succeed",
        }
    cache_alias = str(sample_record.get("local_cache_alias") or "")
    cache_path = REPO_ROOT / "data" / "knowledge_base" / "raw" / cache_alias
    if not cache_path.exists():
        return {
            **record,
            "status": "not_available",
            "error_type": "FileNotFoundError",
            "error_summary": "HTML cache file is not available in the current environment.",
        }
    try:
        html = cache_path.read_text(encoding="utf-8", errors="ignore")
        parser = MinimalHTMLStatsParser()
        parser.feed(html)
        body_text = " ".join(parser.body_text_parts)
        return {
            **record,
            "status": "pass" if parser.body_text_length > 0 else "fail",
            "title_count": 1 if parser.title else 0,
            "paragraph_count": None,
            "table_count": None,
            "field_count": parser.link_count,
            "top_level_keys": parser.headings[:8],
            "text_extractable": parser.body_text_length > 0,
            "body_preview_hash": _sha256_text(body_text),
            "content_sha256": sample_record.get("content_sha256") or _sha256_file(cache_path),
            "html_body_length": parser.body_text_length,
            "html_code_block_count": parser.code_block_count,
            "html_link_count": parser.link_count,
            "source_url": sample_record.get("source_url"),
        }
    except Exception as exc:
        return _error_record(record, exc)


def _markdown_validation(path: Path, index: int) -> dict[str, Any]:
    record = _base_record(
        validation_id=f"parser_markdown_{index:03d}",
        sample_id=f"repo_markdown_{index:03d}",
        doc_type="markdown",
        parser="plain-text-markdown",
        notes=f"Repository Markdown sample: {path.name}. No full content stored.",
    )
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
        headings = [line for line in text.splitlines() if line.lstrip().startswith("#")]
        return {
            **record,
            "status": "pass",
            "title_count": len(headings),
            "line_count": len(text.splitlines()),
            "text_extractable": bool(text.strip()),
            "body_preview_hash": _sha256_text(text),
            "content_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        }
    except Exception as exc:
        return _error_record(record, exc)


def _json_validation(path: Path, index: int) -> dict[str, Any]:
    record = _base_record(
        validation_id=f"parser_json_{index:03d}",
        sample_id=f"repo_json_{index:03d}",
        doc_type="json",
        parser="json",
        notes=f"Repository JSON sample: {path.name}. No full content stored.",
    )
    try:
        text = path.read_text(encoding="utf-8")
        data = json.loads(text)
        keys = list(data.keys()) if isinstance(data, dict) else []
        return {
            **record,
            "status": "pass",
            "line_count": len(text.splitlines()),
            "field_count": len(keys),
            "top_level_keys": keys[:20],
            "text_extractable": True,
            "body_preview_hash": _sha256_text(" ".join(keys)),
            "content_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        }
    except Exception as exc:
        return _error_record(record, exc)


def _yaml_validation(path: Path, index: int) -> dict[str, Any]:
    record = _base_record(
        validation_id=f"parser_yaml_{index:03d}",
        sample_id=f"repo_yaml_{index:03d}",
        doc_type="yaml",
        parser="pyyaml" if yaml is not None else "limited-yaml",
        notes=f"Repository YAML sample: {path.name}. No full content stored.",
    )
    try:
        text = path.read_text(encoding="utf-8")
        if yaml is not None:
            loaded = yaml.safe_load(text) or {}
            keys = list(loaded.keys()) if isinstance(loaded, dict) else []
        else:
            keys = [line[:-1] for line in text.splitlines() if line and not line.startswith(" ")]
        return {
            **record,
            "status": "pass",
            "line_count": len(text.splitlines()),
            "field_count": len(keys),
            "top_level_keys": keys[:20],
            "text_extractable": True,
            "body_preview_hash": _sha256_text(" ".join(keys)),
            "content_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        }
    except Exception as exc:
        return _error_record(record, exc)


def _csv_validation(index: int) -> dict[str, Any]:
    record = _base_record(
        validation_id=f"parser_csv_{index:03d}",
        sample_id="repo_csv_not_available",
        doc_type="csv",
        parser="csv",
        notes="sample_not_available_in_current_environment",
    )
    csv_candidates = [
        path
        for path in REPO_ROOT.rglob("*.csv")
        if not any(part in SKIP_DIR_NAMES or part.startswith(".") for part in path.parts)
    ]
    if not csv_candidates:
        return {**record, "status": "not_available"}
    path = sorted(csv_candidates)[0]
    try:
        with path.open("r", encoding="utf-8", errors="ignore", newline="") as file:
            reader = csv.reader(file)
            rows = list(reader)
        field_count = len(rows[0]) if rows else 0
        return {
            **record,
            "sample_id": "repo_csv_001",
            "status": "pass",
            "line_count": len(rows),
            "field_count": field_count,
            "text_extractable": bool(rows),
            "content_sha256": _sha256_file(path),
            "notes": f"Repository CSV sample: {path.name}. No full content stored.",
        }
    except Exception as exc:
        return _error_record(record, exc)


def _availability_record(
    validation_id: str,
    sample_id: str,
    doc_type: str,
    parser_name: str,
    module_names: list[str],
    sample_available: bool,
) -> dict[str, Any]:
    available_module = next(
        (module_name for module_name in module_names if importlib.util.find_spec(module_name)),
        None,
    )
    status = "pass" if available_module else "not_available"
    note = "availability check only"
    if not sample_available:
        note = f"{note}; sample_not_available_in_current_environment"
    return {
        **_base_record(validation_id, sample_id, doc_type, parser_name, note),
        "status": status,
        "text_extractable": None,
        "parser_available": available_module is not None,
        "available_module": available_module,
        "sample_available": sample_available,
    }


def _write_jsonl(records: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as file:
        for record in records:
            file.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def _status_for(records: list[dict[str, Any]], doc_type: str) -> str:
    matching = [record for record in records if record["doc_type"] == doc_type]
    if not matching:
        return "not_available"
    if any(record["status"] == "pass" for record in matching):
        return "pass"
    if all(record["status"] == "not_available" for record in matching):
        return "not_available"
    return "fail"


def _format_counts(records: list[dict[str, Any]]) -> Counter[str]:
    return Counter(str(record["doc_type"]) for record in records)


def _failure_rows(records: list[dict[str, Any]]) -> list[str]:
    rows: list[str] = []
    for record in records:
        if record["status"] == "pass":
            continue
        if record["status"] == "not_available" and not record.get("error_type"):
            continue
        rows.append(
            "| {sample_id} | {doc_type} | {error_type} | {error_summary} |".format(
                sample_id=record["sample_id"],
                doc_type=record["doc_type"],
                error_type=record.get("error_type") or "",
                error_summary=(record.get("error_summary") or "").replace("|", "/"),
            )
        )
    if not rows:
        rows.append("| None | - | - | - |")
    return rows


def _write_report(records: list[dict[str, Any]], path: Path = PARSER_REPORT_PATH) -> None:
    counts = _format_counts(records)
    status_by_format = {doc_type: _status_for(records, doc_type) for doc_type in counts}
    matrix = [
        ("DOCX", "docx", "docx-zip-xml", "Local course metadata only"),
        ("PDF text", "pdf", "pypdf/pdf-marker-metadata", "Metadata/text extractability check"),
        ("HTML", "html", "html.parser", "Seed pages only"),
        ("Markdown", "markdown", "plain text", "Repo docs"),
        ("JSON", "json", "json", "Schema files"),
        ("YAML", "yaml", "yaml", "source_catalog"),
        ("CSV", "csv", "csv", "Small structured sample"),
        ("PPTX", "pptx", "python-pptx", "Availability check"),
        ("Scanned PDF/OCR", "scanned_pdf_ocr", "OCR tool", "Availability check"),
    ]
    lines = [
        "# Parser Validation",
        "",
        "## Phase 6A-2 Goal",
        "",
        "Phase 6A-2 validates a controlled multi-format parser path for the AI autonomous "
        "learning and large language model technology knowledge base. It does not chunk, "
        "embed, write Chroma, call an LLM, or start QA evaluation.",
        "",
        "## Why Small Samples Only",
        "",
        "Small samples keep the workflow reproducible and auditable. Full-site crawling or bulk "
        "document collection would introduce noisy pages, licensing ambiguity, unstable diffs, "
        "and large raw files that should not be committed.",
        "",
        "## Sample Source Summary",
        "",
        f"- Total validation records: {len(records)}",
        f"- HTML records: {counts.get('html', 0)}",
        f"- Local DOCX records: {counts.get('docx', 0)}",
        f"- Local PDF records: {counts.get('pdf', 0)}",
        "- Raw course files are inspected in place and are not copied into the repository.",
        "",
        "## Format Coverage",
        "",
        "| Format | Sample Count | Parser | Status | Notes |",
        "| --- | ---: | --- | --- | --- |",
    ]
    for label, doc_type, parser_name, notes in matrix:
        lines.append(
            f"| {label} | {counts.get(doc_type, 0)} | {parser_name} | "
            f"{status_by_format.get(doc_type, 'not_available')} | {notes} |"
        )
    lines.extend(
        [
            "",
            "## Failure Records",
            "",
            "| Sample | Format | Error Type | Error Summary |",
            "| --- | --- | --- | --- |",
            *_failure_rows(records),
            "",
            "## Raw File Policy",
            "",
            "Raw DOCX, PDF, PPT/PPTX, HTML cache files, normalized text, Chroma databases, "
            "model weights, logs, and secrets are not committed. Manifests store only metadata, "
            "hashes, counts, parser status, and source aliases.",
            "",
            "## Before Phase 6B",
            "",
            "- Review failed or unavailable parser capabilities.",
            "- Decide which small raw samples are allowed for local-only cache use.",
            "- Confirm license and redistribution status before normalization.",
            "- Keep local embedding and Chroma writes disabled until ingestion is explicitly started.",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def build_records(args: argparse.Namespace) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for index, path in enumerate(
        _iter_course_files(args.course_root, ".docx", args.max_local_docx),
        start=1,
    ):
        records.append(_docx_validation(path, index))
    for index, path in enumerate(
        _iter_course_files(args.course_root, ".pdf", args.max_local_pdf),
        start=1,
    ):
        records.append(_pdf_validation(path, index))

    sample_records = _load_jsonl(SAMPLE_MANIFEST_PATH)
    html_index = 1
    for sample_record in sample_records:
        if sample_record.get("format") == "html":
            records.append(_html_validation(sample_record, html_index))
            html_index += 1

    markdown_path = REPO_ROOT / "README.md"
    if markdown_path.exists():
        records.append(_markdown_validation(markdown_path, 1))
    else:
        records.append(
            {
                **_base_record(
                    "parser_markdown_001",
                    "repo_markdown_not_available",
                    "markdown",
                    "plain-text-markdown",
                    "sample_not_available_in_current_environment",
                ),
                "status": "not_available",
            }
        )

    json_paths = [
        MANIFEST_DIR / "document_manifest.schema.json",
        MANIFEST_DIR / "chunk_manifest.schema.json",
    ]
    for index, path in enumerate([path for path in json_paths if path.exists()], start=1):
        records.append(_json_validation(path, index))

    yaml_path = MANIFEST_DIR / "source_catalog.yaml"
    if yaml_path.exists():
        records.append(_yaml_validation(yaml_path, 1))

    records.append(_csv_validation(1))
    records.append(
        _availability_record(
            "parser_pptx_001",
            "pptx_sample_not_available",
            "pptx",
            "python-pptx",
            ["pptx"],
            sample_available=False,
        )
    )
    scanned_samples = list((REPO_ROOT / "data" / "knowledge_base" / "raw" / "scanned_pdf").glob("*.pdf"))
    records.append(
        _availability_record(
            "parser_ocr_001",
            "scanned_pdf_sample",
            "scanned_pdf_ocr",
            "ocr",
            ["pytesseract", "easyocr"],
            sample_available=bool(scanned_samples),
        )
    )
    return records


def main() -> None:
    args = parse_args()
    records = build_records(args)
    _write_jsonl(records, PARSER_MANIFEST_PATH)
    _write_report(records)

    counts_by_type: dict[str, int] = defaultdict(int)
    pass_by_type: dict[str, int] = defaultdict(int)
    for record in records:
        counts_by_type[str(record["doc_type"])] += 1
        if record["status"] == "pass":
            pass_by_type[str(record["doc_type"])] += 1
    summary = {
        "validation_record_count": len(records),
        "counts_by_type": dict(counts_by_type),
        "pass_by_type": dict(pass_by_type),
        "parser_manifest_path": str(PARSER_MANIFEST_PATH.relative_to(REPO_ROOT)),
        "parser_report_path": str(PARSER_REPORT_PATH.relative_to(REPO_ROOT)),
        "writes_chroma": False,
        "calls_embedding": False,
        "calls_llm": False,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))  # noqa: T201


if __name__ == "__main__":
    main()
