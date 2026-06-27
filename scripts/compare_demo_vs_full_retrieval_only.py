"""Demo vs Full corpus retrieval-only comparison (no LLM, no DeepSeek)."""
import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

try:
    from datetime import UTC as DATETIME_UTC
except ImportError:
    DATETIME_UTC = timezone.utc

from rag.retriever import retrieve  # noqa: E402

DEFAULT_CASES = ROOT_DIR / "data/knowledge_base/evaluation/phase6d7_expanded_cases.jsonl"
DEMO_PERSIST = "./chroma_enterprise_final"
DEMO_COLLECTION = "enterprise_knowledge_base"
FULL_PERSIST = "./chroma_enterprise_full"
FULL_COLLECTION = "enterprise_knowledge_base_full"
DEFAULT_OUTPUT = ROOT_DIR / "data/knowledge_base/evaluation/demo_vs_full_retrieval_only_comparison.json"


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--cases", default=str(DEFAULT_CASES))
    p.add_argument("--demo-persist", default=DEMO_PERSIST)
    p.add_argument("--demo-collection", default=DEMO_COLLECTION)
    p.add_argument("--full-persist", default=FULL_PERSIST)
    p.add_argument("--full-collection", default=FULL_COLLECTION)
    p.add_argument("--top-k", type=int, default=5)
    p.add_argument("--output", default=str(DEFAULT_OUTPUT))
    return p.parse_args()


def _hit(expected: str, source_ids: list[str]) -> bool:
    if not expected:
        return False
    return expected in source_ids


def _kw_hits(expected_kws: list[str], page_contents: list[str]) -> tuple[int, int]:
    """返回 (命中数, 总期望数)。"""
    if not expected_kws:
        return 0, 0
    combined = " ".join(page_contents).lower()
    hits = sum(1 for kw in expected_kws if kw.lower() in combined)
    return hits, len(expected_kws)


def _doc_type_hit(expected_dt: str, doc_types: list[str]) -> bool:
    if not expected_dt:
        return False
    return expected_dt in doc_types


def main() -> None:
    args = _parse_args()
    now = datetime.now(DATETIME_UTC).isoformat()

    cases = [json.loads(l) for l in Path(args.cases).read_text(encoding="utf-8").splitlines() if l.strip()]
    print(f"[信息] 加载 {len(cases)} cases")

    per_case = []
    demo_src_hit = demo_dt_hit = full_src_hit = full_dt_hit = 0
    demo_kw_hits_total = demo_kw_expected_total = 0
    full_kw_hits_total = full_kw_expected_total = 0
    demo_zero_kw = full_zero_kw = 0
    improved = regressed = unchanged = 0
    per_source_improve: dict[str, Counter] = {}

    for i, case in enumerate(cases):
        cid = case.get("case_id", f"case_{i}")
        query = case.get("query", "")
        exp_src = case.get("expected_source_id", "")
        exp_dt = case.get("expected_doc_type", "")
        exp_kws = case.get("expected_keywords", [])

        # Demo retrieval
        d_results = retrieve(query, top_k=args.top_k, persist_dir=args.demo_persist, collection_name=args.demo_collection)
        d_sids = [r.metadata.get("source_id", "") for r in d_results]
        d_dts = [r.metadata.get("doc_type", "") for r in d_results]
        d_texts = [r.page_content or "" for r in d_results]
        d_src_h = _hit(exp_src, d_sids)
        d_dt_h = _doc_type_hit(exp_dt, d_dts)
        d_kw_h, d_kw_t = _kw_hits(exp_kws, d_texts)

        # Full retrieval
        f_results = retrieve(query, top_k=args.top_k, persist_dir=args.full_persist, collection_name=args.full_collection)
        f_sids = [r.metadata.get("source_id", "") for r in f_results]
        f_dts = [r.metadata.get("doc_type", "") for r in f_results]
        f_texts = [r.page_content or "" for r in f_results]
        f_src_h = _hit(exp_src, f_sids)
        f_dt_h = _doc_type_hit(exp_dt, f_dts)
        f_kw_h, f_kw_t = _kw_hits(exp_kws, f_texts)

        # Accumulate
        if d_src_h:
            demo_src_hit += 1
        if d_dt_h:
            demo_dt_hit += 1
        if f_src_h:
            full_src_hit += 1
        if f_dt_h:
            full_dt_hit += 1
        demo_kw_hits_total += d_kw_h
        demo_kw_expected_total += d_kw_t
        full_kw_hits_total += f_kw_h
        full_kw_expected_total += f_kw_t
        if d_kw_h == 0 and d_kw_t > 0:
            demo_zero_kw += 1
        if f_kw_h == 0 and f_kw_t > 0:
            full_zero_kw += 1

        # Improved/regressed
        d_score = int(d_src_h) + int(d_dt_h) + d_kw_h
        f_score = int(f_src_h) + int(f_dt_h) + f_kw_h
        if f_score > d_score:
            improved += 1
            reason = "improved"
        elif f_score < d_score:
            regressed += 1
            reason = "regressed"
        else:
            unchanged += 1
            reason = "unchanged"

        # Per-source tracking
        if reason == "improved" and exp_src:
            if exp_src not in per_source_improve:
                per_source_improve[exp_src] = Counter()
            per_source_improve[exp_src]["improved"] += 1
        elif reason == "regressed" and exp_src:
            if exp_src not in per_source_improve:
                per_source_improve[exp_src] = Counter()
            per_source_improve[exp_src]["regressed"] += 1

        per_case.append({
            "case_id": cid,
            "query": query[:120],
            "expected_source_id": exp_src,
            "expected_doc_type": exp_dt,
            "expected_keywords": exp_kws[:5],
            "demo_sources_top3": d_sids[:3],
            "full_sources_top3": f_sids[:3],
            "demo_source_hit": d_src_h,
            "full_source_hit": f_src_h,
            "demo_doc_type_hit": d_dt_h,
            "full_doc_type_hit": f_dt_h,
            "demo_keyword_hits": d_kw_h,
            "full_keyword_hits": f_kw_h,
            "improvement_reason": reason,
        })

    total = len(cases)
    cases_with_exp = sum(1 for c in cases if c.get("expected_source_id"))

    report = {
        "generated_at": now,
        "total_cases": total,
        "cases_with_expected_source": cases_with_exp,
        "demo": {
            "source_hit_at_k": demo_src_hit,
            "doc_type_hit_at_k": demo_dt_hit,
            "keyword_hit_rate": round(demo_kw_hits_total / demo_kw_expected_total, 4) if demo_kw_expected_total else 0,
            "zero_keyword_cases": demo_zero_kw,
        },
        "full": {
            "source_hit_at_k": full_src_hit,
            "doc_type_hit_at_k": full_dt_hit,
            "keyword_hit_rate": round(full_kw_hits_total / full_kw_expected_total, 4) if full_kw_expected_total else 0,
            "zero_keyword_cases": full_zero_kw,
        },
        "delta": {
            "improved_cases": improved,
            "regressed_cases": regressed,
            "unchanged_cases": unchanged,
        },
        "per_source_improvement": {
            sid: dict(cnt) for sid, cnt in per_source_improve.items()
        },
        "per_case": per_case,
        "calls_llm": False,
        "writes_chroma": False,
    }

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    print(f"\n[信息] demo   source_hit={demo_src_hit}/{total}  kw_rate={report['demo']['keyword_hit_rate']:.3f}  zero_kw={demo_zero_kw}")
    print(f"[信息] full   source_hit={full_src_hit}/{total}  kw_rate={report['full']['keyword_hit_rate']:.3f}  zero_kw={full_zero_kw}")
    print(f"[信息] delta  improved={improved}  regressed={regressed}  unchanged={unchanged}")
    print(f"[信息] 输出: {args.output}")


if __name__ == "__main__":
    main()
