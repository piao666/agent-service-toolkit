from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

try:
    import yaml
except ModuleNotFoundError:  # pragma: no cover - exercised when PyYAML is unavailable.
    yaml = None  # type: ignore[assignment]


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG_PATH = (
    REPO_ROOT / "data" / "knowledge_base" / "manifests" / "source_catalog.yaml"
)
WEB_SOURCE_TYPES = {"web_docs"}
PAPER_SOURCE_TYPES = {"paper"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Dry-run source catalog fetch policies without downloading content."
    )
    parser.add_argument("--catalog-path", type=Path, default=DEFAULT_CATALOG_PATH)
    return parser.parse_args()


def _load_catalog(path: Path) -> dict[str, dict[str, Any]]:
    if yaml is None:
        return _load_catalog_without_yaml(path)
    with path.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file) or {}
    if not isinstance(data, dict):
        raise ValueError("source catalog must be a mapping of source_id to source config")
    return data


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
            source_id = line[:-1]
            current_source = {}
            catalog[source_id] = current_source
            current_section = None
            current_list = None
            continue

        if current_source is None:
            raise ValueError("source catalog content appeared before a source_id")

        if indent == 2:
            key, _, value = line.partition(":")
            if not value.strip():
                section: dict[str, Any] = {}
                current_source[key] = section
                current_section = section
                current_list = None
            else:
                current_source[key] = _parse_scalar(value)
                current_section = None
                current_list = None
            continue

        if indent == 4 and current_section is not None:
            key, _, value = line.partition(":")
            if not value.strip():
                values: list[Any] = []
                current_section[key] = values
                current_list = values
            else:
                current_section[key] = _parse_scalar(value)
                current_list = None
            continue

        if indent == 6 and current_list is not None and line.startswith("- "):
            current_list.append(_parse_scalar(line[2:]))
            continue

        raise ValueError(f"Unsupported source catalog line: {raw_line}")

    return catalog


def _valid_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _validate_source(source_id: str, config: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    required_fields = {
        "title",
        "source_type",
        "domain",
        "language",
        "format",
        "entry_url",
        "local_path",
        "license_status",
        "redistribution",
        "priority",
        "fetch_policy",
        "notes",
    }
    missing = sorted(field for field in required_fields if field not in config)
    if missing:
        errors.append(f"missing fields: {', '.join(missing)}")

    fetch_policy = config.get("fetch_policy") or {}
    if not isinstance(fetch_policy, dict):
        return [*errors, "fetch_policy must be an object"]
    for field in ("mode", "max_depth", "max_pages", "include_patterns", "exclude_patterns"):
        if field not in fetch_policy:
            errors.append(f"fetch_policy missing {field}")

    source_type = config.get("source_type")
    entry_url = str(config.get("entry_url") or "")
    if source_type in WEB_SOURCE_TYPES | PAPER_SOURCE_TYPES and not _valid_url(entry_url):
        errors.append("entry_url is not a valid HTTP URL")

    mode = fetch_policy.get("mode")
    if source_type in WEB_SOURCE_TYPES and mode != "sample_only":
        errors.append("web source mode must be sample_only")
    if source_type in PAPER_SOURCE_TYPES:
        if mode != "metadata_only":
            errors.append("paper source mode must be metadata_only")
        if fetch_policy.get("download_pdf") is not False:
            errors.append("paper source download_pdf must be false")

    source_label = source_id.replace("_", "-")
    if any(token in source_label for token in ("company", "role-specific")):
        errors.append("source_id must stay generic")
    return errors


def _source_plan(source_id: str, config: dict[str, Any]) -> dict[str, Any]:
    fetch_policy = config.get("fetch_policy") or {}
    seed_pages = fetch_policy.get("seed_pages") or []
    return {
        "source_id": source_id,
        "source_type": config.get("source_type"),
        "entry_url": config.get("entry_url"),
        "mode": fetch_policy.get("mode"),
        "max_depth": fetch_policy.get("max_depth"),
        "max_pages": fetch_policy.get("max_pages"),
        "seed_pages_count": len(seed_pages),
        "include_patterns": fetch_policy.get("include_patterns") or [],
        "exclude_patterns": fetch_policy.get("exclude_patterns") or [],
        "download_pdf": fetch_policy.get("download_pdf"),
        "validation_errors": _validate_source(source_id, config),
    }


def main() -> None:
    args = parse_args()
    catalog = _load_catalog(args.catalog_path)
    plans = [_source_plan(source_id, config) for source_id, config in catalog.items()]
    web_or_paper_plans = [
        plan
        for plan in plans
        if plan["source_type"] in WEB_SOURCE_TYPES or plan["source_type"] in PAPER_SOURCE_TYPES
    ]
    validation_errors = {
        plan["source_id"]: plan["validation_errors"]
        for plan in plans
        if plan["validation_errors"]
    }
    summary = {
        "catalog_path": str(args.catalog_path.relative_to(REPO_ROOT)),
        "source_count": len(catalog),
        "dry_run": True,
        "downloads_content": False,
        "plans": web_or_paper_plans,
        "validation_errors": validation_errors,
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))  # noqa: T201
    if validation_errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
