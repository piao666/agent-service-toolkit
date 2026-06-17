#!/usr/bin/env python3
"""Phase 6F-2: Build code/config symbol index from chunk_manifest.jsonl.

Extract symbols via regex: API paths, filenames, function names, env vars, config keys.
不保存完整 chunk 正文，不调用 LLM，不调用 embedding，不写 Chroma。
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "data" / "knowledge_base" / "manifests" / "chunk_manifest.jsonl"
EVAL = ROOT / "data" / "knowledge_base" / "evaluation"
OUT_INDEX = EVAL / "phase6f_symbol_index.json"
OUT_SUMMARY = EVAL / "phase6f_symbol_index_summary.json"

# ── Symbol extraction patterns ──
SYMBOL_PATTERNS = {
    "env_var": re.compile(r"\b[A-Z][A-Z0-9_]{3,}\b"),  # UPPER_CASE env vars
    "filename_py": re.compile(r"\b[\w_]+\.py\b"),
    "filename_json": re.compile(r"\b[\w_\-]+\.json\b"),
    "filename_yaml": re.compile(r"\b[\w_\-]+\.ya?ml\b"),
    "filename_toml": re.compile(r"\b[\w_\-]+\.toml\b"),
    "filename_md": re.compile(r"\b[\w_\-]+\.md\b"),
    "api_path": re.compile(r"/(?:api|v\d+|enterprise|agent|invoke|health|info|stream|history|feedback)(?:/[\w_{}]+)*"),
    "http_method": re.compile(r"\b(GET|POST|PUT|DELETE|PATCH|OPTIONS|HEAD)\b"),
    "function_call": re.compile(r"\b([\w_]+)\s*\((.*?)\)"),  # func_name(args)
    "class_def": re.compile(r"\bclass\s+(\w+)"),
    "config_key": re.compile(r"\b([\w_]+)\s*[:=]\s*['\"]?[\w/\-\.]+['\"]?"),
    "number_version": re.compile(r"\b(\d+\.\d+(?:\.\d+)?)\b"),
    "import_stmt": re.compile(r"\b(?:from|import)\s+([\w.]+)"),
    "port_number": re.compile(r"\b(?:port|PORT)\s*[:=]?\s*(\d{2,5})\b"),
}
PREVIEW_LEN = 300


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def extract_symbols(text: str, source_id: str, chunk_id: str, title: str, section: str) -> list[dict[str, Any]]:
    """Extract symbols from a text block."""
    symbols: list[dict[str, Any]] = []
    seen: set[str] = set()

    for sym_type, pattern in SYMBOL_PATTERNS.items():
        for match in pattern.finditer(text):
            value = match.group(0).strip()
            if sym_type == "function_call":
                value = match.group(1)  # function name only
            elif sym_type == "class_def":
                value = match.group(1)
            elif sym_type == "import_stmt":
                value = match.group(1)
            elif sym_type == "number_version":
                value = match.group(1)

            key = f"{sym_type}:{value}"
            if key in seen:
                continue
            seen.add(key)

            symbols.append({
                "symbol_type": sym_type,
                "value": value[:120],
                "source_id": source_id,
                "chunk_id": chunk_id,
                "title": title,
                "section_path": section,
            })
    return symbols


def main():
    chunks = load_jsonl(MANIFEST_PATH)
    print(f"Loaded {len(chunks)} chunks")

    all_symbols: list[dict[str, Any]] = []
    sym_type_dist: Counter = Counter()
    chunks_with_sym = 0

    for c in chunks:
        sid = c.get("source_id", "")
        cid = c.get("chunk_id", "")
        title = c.get("title", "")
        sp = c.get("section_path", "")
        if isinstance(sp, list):
            sp = " ".join(s for s in sp if s)

        # Scan: preview, title, section_path
        text = " ".join(filter(None, [
            c.get("content_preview") or c.get("text") or "",
            title, sp,
        ]))[:2000]

        syms = extract_symbols(text, sid, cid, title, sp)
        if syms:
            chunks_with_sym += 1
            all_symbols.extend(syms)
            for s in syms:
                sym_type_dist[s["symbol_type"]] += 1

    # ── Deduplicate by symbol value ──
    deduped: dict[str, dict[str, Any]] = {}
    for s in all_symbols:
        key = f"{s['symbol_type']}:{s['value']}"
        if key not in deduped:
            deduped[key] = s
        else:
            # Append additional source_id if different
            existing_sids = deduped[key].get("source_ids", [deduped[key]["source_id"]])
            if s["source_id"] not in existing_sids:
                existing_sids.append(s["source_id"])
            deduped[key]["source_ids"] = existing_sids

    result = sorted(deduped.values(), key=lambda x: f"{x['symbol_type']}:{x['value']}")

    # ── Write index ──
    with OUT_INDEX.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    # ── Summary ──
    summary = {
        "total_chunks_scanned": len(chunks),
        "total_symbols": len(all_symbols),
        "total_unique_symbols": len(result),
        "symbol_type_distribution": dict(sym_type_dist),
        "chunks_with_symbols_count": chunks_with_sym,
        "code_config_index_ready": len(result) > 0,
        "calls_llm": False,
        "writes_chroma": False,
        "top_symbols_by_type": {
            st: sorted(
                [s["value"] for s in result if s["symbol_type"] == st],
                key=lambda v: sum(1 for x in result if x["symbol_type"] == st and x["value"] == v),
                reverse=True,
            )[:10]
            for st in list(sym_type_dist)[:8]
        },
    }

    with OUT_SUMMARY.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    print(f"  Chunks scanned:       {len(chunks)}")
    print(f"  Chunks with symbols:  {chunks_with_sym}")
    print(f"  Total symbols:        {len(all_symbols)}")
    print(f"  Unique symbols:       {len(result)}")
    print(f"  Symbol distribution:  {dict(sym_type_dist.most_common(10))}")
    print(f"  Ready:                {summary['code_config_index_ready']}")
    print(f"  Output:               {OUT_INDEX}")
    print(f"  Summary:              {OUT_SUMMARY}")


if __name__ == "__main__":
    main()
