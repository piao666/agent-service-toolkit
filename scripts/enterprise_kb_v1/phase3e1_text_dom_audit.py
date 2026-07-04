#!/usr/bin/env python3
"""Phase 3E1 Text/DOM Evidence-Driven Audit.
Reads raw.html + normalized.md for 3 samples, produces canonical audit.json.
Python stdlib only. No shell grep. Operator checking with exact token boundaries.
Table counting: HTML <table> tags + Markdown table blocks (code-fence aware)."""

import json, re, os, html as html_mod
from pathlib import Path
from html.parser import HTMLParser


class TableTagCounter(HTMLParser):
    """Counts real <table> tags in HTML."""
    def __init__(self):
        super().__init__()
        self.table_count = 0
    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self.table_count += 1


def count_html_tables(raw_html):
    counter = TableTagCounter()
    counter.feed(raw_html)
    return counter.table_count


def count_markdown_table_blocks(body):
    """Count valid Markdown table blocks. Table = header row + separator row + at least 1 data row.
    A separator row matches: |---|...---| or ---|---|... (pipes optional at edges).
    Code-fence aware: ignores separators inside fenced code blocks."""
    lines = body.split("\n")
    tables = 0
    backtick_count = 0
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("```"):
            backtick_count += 1
            continue
        if backtick_count % 2 == 1:
            continue
        # Separator row: cells like ---, :---, ---:, :---: separated by |
        # Pattern: optional leading |, then one or more |-: cells separated by |, optional trailing |
        if re.match(r'^\|?\s*[-:]+(\s*\|\s*[-:]+\s*)+\|?\s*$', stripped):
            prev = lines[i-1].strip() if i > 0 else ""
            nxt = lines[i+1].strip() if i+1 < len(lines) else ""
            if "|" in prev and "|" in nxt:
                tables += 1
    return tables

SAMPLES = [
    {"sample_id": "S1", "source_id": "fastapi_official_middleware",
     "origin_url": "https://fastapi.tiangolo.com/tutorial/middleware/"},
    {"sample_id": "S2", "source_id": "chroma_official_metadata_filter",
     "origin_url": "https://docs.trychroma.com/docs/querying-collections/metadata-filtering"},
    {"sample_id": "S3", "source_id": "langgraph_official_stategraph",
     "origin_url": "https://docs.langchain.com/oss/python/langgraph/graph-api"},
]

BASE = Path("data/enterprise_kb_v1/experiments/phase3d_multimodal/text_dom")
MANIFEST_DIR = Path("data/enterprise_kb_v1/manifests")

# ── Operators (Python literal list, no shell interpolation) ──
OPERATORS = ["$eq", "$ne", "$gt", "$lt", "$gte", "$lte", "$in", "$nin", "$and", "$or", "$contains", "$not_contains"]

def check_operator(op, text_raw, text_unescaped):
    """Check an operator in text with exact token boundary matching.
    Uses re.escape to avoid $ being treated as regex anchor.
    Boundary: op must not be preceded/followed by [A-Za-z0-9_$]."""
    pattern = re.compile(r'(?<![A-Za-z0-9_$])' + re.escape(op) + r'(?![A-Za-z0-9_])')
    # raw (unescaped HTML):
    raw_match = bool(pattern.search(text_unescaped))
    # substring in raw HTML (for debugging):
    raw_sub = op in text_raw
    return {"substring_present": raw_sub, "exact_token_present": raw_match}

def check_operator_in_md(op, md_text):
    """Same check on normalized markdown."""
    pattern = re.compile(r'(?<![A-Za-z0-9_$])' + re.escape(op) + r'(?![A-Za-z0-9_])')
    md_match = bool(pattern.search(md_text))
    md_sub = op in md_text
    return {"substring_present": md_sub, "exact_token_present": md_match}

def extract_front_matter(md):
    """Extract front matter block. Returns (present, fm_dict, body_start)."""
    if not md.startswith("---"):
        return False, {}, 0
    end = md.find("---", 3)
    if end < 0:
        return False, {}, 0
    fm_text = md[3:end].strip()
    fm = {}
    for line in fm_text.split("\n"):
        if ":" in line:
            k, v = line.split(":", 1)
            fm[k.strip()] = v.strip()
    return True, fm, end + 3

def count_headings(body):
    """Count headings by level. Skips front matter."""
    h = {"h1": 0, "h2": 0, "h3": 0, "h4": 0, "h5": 0, "h6": 0}
    for line in body.split("\n"):
        m = re.match(r'^(#{1,6})\s+', line)
        if m:
            level = len(m.group(1))
            h[f"h{level}"] += 1
    return h

def count_empty_headings(body):
    """Count empty heading markers (### with nothing after)."""
    return len(re.findall(r'^(#{1,6})\s*$', body, re.MULTILINE))

def count_zero_width_empty_headings(md):
    """Count headings with ONLY zero-width/non-printing chars after the markers."""
    count = 0
    for line in md.split("\n"):
        m = re.match(r'^(#{1,6})(.*)$', line)
        if m:
            rest = m.group(2)
            # If rest is empty or only zero-width/invisible chars:
            stripped = rest
            for ch in ['​', '‌', '‍', '﻿', '­', ' ']:
                stripped = stripped.replace(ch, '')
            if stripped == '' and rest != '':
                count += 1
            elif rest.strip() == '':
                count += 1
    return count

def audit():
    results = []
    for s in SAMPLES:
        sid = s["sample_id"]
        d = BASE / sid

        raw_html_path = d / "raw.html"
        normalized_md_path = d / "normalized.md"

        if not raw_html_path.exists() or not normalized_md_path.exists():
            print(f"FATAL: {sid} missing raw.html or normalized.md")
            results.append({"sample_id": sid, "audit_pass": False, "audit_fail_reasons": ["missing_input"]})
            continue

        raw_html = raw_html_path.read_text(encoding="utf-8")
        normalized_md = normalized_md_path.read_text(encoding="utf-8")
        raw_unescaped = html_mod.unescape(raw_html)

        html_size = len(raw_html.encode("utf-8"))
        md_size = len(normalized_md.encode("utf-8"))

        # ── Front matter ──
        fm_present, fm_dict, body_start = extract_front_matter(normalized_md)
        body = normalized_md[body_start:] if fm_present else normalized_md

        # ── Heading stats ──
        headings = count_headings(body)
        total_h = sum(headings.values())
        empty_h = count_empty_headings(body)
        zw_empty_h = count_zero_width_empty_headings(normalized_md)

        # ── Code blocks ──
        fenced_code = body.count("```text")
        legacy_code_tags = body.count("[code]") + body.count("[/code]")

        # ── Table count from evidence ──
        raw_table_count = count_html_tables(raw_html)
        md_table_count = count_markdown_table_blocks(body)
        table_count = md_table_count  # canonical: markdown table blocks

        # ── Links ──
        links = len(re.findall(r'\[([^\]]+)\]\(([^)]+)\)', body))

        # ── Operator check (S2 only) ──
        op_check = {}
        if sid == "S2":
            for op in OPERATORS:
                raw_check = check_operator(op, raw_html, raw_unescaped)
                md_check = check_operator_in_md(op, normalized_md)
                op_check[op] = {
                    "raw_html_substring": raw_check["substring_present"],
                    "raw_html_exact_token": raw_check["exact_token_present"],
                    "normalized_md_substring": md_check["substring_present"],
                    "normalized_md_exact_token": md_check["exact_token_present"],
                }

        # ── Format checks ──
        format_ok = True
        format_issues = []
        if not fm_present:
            format_issues.append("front_matter_missing")
            format_ok = False
        if legacy_code_tags > 0:
            format_issues.append(f"legacy_code_tags={legacy_code_tags}")
            format_ok = False
        if empty_h > 0:
            format_issues.append(f"empty_headings={empty_h}")
            format_ok = False
        if zw_empty_h > 0:
            format_issues.append(f"zero_width_empty_headings={zw_empty_h}")
            format_ok = False

        # ── Extraction warnings per sample ──
        warnings = []
        if sid == "S2":
            # Check raw→md operator loss
            for op in OPERATORS:
                oc = op_check[op]
                if oc["raw_html_exact_token"] and not oc["normalized_md_exact_token"]:
                    warnings.append(f"S2: {op} present in raw.html but missing from normalized.md — extraction loss")
                elif not oc["raw_html_exact_token"] and not oc["normalized_md_exact_token"]:
                    warnings.append(f"S2: {op} not present in captured page content (raw or md)")

        # ── Quality status ──
        if not format_ok:
            quality = "fail"
        elif sid == "S2" and any("extraction loss" in w for w in warnings):
            quality = "partial"
        else:
            quality = "pass"

        # ── Audit pass/fail ──
        fail_reasons = list(format_issues)
        if sid == "S2":
            # Hard fail if any operator key is empty
            for k in op_check:
                if not k or k.strip() == "":
                    fail_reasons.append("empty_operator_key")
                    break

        audit_pass = len(fail_reasons) == 0 and quality != "fail"

        result = {
            "sample_id": sid,
            "source_id": s["source_id"],
            "origin_url": s["origin_url"],
            "raw_html_path": str(raw_html_path),
            "normalized_md_path": str(normalized_md_path),
            "html_size_bytes": html_size,
            "markdown_size_bytes": md_size,
            "front_matter_present": fm_present,
            "heading_count_by_level": headings,
            "heading_count_total": total_h,
            "empty_heading_count": empty_h,
            "zero_width_empty_heading_count": zw_empty_h,
            "code_block_count": fenced_code,
            "legacy_code_tag_count": legacy_code_tags,
            "raw_html_table_count": raw_table_count,
            "markdown_table_block_count": md_table_count,
            "table_count": table_count,
            "link_count": links,
            "operator_check": op_check if sid == "S2" else None,
            "format_checks": {
                "front_matter_ok": fm_present,
                "no_legacy_code_tags": legacy_code_tags == 0,
                "no_empty_headings": empty_h == 0,
                "no_zero_width_headings": zw_empty_h == 0,
            },
            "quality_status": quality,
            "extraction_warnings": warnings,
            "audit_pass": audit_pass,
            "audit_fail_reasons": fail_reasons,
        }
        results.append(result)

    # ── Write audit.json ──
    audit_doc = {
        "audit_version": "1.0.0",
        "audit_generated_at": "2026-07-04T21:00:00+08:00",
        "audit_method": "python_stdlib_exact_token_boundary",
        "operator_list": OPERATORS,
        "samples": results,
    }
    MANIFEST_DIR.mkdir(parents=True, exist_ok=True)
    audit_path = MANIFEST_DIR / "phase3e1_text_dom_audit.json"
    with open(audit_path, "w", encoding="utf-8") as f:
        json.dump(audit_doc, f, ensure_ascii=False, indent=2)
    print(f"Audit written: {audit_path}")

    # Summary
    for r in results:
        h = r["heading_count_total"]
        c = r["code_block_count"]
        t = r["table_count"]
        print(f"{r['sample_id']}: h={h} code={c} tables={t} quality={r['quality_status']} audit_pass={r['audit_pass']} warnings={len(r['extraction_warnings'])}")
        if r.get("operator_check"):
            for op in OPERATORS:
                oc = r["operator_check"][op]
                print(f"  {op}: raw_exact={oc['raw_html_exact_token']} md_exact={oc['normalized_md_exact_token']}")

if __name__ == "__main__":
    audit()
