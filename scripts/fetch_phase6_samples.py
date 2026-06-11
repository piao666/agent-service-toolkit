from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

try:
    from datetime import UTC as DATETIME_UTC
except ImportError:  # pragma: no cover - Python 3.10 compatibility.
    DATETIME_UTC = timezone.utc  # noqa: UP017

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover - supports bare Python script runs.
    yaml = None  # type: ignore[assignment]


REPO_ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = REPO_ROOT / "data" / "knowledge_base" / "manifests" / "source_catalog.yaml"
SAMPLE_MANIFEST_PATH = (
    REPO_ROOT / "data" / "knowledge_base" / "manifests" / "sample_manifest.jsonl"
)
RAW_WEB_ROOT = REPO_ROOT / "data" / "knowledge_base" / "raw" / "web_html"
PREFERRED_WEB_SOURCES = (
    "fastapi_docs",
    "pytorch_docs",
    "chroma_docs",
    "langgraph_docs",
    "kubernetes_cn_docs",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch a controlled Phase 6A-2 HTML sample set from seed pages only."
    )
    parser.add_argument("--dry-run", action="store_true", help="Plan samples without downloading.")
    parser.add_argument("--execute", action="store_true", help="Download selected seed page samples.")
    parser.add_argument("--max-total-pages", type=int, default=10)
    parser.add_argument("--max-pages-per-source", type=int, default=2)
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--source", action="append", dest="sources", default=None)
    return parser.parse_args()


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
        raise ValueError(f"Unsupported source catalog line: {raw_line}")
    return catalog


def load_catalog(path: Path = CATALOG_PATH) -> dict[str, dict[str, Any]]:
    if yaml is None:
        return _load_catalog_without_yaml(path)
    with path.open("r", encoding="utf-8") as file:
        loaded = yaml.safe_load(file) or {}
    if not isinstance(loaded, dict):
        raise ValueError("source catalog must be a mapping")
    return loaded


def _selected_sources(
    catalog: dict[str, dict[str, Any]],
    requested_sources: list[str] | None,
) -> list[tuple[str, dict[str, Any]]]:
    source_ids = requested_sources or list(PREFERRED_WEB_SOURCES)
    selected: list[tuple[str, dict[str, Any]]] = []
    for source_id in source_ids:
        config = catalog.get(source_id)
        if not config:
            continue
        fetch_policy = config.get("fetch_policy") or {}
        if config.get("source_type") != "web_docs":
            continue
        if fetch_policy.get("mode") != "sample_only":
            continue
        if fetch_policy.get("seed_pages"):
            selected.append((source_id, config))
    return selected


def _planned_samples(
    catalog: dict[str, dict[str, Any]],
    requested_sources: list[str] | None,
    max_total_pages: int,
    max_pages_per_source: int,
) -> list[tuple[str, int, str]]:
    planned: list[tuple[str, int, str]] = []
    for source_id, config in _selected_sources(catalog, requested_sources):
        fetch_policy = config.get("fetch_policy") or {}
        seed_pages = fetch_policy.get("seed_pages") or []
        source_limit = min(int(fetch_policy.get("max_pages") or 0), max_pages_per_source)
        for source_index, source_url in enumerate(seed_pages[:source_limit], start=1):
            if len(planned) >= max_total_pages:
                return planned
            planned.append((source_id, source_index, str(source_url)))
    return planned


def _error_summary(exc: Exception) -> tuple[str, str]:
    error_type = type(exc).__name__
    summary = str(exc).replace("\n", " ").strip()
    return error_type, summary[:240]


def _fetch_url(url: str, timeout: int) -> bytes:
    request = Request(
        url,
        headers={
            "User-Agent": "enterprise-rag-backend-sample-fetch/1.0",
            "Accept": "text/html,application/xhtml+xml",
        },
    )
    with urlopen(request, timeout=timeout) as response:  # noqa: S310
        content_type = response.headers.get("content-type", "")
        if "html" not in content_type:
            raise ValueError(f"Unexpected content type: {content_type}")
        return response.read()


def _record(
    *,
    source_id: str,
    source_index: int,
    source_url: str,
    execute: bool,
    timeout: int,
) -> dict[str, Any]:
    sample_id = f"sample_{source_id}_{source_index:03d}"
    local_alias = f"web_html/{source_id}/sample_{source_index:03d}.html"
    cache_path = RAW_WEB_ROOT / source_id / f"sample_{source_index:03d}.html"
    fetched_at = datetime.now(DATETIME_UTC).isoformat()
    base_record: dict[str, Any] = {
        "sample_id": sample_id,
        "source_id": source_id,
        "source_url": source_url,
        "format": "html",
        "local_cache_alias": local_alias,
        "content_sha256": None,
        "size_bytes": 0,
        "fetched_at": fetched_at,
        "fetch_status": "dry_run",
        "error_type": None,
        "error_summary": None,
        "redistribution": "local_cache_only",
    }
    if not execute:
        return base_record
    try:
        content = _fetch_url(source_url, timeout=timeout)
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_bytes(content)
        return {
            **base_record,
            "content_sha256": hashlib.sha256(content).hexdigest(),
            "size_bytes": len(content),
            "fetch_status": "ok",
        }
    except (HTTPError, URLError, TimeoutError, ValueError) as exc:
        error_type, summary = _error_summary(exc)
        return {
            **base_record,
            "fetch_status": "fail",
            "error_type": error_type,
            "error_summary": summary,
        }


def write_manifest(records: list[dict[str, Any]], path: Path = SAMPLE_MANIFEST_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as file:
        for record in records:
            file.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def main() -> None:
    args = parse_args()
    execute = bool(args.execute)
    if args.dry_run:
        execute = False

    catalog = load_catalog()
    planned = _planned_samples(
        catalog=catalog,
        requested_sources=args.sources,
        max_total_pages=args.max_total_pages,
        max_pages_per_source=args.max_pages_per_source,
    )
    records = [
        _record(
            source_id=source_id,
            source_index=source_index,
            source_url=source_url,
            execute=execute,
            timeout=args.timeout,
        )
        for source_id, source_index, source_url in planned
    ]
    write_manifest(records)
    summary = {
        "execute": execute,
        "dry_run": not execute,
        "planned_count": len(planned),
        "ok_count": sum(1 for record in records if record["fetch_status"] == "ok"),
        "fail_count": sum(1 for record in records if record["fetch_status"] == "fail"),
        "manifest_path": str(SAMPLE_MANIFEST_PATH.relative_to(REPO_ROOT)),
        "downloads_are_gitignored": True,
        "writes_chroma": False,
        "calls_embedding": False,
        "calls_llm": False,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))  # noqa: T201


if __name__ == "__main__":
    main()
