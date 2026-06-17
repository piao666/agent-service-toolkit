#!/usr/bin/env python3
"""Phase 6F-3: Structured retrieval probe — test metadata/symbol index against 59 bad cases.

不调用 LLM，不写 Chroma，不启动服务。
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
EVAL = ROOT / "data" / "knowledge_base" / "evaluation"

REMAINING_CASES = EVAL / "phase6e_remaining_bad_cases.jsonl"
ROOT_CAUSE = EVAL / "phase6e12_bad_case_root_cause_results.jsonl"
METADATA_INDEX = EVAL / "phase6f_metadata_index.json"
SYMBOL_INDEX = EVAL / "phase6f_symbol_index.json"

OUT_RESULTS = EVAL / "phase6f_structured_retrieval_probe_results.jsonl"
OUT_SUMMARY = EVAL / "phase6f_structured_retrieval_probe_summary.json"


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def main():
    cases = load_jsonl(REMAINING_CASES)
    root_causes = load_jsonl(ROOT_CAUSE)
    meta_idx = json.loads(Path(METADATA_INDEX).read_text(encoding="utf-8")) if METADATA_INDEX.exists() else []
    sym_idx = json.loads(Path(SYMBOL_INDEX).read_text(encoding="utf-8")) if SYMBOL_INDEX.exists() else []

    if not cases:
        print("ERROR: no remaining cases found"); return
    if not meta_idx:
        print("ERROR: metadata index not found — run build_phase6f_metadata_index.py first"); return

    print(f"Cases: {len(cases)}, Metadata entries: {len(meta_idx)}, Symbols: {len(sym_idx)}")

    # ── Build lookup maps ──
    meta_by_source: dict[str, dict] = {e["source_id"]: e for e in meta_idx}
    meta_by_chunk: dict[str, dict] = {}
    for e in meta_idx:
        for cid in e.get("chunk_ids", []):
            meta_by_chunk[cid] = e
    sym_by_source: dict[str, list] = {}
    for s in sym_idx:
        sid = s.get("source_id", "")
        if sid not in sym_by_source:
            sym_by_source[sid] = []
        sym_by_source[sid].append(s)

    # ── Probe each case ──
    results: list[dict[str, Any]] = []
    stats = Counter()
    qt_stats: dict[str, Counter] = {}

    for c in cases:
        cid = c.get("case_id", "?")
        qt = c.get("query_type", "unknown")
        esid = c.get("expected_source_id", "")
        query = c.get("query", "").lower()
        if qt not in qt_stats:
            qt_stats[qt] = Counter()

        meta_hit = False
        sym_hit = False
        citation_hit = False

        # ── Metadata lookup ──
        if esid and esid in meta_by_source:
            meta_hit = True
            stats["metadata_source_hit"] += 1
            qt_stats[qt]["metadata_source_hit"] += 1
        # Also try chunk_id lookup
        for token in query.split():
            if token in meta_by_chunk:
                meta_hit = True
                stats["metadata_chunk_hit"] += 1
                break

        # ── Symbol lookup ──
        if esid and esid in sym_by_source:
            sym_hit = True
            stats["symbol_source_hit"] += 1
            qt_stats[qt]["symbol_source_hit"] += 1

        # ── Citation check ──
        citation_terms = ["引用", "出处", "来源", "cite", "citation", "source", "reference", "证据"]
        if any(t in query for t in citation_terms) and (meta_hit or sym_hit):
            citation_hit = True
            stats["citation_candidate_hit"] += 1

        structured_hit = meta_hit or sym_hit
        if structured_hit:
            stats["structured_hit"] += 1
            qt_stats[qt]["structured_hit"] += 1
        else:
            stats["structured_miss"] += 1
            qt_stats[qt]["structured_miss"] += 1

        results.append({
            "case_id": cid,
            "query_type": qt,
            "expected_source_id": esid,
            "metadata_hit": meta_hit,
            "symbol_hit": sym_hit,
            "citation_candidate_hit": citation_hit,
            "structured_hit": structured_hit,
            "metadata_source_info": meta_by_source.get(esid, {}).get("chunk_count") if esid else None,
        })

    # ── Summary ──
    total = len(cases)
    hit_rate = stats.get("structured_hit", 0) / total if total else 0

    summary = {
        "total_probe_cases": total,
        "metadata_probe_cases": sum(1 for c in cases if c["query_type"] == "exact_metadata_lookup"),
        "symbol_probe_cases": sum(1 for c in cases if c["query_type"] == "code_api_config"),
        "citation_probe_cases": sum(1 for c in cases if c["query_type"] == "citation_required_query"),
        "metadata_source_hit_count": stats.get("metadata_source_hit", 0),
        "symbol_source_hit_count": stats.get("symbol_source_hit", 0),
        "citation_candidate_hit_count": stats.get("citation_candidate_hit", 0),
        "structured_candidate_hit_rate": round(hit_rate, 4),
        "structured_hit_count": stats.get("structured_hit", 0),
        "structured_miss_count": stats.get("structured_miss", 0),
        "by_query_type": {
            qt: {"structured_hit": c.get("structured_hit", 0), "total": sum(c.values())}
            for qt, c in qt_stats.items()
        },
        "expected_gain_area": sorted(
            [qt for qt, c in qt_stats.items() if c.get("structured_hit", 0) > 0],
            key=lambda qt: qt_stats[qt].get("structured_hit", 0), reverse=True,
        ),
        "recommended_hpc_eval": hit_rate >= 0.50,
        "calls_llm": False,
        "writes_chroma": False,
        "starts_service": False,
    }

    # ── Write ──
    with OUT_RESULTS.open("w", encoding="utf-8", newline="\n") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False, sort_keys=True) + "\n")
    with OUT_SUMMARY.open("w", encoding="utf-8", newline="\n") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)

    # ── Print ──
    print(f"\n{'='*55}")
    print(f"Phase 6F-3: Structured Retrieval Probe")
    print(f"  structured_hit_rate: {hit_rate:.1%} ({stats.get('structured_hit',0)}/{total})")
    print(f"  metadata_hits:       {stats.get('metadata_source_hit',0)}")
    print(f"  symbol_hits:         {stats.get('symbol_source_hit',0)}")
    print(f"  citation_hits:       {stats.get('citation_candidate_hit',0)}")
    print(f"  recommended_hpc:     {summary['recommended_hpc_eval']}")
    print(f"  expected_gain:       {summary['expected_gain_area']}")
    print(f"  threshold (>=0.50):  {'PASS' if hit_rate >= 0.50 else 'FAIL'}")

    for qt, c in sorted(qt_stats.items()):
        sh = c.get("structured_hit", 0)
        total_qt = sum(v for k, v in c.items() if k != "total")
        print(f"    {qt:35s}: {sh}/{total_qt} structured_hit")


if __name__ == "__main__":
    main()
