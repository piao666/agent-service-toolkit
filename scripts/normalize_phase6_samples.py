from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import zipfile
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

try:
    from datetime import UTC as DATETIME_UTC
except ImportError:  # pragma: no cover - Python 3.10 compatibility.
    DATETIME_UTC = timezone.utc  # noqa: UP017


REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_DIR = REPO_ROOT / "data" / "knowledge_base" / "manifests"
NORMALIZED_ROOT = REPO_ROOT / "data" / "knowledge_base" / "normalized"
PARSER_VALIDATION_PATH = MANIFEST_DIR / "parser_validation.jsonl"
SAMPLE_MANIFEST_PATH = MANIFEST_DIR / "sample_manifest.jsonl"
DOCUMENT_MANIFEST_PATH = MANIFEST_DIR / "document_manifest.jsonl"
SOURCE_CATALOG_PATH = MANIFEST_DIR / "source_catalog.yaml"
NORMALIZED_MANIFEST_PATH = MANIFEST_DIR / "normalized_manifest.jsonl"
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


def _load_optional_venv_packages() -> None:
    version = f"Python{sys.version_info.major}{sys.version_info.minor}"
    candidates = [
        REPO_ROOT / ".venv" / "Lib" / "site-packages",
        REPO_ROOT / ".venv" / "lib" / version / "site-packages",
    ]
    for candidate in candidates:
        if candidate.exists() and str(candidate) not in sys.path:
            sys.path.append(str(candidate))


_load_optional_venv_packages()

try:
    from pypdf import PdfReader
except Exception:  # pragma: no cover - optional parser dependency.
    PdfReader = None  # type: ignore[assignment]

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover - supports bare Python script runs.
    yaml = None  # type: ignore[assignment]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Normalize Phase 6 parser-passed samples without embedding or Chroma writes."
    )
    parser.add_argument("--course-root", type=Path, default=_default_course_root())
    parser.add_argument("--max-local-scan-files", type=int, default=200)
    return parser.parse_args()


def _default_course_root() -> Path:
    configured_root = os.getenv("COURSE_DOC_ROOT")
    if configured_root:
        return Path(configured_root)
    current_anchor = Path.cwd().anchor
    if current_anchor:
        return Path(current_anchor) / "python"
    return Path("python")


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def _write_jsonl(records: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as file:
        for record in records:
            file.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_text(text: str) -> str:
    text = text.replace("\x00", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _parse_scalar(value: str) -> Any:
    value = value.strip()
    if value == '""':
        return ""
    if value in {"true", "false"}:
        return value == "true"
    if value.isdigit():
        return int(value)
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        return value[1:-1]
    return value


def _load_catalog_without_yaml(path: Path) -> dict[str, dict[str, Any]]:
    catalog: dict[str, dict[str, Any]] = {}
    current_source: dict[str, Any] | None = None
    current_section: dict[str, Any] | None = None
    current_list: list[Any] | None = None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        line = raw_line.strip()
        if indent == 0 and line.endswith(":"):
            current_source = {}
            catalog[line[:-1]] = current_source
            current_section = None
            current_list = None
            continue
        if current_source is None:
            raise ValueError("source catalog content appeared before a source_id")
        if indent == 2:
            key, _, value = line.partition(":")
            if value.strip():
                current_source[key] = _parse_scalar(value)
                current_section = None
                current_list = None
            else:
                current_section = {}
                current_source[key] = current_section
                current_list = None
            continue
        if indent == 4 and current_section is not None:
            key, _, value = line.partition(":")
            if value.strip():
                current_section[key] = _parse_scalar(value)
                current_list = None
            else:
                current_list = []
                current_section[key] = current_list
            continue
        if indent == 6 and current_list is not None and line.startswith("- "):
            current_list.append(_parse_scalar(line[2:]))
            continue
    return catalog


def _load_catalog(path: Path = SOURCE_CATALOG_PATH) -> dict[str, dict[str, Any]]:
    if yaml is not None:
        with path.open("r", encoding="utf-8") as file:
            loaded = yaml.safe_load(file) or {}
        return loaded if isinstance(loaded, dict) else {}
    return _load_catalog_without_yaml(path)


def _is_skipped(path: Path) -> bool:
    return any(part in SKIP_DIR_NAMES for part in path.parts)


def _iter_course_files(course_root: Path, suffixes: set[str], limit: int) -> list[Path]:
    files: list[Path] = []
    for subdir in DEFAULT_SUBDIRS:
        scan_root = course_root / subdir
        if not scan_root.exists():
            continue
        for path in sorted(scan_root.rglob("*")):
            if len(files) >= limit:
                return files
            if path.is_file() and not _is_skipped(path) and path.suffix.lower() in suffixes:
                files.append(path)
    return files


def _local_file_index(course_root: Path, limit: int) -> dict[str, Path]:
    index: dict[str, Path] = {}
    for path in _iter_course_files(course_root, {".docx", ".pdf"}, limit):
        try:
            index[_sha256_file(path)] = path
        except OSError:
            continue
    return index


def _document_by_hash(records: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        str(record.get("sha256")): record
        for record in records
        if record.get("sha256")
    }


def _source_info(source_id: str | None, catalog: dict[str, dict[str, Any]]) -> dict[str, str | None]:
    source = catalog.get(source_id or "", {})
    return {
        "source_id": source_id or "repo_project_files",
        "language": str(source.get("language") or "unknown"),
        "domain": str(source.get("domain") or "repo_metadata"),
        "title": str(source.get("title") or source_id or "Repository sample"),
    }


def _extract_docx(path: Path) -> tuple[str, list[str]]:
    with zipfile.ZipFile(path) as archive:
        xml_bytes = archive.read("word/document.xml")
    root = ElementTree.fromstring(xml_bytes)
    namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    paragraphs: list[str] = []
    headings: list[str] = []
    for paragraph in root.findall(".//w:p", namespace):
        text = "".join(
            node.text or ""
            for node in paragraph.findall(".//w:t", namespace)
            if node.text
        ).strip()
        if not text:
            continue
        paragraphs.append(text)
        styles = paragraph.findall(".//w:pStyle", namespace)
        if any(
            (style.attrib.get(
                "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val",
                "",
            ).lower().startswith("heading"))
            or ("标题" in style.attrib.get(
                "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val",
                "",
            ))
            for style in styles
        ):
            headings.append(text)
    return _safe_text("\n\n".join(paragraphs)), headings


def _extract_pdf(path: Path) -> tuple[str, int | None]:
    if PdfReader is None:
        raise RuntimeError("pypdf is not available for text-extractable PDF normalization")
    reader = PdfReader(str(path))
    page_texts: list[str] = []
    for index, page in enumerate(reader.pages, start=1):
        text = _safe_text(page.extract_text() or "")
        if text:
            page_texts.append(f"[page:{index}]\n{text}")
    return _safe_text("\n\n".join(page_texts)), len(reader.pages)


class NormalizedHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.title = ""
        self.headings: list[str] = []
        self.body_parts: list[str] = []
        self.code_block_count = 0
        self.link_count = 0
        self._tag: str | None = None
        self._title_parts: list[str] = []
        self._heading_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._tag = tag
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
                self.body_parts.append(f"# {heading}")
            self._heading_parts = []
        self._tag = None

    def handle_data(self, data: str) -> None:
        clean = re.sub(r"\s+", " ", data).strip()
        if not clean:
            return
        if self._tag == "title":
            self._title_parts.append(clean)
        elif self._tag in {"h1", "h2", "h3"}:
            self._heading_parts.append(clean)
        elif self._tag not in {"script", "style"}:
            self.body_parts.append(clean)


def _extract_html(path: Path) -> tuple[str, str, list[str], int, int]:
    parser = NormalizedHTMLParser()
    parser.feed(path.read_text(encoding="utf-8", errors="ignore"))
    text = _safe_text("\n\n".join(parser.body_parts))
    return text, parser.title, parser.headings, parser.code_block_count, parser.link_count


def _repo_text_sample(doc_type: str) -> tuple[Path, str]:
    if doc_type == "markdown":
        path = REPO_ROOT / "README.md"
    elif doc_type == "json":
        path = MANIFEST_DIR / "document_manifest.schema.json"
    elif doc_type == "yaml":
        path = SOURCE_CATALOG_PATH
    else:
        raise ValueError(f"Unsupported repository doc_type: {doc_type}")
    return path, path.read_text(encoding="utf-8", errors="ignore")


def _record(
    *,
    index: int,
    validation: dict[str, Any],
    source_id: str | None,
    sample_id: str | None,
    doc_id: str | None,
    source_url: str | None,
    text: str,
    headings: list[str],
    source_info: dict[str, str | None],
    title: str | None = None,
    page_count: int | None = None,
    code_block_count: int | None = None,
    link_count: int | None = None,
) -> dict[str, Any]:
    doc_type = str(validation.get("doc_type"))
    normalized_id = f"norm_{doc_type}_{index:03d}"
    content_cache_alias = f"normalized/{doc_type}/{normalized_id}.txt"
    cache_path = REPO_ROOT / "data" / "knowledge_base" / content_cache_alias
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    normalized_text = _safe_text(text)
    cache_path.write_text(normalized_text + "\n", encoding="utf-8", newline="\n")
    paragraphs = [part for part in re.split(r"\n{2,}", normalized_text) if part.strip()]
    return {
        "normalized_id": normalized_id,
        "sample_id": sample_id,
        "doc_id": doc_id,
        "source_id": source_info["source_id"],
        "doc_type": doc_type,
        "language": source_info["language"],
        "domain": source_info["domain"],
        "title": title or source_info["title"] or f"{doc_type} normalized sample",
        "source_url": source_url,
        "content_cache_alias": content_cache_alias,
        "content_sha256": _sha256_text(normalized_text),
        "content_chars": len(normalized_text),
        "heading_count": len(headings),
        "paragraph_count": len(paragraphs),
        "table_count": validation.get("table_count"),
        "page_count": page_count if page_count is not None else validation.get("page_count"),
        "code_block_count": code_block_count,
        "link_count": link_count,
        "parser": validation.get("parser"),
        "normalizer": "phase6-normalizer-v1",
        "normalization_status": "pass",
        "error_summary": None,
        "created_at": datetime.now(DATETIME_UTC).isoformat(),
    }


def normalize(args: argparse.Namespace) -> list[dict[str, Any]]:
    all_validations = _load_jsonl(PARSER_VALIDATION_PATH)
    validations = [record for record in all_validations if record.get("status") == "pass"]
    samples_by_id = {
        str(record.get("sample_id")): record
        for record in _load_jsonl(SAMPLE_MANIFEST_PATH)
        if record.get("sample_id")
    }
    passed_sample_ids = {
        str(record.get("sample_id"))
        for record in validations
        if record.get("sample_id")
    }
    for sample_id, sample_record in samples_by_id.items():
        if sample_record.get("format") != "html" or sample_id in passed_sample_ids:
            continue
        alias = str(sample_record.get("local_cache_alias") or "")
        if not alias:
            continue
        cache_path = REPO_ROOT / "data" / "knowledge_base" / "raw" / alias
        if not cache_path.exists():
            continue
        validations.append(
            {
                "sample_id": sample_id,
                "doc_type": "html",
                "status": "pass",
                "parser": "html.parser",
                "title_count": None,
                "paragraph_count": None,
                "table_count": None,
                "page_count": None,
                "content_sha256": sample_record.get("content_sha256"),
                "notes": "Recovered from local ignored HTML cache when manifest fetch status is stale.",
            }
        )
    documents_by_hash = _document_by_hash(_load_jsonl(DOCUMENT_MANIFEST_PATH))
    catalog = _load_catalog()
    local_files = _local_file_index(args.course_root, args.max_local_scan_files)
    counters: dict[str, int] = {}
    normalized: list[dict[str, Any]] = []

    for validation in validations:
        doc_type = str(validation.get("doc_type"))
        counters[doc_type] = counters.get(doc_type, 0) + 1
        index = counters[doc_type]
        sample_id = str(validation.get("sample_id") or "")
        source_hash = str(validation.get("content_sha256") or "")
        document_record = documents_by_hash.get(source_hash, {})
        source_id = document_record.get("source_id")
        source_url = None
        doc_id = document_record.get("doc_id")
        headings: list[str] = []
        title: str | None = None
        page_count: int | None = None
        code_block_count: int | None = None
        link_count: int | None = None

        try:
            if doc_type == "docx":
                source_path = local_files[source_hash]
                text, headings = _extract_docx(source_path)
            elif doc_type == "pdf":
                source_path = local_files[source_hash]
                text, page_count = _extract_pdf(source_path)
            elif doc_type == "html":
                sample_record = samples_by_id[sample_id]
                source_id = str(sample_record.get("source_id") or "")
                source_url = str(sample_record.get("source_url") or "")
                alias = str(sample_record.get("local_cache_alias") or "")
                source_path = REPO_ROOT / "data" / "knowledge_base" / "raw" / alias
                text, title, headings, code_block_count, link_count = _extract_html(source_path)
            elif doc_type in {"markdown", "json", "yaml"}:
                source_path, text = _repo_text_sample(doc_type)
                title = f"Repository {doc_type.upper()} sample"
                source_id = "repo_project_files"
                source_url = None
                doc_id = source_path.stem
                if doc_type == "markdown":
                    headings = [
                        line.lstrip("#").strip()
                        for line in text.splitlines()
                        if line.lstrip().startswith("#")
                    ]
            else:
                continue
            if not text.strip():
                continue
            info = _source_info(str(source_id) if source_id else None, catalog)
            normalized.append(
                _record(
                    index=index,
                    validation=validation,
                    source_id=str(source_id) if source_id else None,
                    sample_id=sample_id,
                    doc_id=str(doc_id) if doc_id else None,
                    source_url=source_url,
                    text=text,
                    headings=headings,
                    source_info=info,
                    title=title,
                    page_count=page_count,
                    code_block_count=code_block_count,
                    link_count=link_count,
                )
            )
        except Exception as exc:
            info = _source_info(str(source_id) if source_id else None, catalog)
            normalized_id = f"norm_{doc_type}_{index:03d}"
            normalized.append(
                {
                    "normalized_id": normalized_id,
                    "sample_id": sample_id,
                    "doc_id": str(doc_id) if doc_id else None,
                    "source_id": info["source_id"],
                    "doc_type": doc_type,
                    "language": info["language"],
                    "domain": info["domain"],
                    "title": info["title"],
                    "source_url": source_url,
                    "content_cache_alias": None,
                    "content_sha256": None,
                    "content_chars": 0,
                    "heading_count": validation.get("title_count"),
                    "paragraph_count": validation.get("paragraph_count"),
                    "table_count": validation.get("table_count"),
                    "page_count": validation.get("page_count"),
                    "code_block_count": None,
                    "link_count": None,
                    "parser": validation.get("parser"),
                    "normalizer": "phase6-normalizer-v1",
                    "normalization_status": "fail",
                    "error_summary": f"{type(exc).__name__}: {str(exc)[:200]}",
                    "created_at": datetime.now(DATETIME_UTC).isoformat(),
                }
            )
    return normalized


def main() -> None:
    args = parse_args()
    records = normalize(args)
    _write_jsonl(records, NORMALIZED_MANIFEST_PATH)
    summary = {
        "normalized_record_count": len(records),
        "pass_count": sum(1 for record in records if record["normalization_status"] == "pass"),
        "fail_count": sum(1 for record in records if record["normalization_status"] == "fail"),
        "manifest_path": str(NORMALIZED_MANIFEST_PATH.relative_to(REPO_ROOT)),
        "cache_root": "data/knowledge_base/normalized",
        "cache_is_gitignored": True,
        "writes_chroma": False,
        "calls_embedding": False,
        "calls_llm": False,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))  # noqa: T201


if __name__ == "__main__":
    main()
