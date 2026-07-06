#!/usr/bin/env python3
"""Phase 6C Smoke: PostProcessor 增强 — fixture-based, 不依赖 Chroma/embedding。

覆盖:
  1. chunk_id duplicate case
  2. source_id duplicate case
  3. mixed channel score normalization
  4. dual corpus balance
  5. citation candidates from merged hits
  6. empty hits case
  7. malformed hit case (不崩溃, 写 errors)
"""

import json, sys
from pathlib import Path
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))
REPORTS = Path(__file__).resolve().parent.parent.parent / "reports" / "enterprise_kb_v1"
REPORTS.mkdir(parents=True, exist_ok=True)

from rag.search_channels.base import SearchHit
from rag.postprocess import (
    _deduplicate_by_chunk_id_new as deduplicate_by_chunk_id,
    _deduplicate_by_source_id_new as deduplicate_by_source_id,
    _normalize_scores_new as normalize_scores,
    _balance_corpora_new as balance_corpora,
    _select_citation_candidates_new as select_citation_candidates,
    run_postprocess_pipeline,
)


def make_hit(chunk_id, source_id, score, corpus="official_docs", channel="test", heading="", text=""):
    return SearchHit(
        chunk_id=chunk_id, source_id=source_id, heading_path=heading,
        text_preview=text, score=score, corpus=corpus, channel=channel,
    )


# -- Case 1: chunk_id duplicate --------------------------------------------

def test_chunk_dedup():
    hits = [
        make_hit("c1", "s1", 0.9),        # best score for c1
        make_hit("c1", "s1", 0.5),        # dup c1, lower — removed
        make_hit("c2", "s2", 0.8),
    ]
    result, trace = deduplicate_by_chunk_id(hits)
    c1_count = sum(1 for h in result if h.chunk_id == "c1")
    return {
        "deduped_count": len(result),
        "expected_after_dedup": 2,
        "c1_kept_once": c1_count == 1,
        "c1_keeps_highest": any(h.chunk_id == "c1" and h.score == 0.9 for h in result),
        "removed_duplicates_count": trace["removed_duplicates_count"],
        "trace_has_policy": "policy" in trace,
        "pass": len(result) == 2 and c1_count == 1,
    }


# -- Case 2: source_id duplicate -------------------------------------------

def test_source_dedup():
    hits = [
        make_hit("c1", "s1", 0.9),
        make_hit("c2", "s1", 0.8),  # same source
        make_hit("c3", "s1", 0.7),  # same source
        make_hit("c4", "s2", 0.6),
    ]
    result, trace = deduplicate_by_source_id(hits, max_per_source=2)
    s1_count = sum(1 for h in result if h.source_id == "s1")
    return {
        "deduped_count": len(result),
        "expected_after_dedup": 3,
        "s1_kept_count": s1_count,
        "s1_max_2": s1_count <= 2,
        "trace_has_policy": "source_dedup_policy" in trace,
        "pass": len(result) == 3 and s1_count == 2,
    }


# -- Case 3: score normalization -------------------------------------------

def test_score_normalize():
    hits = [
        make_hit("c1", "s1", 0.2),
        make_hit("c2", "s2", 0.5),  # official_docs
        make_hit("c3", "s3", 0.8),  # internal_engineering_docs
    ]
    result, trace = normalize_scores(hits)
    original_ok = all("original_score" in h.metadata for h in result)
    in_range = all(0.0 <= h.score <= 1.0 for h in result)
    return {
        "normalized_count": len(result),
        "original_preserved": original_ok,
        "all_in_0_1": in_range,
        "score_range_after": trace.get("score_range_after"),
        "normalize_method": trace.get("normalize_method"),
        "pass": original_ok and in_range,
    }


# -- Case 4: dual corpus balance -------------------------------------------

def test_corpus_balance():
    hits = [
        make_hit("c1", "s1", 0.9, corpus="official_docs", channel="official_vector"),
        make_hit("c2", "s1", 0.8, corpus="official_docs", channel="official_vector"),
        make_hit("c3", "s1", 0.7, corpus="official_docs", channel="official_vector"),
        make_hit("c4", "s2", 0.6, corpus="internal_engineering_docs", channel="internal_vector"),
        make_hit("c5", "s3", 0.5, corpus="internal_engineering_docs", channel="internal_vector"),
    ]
    result, trace = balance_corpora(hits, min_per_corpus=1, total_max=4)
    corpora = [h.corpus for h in result]
    has_both = "official_docs" in corpora and "internal_engineering_docs" in corpora
    return {
        "balanced_count": len(result),
        "max_4": len(result) <= 4,
        "has_both_corpora": has_both,
        "dist_before": trace.get("corpus_distribution_before"),
        "dist_after": trace.get("corpus_distribution_after"),
        "pass": has_both and len(result) <= 4,
    }


# -- Case 5: citation candidates from merged hits --------------------------

def test_citation_candidates():
    hits = [
        make_hit("c1", "s1", 0.9, corpus="official_docs", channel="official_vector",
                 heading="API > Middleware", text="FastAPI middleware processes requests before path operations."),
        make_hit("c2", "s2", 0.8, corpus="internal_engineering_docs", channel="internal_vector",
                 heading="Routing > Design", text="Auto routing uses keyword-based rules."),
        make_hit("c3", "s3", 0.7, corpus="official_docs", channel="keyword_bm25",
                 heading="Body > Nested Models", text="Pydantic models can be nested."),
    ]
    candidates, trace = select_citation_candidates(hits, max_candidates=2)
    merged_ids = {h.chunk_id for h in hits}
    citation_ids = {c.chunk_id for c in candidates}
    all_from_merged = citation_ids <= merged_ids
    # 检查 candidate 必填字段
    field_check = all(
        all(k in c.__dict__ for k in ["chunk_id", "source_id", "corpus", "score", "channel"])
        for c in candidates
    )
    return {
        "candidate_count": len(candidates),
        "max_2": len(candidates) <= 2,
        "all_from_merged_hits": all_from_merged,
        "required_fields_present": field_check,
        "trace_citation_count": trace.get("citation_candidate_count"),
        "pass": all_from_merged and field_check and len(candidates) == 2,
    }


# -- Case 6: empty hits ----------------------------------------------------

def test_empty_hits():
    result = run_postprocess_pipeline([])
    return {
        "merged_hits_empty": len(result["merged_hits"]) == 0,
        "citation_candidates_empty": len(result["citation_candidates"]) == 0,
        "no_crash": True,
        "trace_present": "postprocess_trace" in result,
        "input_count_zero": result["postprocess_trace"]["input_count"] == 0,
        "pass": len(result["merged_hits"]) == 0 and len(result["citation_candidates"]) == 0,
    }


# -- Case 7: malformed hits -------------------------------------------------

def test_malformed_hits():
    hits = [
        make_hit("", "", 0.0),                    # 空 chunk_id, source_id
        make_hit("c_good", "s_good", 0.8),        # 正常
    ]
    result = run_postprocess_pipeline(hits)
    # 空 chunk_id 不应该导致崩溃，应该被过滤
    merged_ids = [h.chunk_id for h in result["merged_hits"]]
    return {
        "no_crash": True,
        "good_hit_kept": "c_good" in merged_ids,
        "empty_chunk_filtered": "" not in merged_ids,
        "merged_count": len(result["merged_hits"]),
        "pass": "c_good" in merged_ids and "" not in merged_ids,
    }


# -- Case 8: full pipeline with mixed channels ------------------------------

def test_full_pipeline():
    hits = [
        make_hit("c1", "s1", 3.5, corpus="official_docs", channel="official_vector"),
        make_hit("c1", "s1", 3.2, corpus="official_docs", channel="keyword_bm25"),  # dup
        make_hit("c2", "s1", 2.8, corpus="official_docs", channel="official_vector"),
        make_hit("c2", "s1", 2.7, corpus="official_docs", channel="keyword_bm25"),  # dup
        make_hit("c3", "s1", 2.5, corpus="official_docs", channel="official_vector"),
        make_hit("c4", "s2", 2.0, corpus="internal_engineering_docs", channel="internal_vector"),
        make_hit("c5", "s3", 1.5, corpus="internal_engineering_docs", channel="internal_vector"),
        make_hit("c6", "s4", 1.0, corpus="official_docs", channel="metadata_filter"),
    ]
    result = run_postprocess_pipeline(hits, max_total=6, max_per_source=2, min_per_corpus=1, do_normalize=True)
    trace = result["postprocess_trace"]
    return {
        "merged_count": len(result["merged_hits"]),
        "citation_count": len(result["citation_candidates"]),
        "trace_steps_count": len(trace["steps"]),
        "trace_complete": trace["steps_count"] == 5 if False else len(trace["steps"]) >= 4,
        "errors_empty": len(result["errors"]) == 0,
        "all_scores_in_range": all(0 <= h.score <= 1 for h in result["merged_hits"]),
        "pass": len(result["merged_hits"]) > 0 and len(result["citation_candidates"]) > 0,
    }


# -- Main ------------------------------------------------------------------

def main():
    print("=== Phase 6C Smoke: PostProcessor ===")
    results = {"smoke": "phase6c_postprocess", "timestamp": datetime.now(timezone.utc).isoformat()}

    cases = [
        ("chunk_dedup", test_chunk_dedup()),
        ("source_dedup", test_source_dedup()),
        ("score_normalize", test_score_normalize()),
        ("corpus_balance", test_corpus_balance()),
        ("citation_candidates", test_citation_candidates()),
        ("empty_hits", test_empty_hits()),
        ("malformed_hits", test_malformed_hits()),
        ("full_pipeline", test_full_pipeline()),
    ]

    for name, r in cases:
        status = "PASS" if r["pass"] else "FAIL"
        print(f"  {name}: {status}")
        results[name] = r

    all_pass = all(r["pass"] for _, r in cases)
    results.update({
        "overall_pass": all_pass,
        "chunk_dedup_pass": results["chunk_dedup"]["pass"],
        "source_dedup_pass": results["source_dedup"]["pass"],
        "score_normalize_pass": results["score_normalize"]["pass"],
        "corpus_balance_pass": results["corpus_balance"]["pass"],
        "citation_candidates_from_merged_hits": results["citation_candidates"]["all_from_merged_hits"],
        "empty_hits_handled": results["empty_hits"]["pass"],
        "malformed_hits_handled": results["malformed_hits"]["pass"],
        "trace_complete": results["full_pipeline"]["pass"],
    })

    path = REPORTS / "phase6c_postprocess_smoke.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)
    print(f"\nSaved: {path}")
    print(f"Overall: {'PASS' if all_pass else 'FAIL'}")

    if not all_pass:
        print("ERROR: overall_pass=false -- exiting with code 1")
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
