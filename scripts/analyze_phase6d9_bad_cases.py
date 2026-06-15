#!/usr/bin/env python3
"""Phase 6D-9: Bad Case Taxonomy + Evaluation Calibration.

重新计算 DeepSeek/Qwen 240-case bad cases 时，应用校准后的 metric:
- negative_banned_source: 不要求 source_hit/doc_type_hit
- ambiguous_query: 不要求 source_hit
- multi_hop_lookup / citation_required_query: 放宽 doc_type_hit
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
EVAL_DIR = ROOT_DIR / "data" / "knowledge_base" / "evaluation"

# ── 校准规则 ──
CALIBRATION = {
    "negative_banned_source": {
        "skip_source_hit": True,
        "skip_doc_type_hit": True,
        "reason": "负向测试不应要求 source/doc_type 命中；成功标准是 banned_source_returned=False",
    },
    "ambiguous_query": {
        "skip_source_hit": True,
        "skip_doc_type_hit": False,
        "reason": "模糊查询不应强制单一 expected_source_id；keyword_hit 仍应检查",
    },
    "multi_hop_lookup": {
        "skip_source_hit": False,
        "skip_doc_type_hit": True,
        "reason": "跨文档查询可能返回多种 doc_type；放宽 doc_type 检查",
    },
    "citation_required_query": {
        "skip_source_hit": False,
        "skip_doc_type_hit": True,
        "reason": "引用查询可接受不同格式来源；放宽 doc_type 检查",
    },
}


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def is_bad_raw(result: dict[str, Any]) -> bool:
    """原始 bad case 判定: source_hit + doc_type_hit + keyword_hit 全为 True。"""
    return not (result.get("source_hit") and result.get("doc_type_hit") and result.get("keyword_hit"))


def is_bad_calibrated(result: dict[str, Any]) -> bool:
    """校准后的 bad case 判定，根据 query_type 调整指标要求。"""
    qt = result.get("query_type", "")
    cal = CALIBRATION.get(qt, {})

    checks = []
    if not cal.get("skip_source_hit"):
        checks.append(result.get("source_hit", False))
    if not cal.get("skip_doc_type_hit"):
        checks.append(result.get("doc_type_hit", False))
    if "keyword_hit" in result:  # always check keyword
        checks.append(result.get("keyword_hit", False))

    return not all(checks) if checks else False


def classify_failure(result: dict[str, Any]) -> str:
    """分类失败类型。"""
    qt = result.get("query_type", "unknown")
    if qt == "negative_banned_source":
        if result.get("banned_source_returned"):
            return "banned_source_leaked"
        return "metric_unfair_negative"
    if qt == "ambiguous_query":
        if not result.get("keyword_hit"):
            return "ambiguous_no_evidence"
        return "metric_unfair_ambiguous"
    if qt == "exact_metadata_lookup" and not result.get("source_hit"):
        return "exact_metadata_retrieval_fail"
    if qt == "multi_hop_lookup" and not result.get("keyword_hit"):
        return "multi_hop_incomplete"
    if qt == "citation_required_query" and not result.get("keyword_hit"):
        return "citation_evidence_missing"
    if not result.get("source_hit"):
        return "retrieval_miss"
    if not result.get("keyword_hit"):
        return "keyword_missing"
    if not result.get("doc_type_hit"):
        return "doc_type_mismatch"
    return "other"


def main() -> None:
    for provider in ["deepseek", "qwen"]:
        results_path = EVAL_DIR / f"phase6d8_{provider}_agent_api_results.jsonl"
        if not results_path.exists():
            continue

        results = load_jsonl(results_path)

        # ── 原始 vs 校准对比 ──
        raw_bad = [r for r in results if is_bad_raw(r)]
        calibrated_bad = [r for r in results if is_bad_calibrated(r)]
        removed_by_cal = [r for r in raw_bad if not is_bad_calibrated(r)]

        # ── Taxonomies ──
        raw_tax: list[dict[str, Any]] = []
        cal_tax: list[dict[str, Any]] = []
        removed_tax: list[dict[str, Any]] = []

        for r in raw_bad:
            entry = {
                "case_id": r.get("case_id"),
                "query_type": r.get("query_type"),
                "query": r.get("query", "")[:150],
                "expected_source_id": r.get("expected_source_id"),
                "returned_source_ids": r.get("returned_source_ids", [])[:5],
                "source_hit": r.get("source_hit"),
                "keyword_hit": r.get("keyword_hit"),
                "doc_type_hit": r.get("doc_type_hit"),
                "banned_source_returned": r.get("banned_source_returned"),
                "failure_type": classify_failure(r),
                "calibrated_out": False,
            }
            raw_tax.append(entry)

        for r in calibrated_bad:
            entry = {
                "case_id": r.get("case_id"),
                "query_type": r.get("query_type"),
                "query": r.get("query", "")[:150],
                "expected_source_id": r.get("expected_source_id"),
                "returned_source_ids": r.get("returned_source_ids", [])[:5],
                "source_hit": r.get("source_hit"),
                "keyword_hit": r.get("keyword_hit"),
                "doc_type_hit": r.get("doc_type_hit"),
                "banned_source_returned": r.get("banned_source_returned"),
                "failure_type": classify_failure(r),
                "calibrated_out": False,
            }
            cal_tax.append(entry)

        for r in removed_by_cal:
            entry = {
                "case_id": r.get("case_id"),
                "query_type": r.get("query_type"),
                "query": r.get("query", "")[:150],
                "reason_removed": CALIBRATION.get(r.get("query_type", ""), {}).get("reason", ""),
            }
            removed_tax.append(entry)

        # ── 写出文件 ──
        def write_jsonl(path: Path, rows):
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("w", encoding="utf-8", newline="\n") as f:
                for row in rows:
                    f.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")

        def write_json(path: Path, data):
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("w", encoding="utf-8", newline="\n") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

        write_jsonl(EVAL_DIR / f"phase6d9_{provider}_raw_bad_taxonomy.jsonl", raw_tax)
        write_jsonl(EVAL_DIR / f"phase6d9_{provider}_calibrated_bad_taxonomy.jsonl", cal_tax)
        write_jsonl(EVAL_DIR / f"phase6d9_{provider}_removed_by_calibration.jsonl", removed_tax)

        # ── Summary ──
        raw_type_dist = Counter(r["query_type"] for r in raw_bad)
        cal_type_dist = Counter(r["query_type"] for r in calibrated_bad)
        removed_type_dist = Counter(r["query_type"] for r in removed_by_cal)
        failure_dist = Counter(r["failure_type"] for r in cal_tax)
        raw_failure_dist = Counter(classify_failure(r) for r in raw_bad)

        summary = {
            "provider": provider,
            "total_cases": len(results),
            "raw_bad_count": len(raw_bad),
            "calibrated_bad_count": len(calibrated_bad),
            "removed_by_calibration": len(removed_by_cal),
            "raw_bad_by_type": dict(raw_type_dist),
            "calibrated_bad_by_type": dict(cal_type_dist),
            "removed_by_type": dict(removed_type_dist),
            "calibrated_failure_types": dict(failure_dist),
            "raw_failure_types": dict(raw_failure_dist),
            "calibration_rules_applied": {
                k: v["reason"] for k, v in CALIBRATION.items()
            },
            "remaining_hardest_types": sorted(cal_type_dist, key=cal_type_dist.get, reverse=True)[:5],
        }
        write_json(EVAL_DIR / f"phase6d9_{provider}_calibrated_summary.json", summary)

        # ── 打印 ──
        print(f"\n{'='*65}")
        print(f"  {provider.upper()} Bad Case Calibration Report")
        print(f"{'='*65}")
        print(f"  Raw bad cases:      {len(raw_bad):>4}")
        print(f"  Removed by calib:   {len(removed_by_cal):>4}  ← evaluator metric 不合理")
        print(f"  Calibrated bad:     {len(calibrated_bad):>4}  ← 真实系统问题")
        print(f"\n  Removed by type:")
        for t, c in removed_type_dist.most_common(10):
            print(f"    {t}: {c} ({CALIBRATION.get(t,{}).get('reason','')[:60]})")
        print(f"\n  Calibrated bad by type:")
        for t, c in cal_type_dist.most_common(12):
            print(f"    {t}: {c}")
        print(f"\n  Calibrated failure types:")
        for ft, c in failure_dist.most_common(10):
            print(f"    {ft}: {c}")


if __name__ == "__main__":
    main()
