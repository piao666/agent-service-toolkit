from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

try:
    from pypdf import PdfReader
except Exception:  # pragma: no cover - optional import guard for script portability.
    PdfReader = None  # type: ignore[assignment]

try:
    from datetime import UTC as DATETIME_UTC
except ImportError:  # pragma: no cover - Python 3.10 compatibility for local script runs.
    from datetime import timezone

    DATETIME_UTC = timezone.utc  # noqa: UP017
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST_PATH = (
    REPO_ROOT / "data" / "knowledge_base" / "manifests" / "document_manifest.jsonl"
)
DEFAULT_SUBDIRS = ("DL", "NLP", "Agent")
SKIP_DIR_NAMES = {".venv", "venv", "env", "site-packages", "__pycache__", ".git"}
EXTENSIONS = {".docx", ".pdf"}


def _default_course_root() -> Path:
    configured_root = os.getenv("COURSE_DOC_ROOT")
    if configured_root:
        return Path(configured_root)
    current_anchor = Path.cwd().anchor
    if current_anchor:
        return Path(current_anchor) / "python"
    return Path("python")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Inspect local course documents and update the document manifest."
    )
    parser.add_argument("--course-root", type=Path, default=_default_course_root())
    parser.add_argument("--manifest-path", type=Path, default=DEFAULT_MANIFEST_PATH)
    parser.add_argument("--subdir", action="append", dest="subdirs", default=None)
    parser.add_argument("--max-files", type=int, default=100)
    return parser.parse_args()


def _is_skipped(path: Path) -> bool:
    return any(part in SKIP_DIR_NAMES for part in path.parts)


def _iter_course_files(course_root: Path, subdirs: list[str], max_files: int) -> list[Path]:
    files: list[Path] = []
    for subdir in subdirs:
        scan_root = course_root / subdir
        if not scan_root.exists():
            continue
        for path in sorted(scan_root.rglob("*")):
            if len(files) >= max_files:
                return files
            if not path.is_file() or _is_skipped(path):
                continue
            if path.suffix.lower() in EXTENSIONS:
                files.append(path)
    return files


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _count_docx_paragraphs(path: Path) -> tuple[int | None, str | None]:
    try:
        with zipfile.ZipFile(path) as archive:
            xml_bytes = archive.read("word/document.xml")
        root = ElementTree.fromstring(xml_bytes)
        namespace = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        return len(root.findall(".//w:p", namespace)), None
    except Exception as exc:
        return None, f"{type(exc).__name__}: {str(exc)[:120]}"


def _count_pdf_pages(path: Path) -> tuple[int | None, str | None]:
    if PdfReader is None:
        return _count_pdf_pages_by_marker(path)
    try:
        reader = PdfReader(str(path))
        return len(reader.pages), None
    except Exception as exc:
        fallback_count, fallback_error = _count_pdf_pages_by_marker(path)
        if fallback_count is not None:
            return fallback_count, None
        return None, fallback_error or f"{type(exc).__name__}: {str(exc)[:120]}"


def _count_pdf_pages_by_marker(path: Path) -> tuple[int | None, str | None]:
    try:
        content = path.read_bytes()
        count = len(re.findall(rb"/Type\s*/Page\b", content))
        if count > 0:
            return count, None
        return None, "PDF page markers were not found"
    except Exception as exc:
        return None, f"{type(exc).__name__}: {str(exc)[:120]}"


def _source_id_for(path: Path, course_root: Path) -> str:
    try:
        first_part = path.relative_to(course_root).parts[0].lower()
    except ValueError:
        first_part = ""
    if first_part == "dl" and path.suffix.lower() == ".docx":
        return "local_deep_learning_course_docx"
    if first_part == "nlp" and path.suffix.lower() == ".docx":
        return "local_nlp_course_docx"
    if first_part == "agent" and path.suffix.lower() == ".pdf":
        return "local_ai_agent_course_pdf"
    return "local_course_material"


def _record_for(path: Path, course_root: Path, index: int) -> dict[str, Any]:
    extension = path.suffix.lower()
    file_hash = _sha256_file(path)
    name_hash = hashlib.sha256(path.name.encode("utf-8")).hexdigest()
    paragraph_count: int | None = None
    page_count: int | None = None
    inspection_errors: list[str] = []
    inspection_notes: list[str] = []

    if extension == ".docx":
        paragraph_count, error = _count_docx_paragraphs(path)
        if error:
            inspection_errors.append(error)
    elif extension == ".pdf":
        page_count, error = _count_pdf_pages(path)
        if error:
            inspection_notes.append(f"pdf_page_count_unavailable: {error}")

    source_id = _source_id_for(path, course_root)
    doc_id = f"{source_id}-{file_hash[:12]}"
    file_alias = f"local_course_doc_{index:03d}{extension}"
    return {
        "doc_id": doc_id,
        "source_id": source_id,
        "source_type": "local_course",
        "domain": source_id.replace("local_", "").replace("_course_docx", ""),
        "language": "zh",
        "format": extension.lstrip("."),
        "file_alias": file_alias,
        "extension": extension,
        "size_bytes": path.stat().st_size,
        "sha256": file_hash,
        "original_file_name_hash": name_hash,
        "local_path_policy": "not_recorded",
        "local_root_alias": "<LOCAL_COURSE_ROOT>",
        "paragraph_count": paragraph_count,
        "page_count": page_count,
        "inspection_status": "ok" if not inspection_errors else "partial",
        "inspection_error": "; ".join(inspection_errors) if inspection_errors else None,
        "inspection_note": "; ".join(inspection_notes) if inspection_notes else None,
        "license_status": "local_use_only",
        "redistribution": "metadata_only",
        "ingested": False,
        "embedding_written": False,
        "chroma_written": False,
        "updated_at": datetime.now(DATETIME_UTC).isoformat(),
    }


def write_manifest(records: list[dict[str, Any]], manifest_path: Path) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    with manifest_path.open("w", encoding="utf-8", newline="\n") as file:
        for record in records:
            file.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def main() -> None:
    args = parse_args()
    course_root = args.course_root
    subdirs = args.subdirs or list(DEFAULT_SUBDIRS)
    files = _iter_course_files(course_root, subdirs, args.max_files)
    records = [_record_for(path, course_root, index) for index, path in enumerate(files, start=1)]
    write_manifest(records, args.manifest_path)

    summary = {
        "course_root_exists": course_root.exists(),
        "course_root_alias": "<LOCAL_COURSE_ROOT>",
        "scanned_subdirs": subdirs,
        "document_count": len(records),
        "manifest_path": str(args.manifest_path.relative_to(REPO_ROOT)),
        "documents": [
            {
                "file_alias": record["file_alias"],
                "extension": record["extension"],
                "size_bytes": record["size_bytes"],
                "sha256": record["sha256"],
                "paragraph_count": record["paragraph_count"],
                "page_count": record["page_count"],
                "inspection_status": record["inspection_status"],
            }
            for record in records
        ],
        "privacy_note": "Original filenames and local absolute paths are not written.",
        "writes_embedding": False,
        "writes_chroma": False,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))  # noqa: T201


if __name__ == "__main__":
    main()
