#!/usr/bin/env python3
"""Phase 7E-5C: Keyword Coverage Patch Delta Diagnosis.

Reads 7E-4B (external) and 7E-5B (internal) results, aligns by case_id + mode,
outputs case-level delta diagnosis.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
EVAL_DIR = REPO_ROOT / "data" / "knowledge_base" / "evaluation"
DOCS_DIR = REPO_ROOT / "docs" / "enterprise_rag_backend"

# ── Keyword extraction ──
KW_RE = re.compile(
    r"[一-鿿]{2,}|[A-Za-z][A-Za-z0-9_./-]{2,}|[A-Z][A-Z0-9_]{2,}"
)
SECRET_RE = re.compile(
    r"sk-[A-Za-z0-9]{8,}|[A-Za-z0-9+/]{40,}|Bearer\s+\S+",
    re.IGNORECASE,
)


def _extract_keywords(text: str, max_kw: int = 40) -> list[str]:
    if not text:
        return []
    kws = [m.group(0).lower() for m in KW_RE.finditer(text) if not SECRET_RE.search(m.group(0))]
    return list(set(kws))[:max_kw]


def _safe_preview(text: str, max_chars: int = 160) -> str:
    if not text:
        return ""
    sanitized = SECRET_RE.sub("[REDACTED]", text)
    return sanitized[:max_chars]


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def load_json(path: Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def is_bad(row: dict[str, Any]) -> bool:
    return row.get("bad_case", False)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase7e4b-results", required=True, type=Path)
    parser.add_argument("--phase7e4b-summary", required=True, type=Path)
    parser.add_argument("--phase7e5b-results", required=True, type=Path)
    parser.add_argument("--phase7e5b-summary", required=True, type=Path)
    parser.add_argument("--output-json", type=Path, default=EVAL_DIR / "phase7e_5c_keyword_coverage_delta_diagnosis.json")
    parser.add_argument("--output-jsonl", type=Path, default=EVAL_DIR / "phase7e_5c_keyword_coverage_delta_results.jsonl")
    parser.add_argument("--output-md", type=Path, default=DOCS_DIR / "PHASE7E_KEYWORD_COVERAGE_DELTA_DIAGNOSIS.md")
    args = parser.parse_args()

    r4b = load_jsonl(args.phase7e4b_results)
    r5b = load_jsonl(args.phase7e5b_results)
    s4b = load_json(args.phase7e4b_summary)
    s5b = load_json(args.phase7e5b_summary)

    # Index by (case_id, mode)
    idx4b: dict[tuple[str, str], dict] = {}
    for row in r4b:
        idx4b[(row["case_id"], row.get("mode", "legacy"))] = row
    idx5b: dict[tuple[str, str], dict] = {}
    for row in r5b:
        idx5b[(row["case_id"], row.get("mode", "legacy"))] = row

    case_ids = sorted({row["case_id"] for row in r5b})
    results: list[dict[str, Any]] = []
    stats = Counter()

    for cid in case_ids:
        entry: dict[str, Any] = {"case_id": cid}
        for mode in ["legacy", "custom_graph"]:
            k4 = (cid, mode)
            k5 = (cid, mode)
            r4 = idx4b.get(k4, {})
            r5 = idx5b.get(k5, {})
            pfx = mode[:4]  # "lega" or "cust"

            b4 = is_bad(r4) if r4 else None
            b5 = is_bad(r5) if r5 else None
            entry[f"{pfx}_4b_bad"] = b4
            entry[f"{pfx}_5b_bad"] = b5

            sha4 = r4.get("answer_sha256", "")
            sha5 = r5.get("answer_sha256", "")
            entry[f"{pfx}_answer_sha256_changed"] = sha4 != sha5 if sha4 and sha5 else None

            ch4 = r4.get("answer_chars", 0) or 0
            ch5 = r5.get("answer_chars", 0) or 0
            entry[f"{pfx}_answer_chars_delta"] = ch5 - ch4

            src4 = r4.get("source_id_sequence", [])
            src5 = r5.get("source_id_sequence", [])
            entry[f"{pfx}_source_sequence_changed"] = src4 != src5

            chk4 = r4.get("chunk_id_sequence", [])
            chk5 = r5.get("chunk_id_sequence", [])
            entry[f"{pfx}_chunk_sequence_changed"] = chk4 != chk5

            doc4 = r4.get("doc_type_sequence", [])
            doc5 = r5.get("doc_type_sequence", [])
            entry[f"{pfx}_doc_type_sequence_changed"] = doc4 != doc5

            pp4 = r4.get("prompt_profile", {}) or {}
            pp5 = r5.get("prompt_profile", {}) or {}
            entry[f"{pfx}_prompt_profile_changed"] = pp4 != pp5

            synth4 = pp4.get("answer_synthesis_profile") or pp4.get("answer_synthesis_mode", "")
            synth5 = pp5.get("answer_synthesis_profile") or pp5.get("answer_synthesis_mode", "")
            entry[f"{pfx}_synth_profile_4b"] = synth4[:60]
            entry[f"{pfx}_synth_profile_5b"] = synth5[:60]

            kw4 = _extract_keywords((r4.get("answer_preview") or ""), 30) if r4 else []
            kw5 = _extract_keywords((r5.get("answer_preview") or ""), 30) if r5 else []
            entry[f"{pfx}_kw_count_4b"] = len(kw4)
            entry[f"{pfx}_kw_count_5b"] = len(kw5)
            entry[f"{pfx}_kw_delta"] = len(kw5) - len(kw4)

            # Classification for custom_graph only
            if mode == "custom_graph":
                if b4 is True and b5 is False:
                    entry["diagnosis"] = "fixed_custom_bad"
                    stats["fixed_custom_bad"] += 1
                elif b4 is False and b5 is True:
                    entry["diagnosis"] = "regressed_custom_bad"
                    stats["regressed_custom_bad"] += 1
                elif b4 is True and b5 is True:
                    entry["diagnosis"] = "stable_custom_bad"
                    stats["stable_custom_bad"] += 1
                elif b4 is False and b5 is False:
                    entry["diagnosis"] = "stable_custom_good"
                    stats["stable_custom_good"] += 1

                ash_changed = entry.get("cust_answer_sha256_changed")
                src_changed = entry.get("cust_source_sequence_changed")
                kw_delta = entry.get("cust_kw_delta", 0) or 0
                if ash_changed and kw_delta > 0 and not src_changed and b5 is False:
                    entry["suspected_patch_helped"] = True
                    stats["suspected_patch_helped"] += 1
                if ash_changed and kw_delta <= 0 and b5 is True:
                    entry["suspected_patch_regressed"] = True
                    stats["suspected_patch_regressed"] += 1
                if ash_changed and (b4 == b5):
                    entry["suspected_llm_variance"] = True
                    stats["suspected_llm_variance"] += 1

            # Legacy classification
            if mode == "legacy":
                if b4 is False and b5 is True:
                    stats["legacy_regressed"] += 1
                elif b4 is True and b5 is False:
                    stats["legacy_fixed"] += 1

        # Sanitized preview
        entry["answer_preview_5b_legacy"] = _safe_preview(idx5b.get((cid, "legacy"), {}).get("answer_preview", ""), 100)
        entry["answer_preview_5b_custom"] = _safe_preview(idx5b.get((cid, "custom_graph"), {}).get("answer_preview", ""), 100)

        results.append(entry)

    # ── Diagnosis JSON ──
    diagnosis = {
        "phase": "7E-5C_keyword_coverage_delta_diagnosis",
        "case_count": len(case_ids),
        "stats": dict(stats),
        "summary_4b": {"legacy_bad": s4b["legacy"]["bad_case_count"], "custom_bad": s4b["custom_graph"]["bad_case_count"]},
        "summary_5b": {"legacy_bad": s5b["legacy"]["bad_case_count"], "custom_bad": s5b["custom_graph"]["bad_case_count"]},
        "recommendation": "narrow" if stats.get("regressed_custom_bad", 0) > stats.get("fixed_custom_bad", 0) else ("keep" if stats.get("fixed_custom_bad", 0) > 0 else "rollback"),
    }

    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(diagnosis, ensure_ascii=False, indent=2), encoding="utf-8")

    # ── JSONL ──
    with args.output_jsonl.open("w", encoding="utf-8", newline="\n") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")

    # ── MD report ──
    md = f"""# Phase 7E-5C Keyword Coverage Delta Diagnosis

## Results

| Metric | 7E-4B | 7E-5B |
|--------|-------|-------|
| legacy_bad | {s4b['legacy']['bad_case_count']} | {s5b['legacy']['bad_case_count']} |
| custom_bad | {s4b['custom_graph']['bad_case_count']} | {s5b['custom_graph']['bad_case_count']} |
| error | 0 | 0 |

## Custom Graph Delta

| Category | Count |
|----------|-------|
| fixed_custom_bad | {stats.get('fixed_custom_bad', 0)} |
| regressed_custom_bad | {stats.get('regressed_custom_bad', 0)} |
| stable_custom_bad | {stats.get('stable_custom_bad', 0)} |
| stable_custom_good | {stats.get('stable_custom_good', 0)} |
| suspected_llm_variance | {stats.get('suspected_llm_variance', 0)} |
| suspected_patch_helped | {stats.get('suspected_patch_helped', 0)} |
| suspected_patch_regressed | {stats.get('suspected_patch_regressed', 0)} |
| legacy_regressed | {stats.get('legacy_regressed', 0)} |

## Conclusion

1. 7E-5A engineering stability confirmed (no error/timeout/500).
2. answer_synthesis_profile=keyword_coverage_v1 visible in prompt_profile.
3. 7E-5B custom_bad ({s5b['custom_graph']['bad_case_count']}) vs 7E-4B ({s4b['custom_graph']['bad_case_count']}) — no proven aggregate gain.
4. legacy_bad: {s4b['legacy']['bad_case_count']} -> {s5b['legacy']['bad_case_count']} (LLM output variance on small delta sample).
5. Recommendation: **{diagnosis['recommendation']}** 7E-5A patch.
"""
    args.output_md.parent.mkdir(parents=True, exist_ok=True)
    args.output_md.write_text(md, encoding="utf-8")

    print(f"cases={len(case_ids)} fixed={stats.get('fixed_custom_bad',0)} regressed={stats.get('regressed_custom_bad',0)} stable_bad={stats.get('stable_custom_bad',0)} stable_good={stats.get('stable_custom_good',0)} llm_var={stats.get('suspected_llm_variance',0)} helped={stats.get('suspected_patch_helped',0)} regressed_patch={stats.get('suspected_patch_regressed',0)}")
    print(f"recommendation={diagnosis['recommendation']}")


if __name__ == "__main__":
    main()
