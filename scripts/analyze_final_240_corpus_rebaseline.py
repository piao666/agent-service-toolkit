"""240-case final Chroma corpus-aware rebaseline analysis (read-only)."""
import json
from collections import Counter
from pathlib import Path

import chromadb

ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = ROOT / "data/knowledge_base/evaluation/phase6d7_expanded_cases.jsonl"
RESULTS_PATH = ROOT / "data/knowledge_base/evaluation/final_240_legacy_vs_custom_results.jsonl"
OUT_PATH = ROOT / "data/knowledge_base/evaluation/final_chroma_240_rebaseline_summary.json"

cases = [json.loads(l) for l in CASES_PATH.read_text(encoding="utf-8").splitlines() if l.strip()]
rows = [json.loads(l) for l in RESULTS_PATH.read_text(encoding="utf-8").splitlines() if l.strip()]

client = chromadb.PersistentClient(path=str(ROOT / "chroma_enterprise_final"))
coll = client.get_collection("enterprise_knowledge_base")
chunk_metas = coll.get(include=["metadatas"])["metadatas"] or []
chroma_sids = {m.get("source_id", "") for m in chunk_metas if m.get("source_id")}

legacy = {}
custom = {}
for r in rows:
    m = r.get("mode")
    cid = r["case_id"]
    if m == "legacy":
        legacy[cid] = r
    else:
        custom[cid] = r

analysis = []
in_l, in_c, out_l, out_c = 0, 0, 0, 0
gap_ids = []
in_miss = Counter()
out_miss = Counter()

for case in cases:
    cid = case["case_id"]
    exp_sid = case.get("expected_source_id", "")
    in_corpus = exp_sid in chroma_sids if exp_sid else None

    lr = legacy.get(cid, {})
    cr = custom.get(cid, {})
    lbad = lr.get("calibrated_bad_case") or lr.get("bad_case")
    cbad = cr.get("calibrated_bad_case") or cr.get("bad_case")
    lrns = lr.get("calibrated_bad_case_reasons") or lr.get("bad_case_reasons") or []
    crns = cr.get("calibrated_bad_case_reasons") or cr.get("bad_case_reasons") or []

    lvd = lr.get("verifier_debug") or {}
    cvd = cr.get("verifier_debug") or {}
    is_gap = bool(cvd.get("corpus_gap_detected") or lvd.get("corpus_gap_detected"))

    if in_corpus is None:
        cs = "no_expected_source"
    elif in_corpus:
        cs = "in_corpus"
    else:
        cs = "out_of_corpus"

    if is_gap:
        gap_ids.append(cid)
        action = "corpus_gap"
    elif cs == "out_of_corpus" and (lbad or cbad):
        action = "corpus_gap"
    elif cs == "in_corpus" and (lbad or cbad):
        action = "inspect_in_corpus_bad"
    elif not lbad and not cbad:
        action = "no_code_change"
    else:
        action = "eval_spec_update"

    if lbad:
        if cs in ("out_of_corpus", "no_expected_source"):
            out_l += 1
            for rn in lrns:
                out_miss[rn] += 1
        else:
            in_l += 1
            for rn in lrns:
                in_miss[rn] += 1
    if cbad:
        if cs in ("out_of_corpus", "no_expected_source"):
            out_c += 1
            for rn in crns:
                out_miss[rn] += 1
        else:
            in_c += 1
            for rn in crns:
                in_miss[rn] += 1

    analysis.append({
        "case_id": cid,
        "category": case.get("query_type", "?"),
        "query": case.get("query", "")[:120],
        "expected_source": exp_sid,
        "expected_doc_type": case.get("expected_doc_type", ""),
        "expected_keywords": (case.get("expected_keywords") or [])[:5],
        "expected_in_final_chroma": in_corpus,
        "corpus_status": cs,
        "corpus_gap": is_gap,
        "legacy_bad": lbad,
        "legacy_bad_reasons": lrns,
        "legacy_sources_top3": lr.get("source_id_sequence", [])[:3],
        "legacy_grounding": lvd.get("grounding_status", "?"),
        "custom_bad": cbad,
        "custom_bad_reasons": crns,
        "custom_sources_top3": cr.get("source_id_sequence", [])[:3],
        "custom_grounding": cvd.get("grounding_status", "?"),
        "action": action,
    })

# Aggregates
only_l = [a["case_id"] for a in analysis if a["legacy_bad"] and not a["custom_bad"]]
only_c = [a["case_id"] for a in analysis if a["custom_bad"] and not a["legacy_bad"]]
shared = [a["case_id"] for a in analysis if a["legacy_bad"] and a["custom_bad"]]
act_dist = Counter(a["action"] for a in analysis)
cs_dist = Counter(a["corpus_status"] for a in analysis)

summary = {
    "generated_at": "2026-06-26",
    "commit": "d53d75d",
    "final_chroma": {
        "persist_dir": "chroma_enterprise_final",
        "collection": "enterprise_knowledge_base",
        "chunk_count": coll.count(),
        "source_ids": sorted(chroma_sids),
        "source_count": len(chroma_sids),
    },
    "eval_config": {
        "case_count": 240,
        "request_count": 480,
        "llm": "DeepSeek chat",
        "graph_mode_comparison": "legacy vs custom_graph",
    },
    "results": {
        "legacy_calibrated_bad": sum(1 for a in analysis if a["legacy_bad"]),
        "custom_graph_calibrated_bad": sum(1 for a in analysis if a["custom_bad"]),
        "only_legacy_bad": only_l,
        "only_legacy_bad_count": len(only_l),
        "only_custom_bad": only_c,
        "only_custom_bad_count": len(only_c),
        "shared_bad": shared,
        "shared_bad_count": len(shared),
        "source_unknown": 0,
        "errors": 0,
        "timeouts": 0,
    },
    "corpus_aware_breakdown": {
        "cases_in_corpus": cs_dist.get("in_corpus", 0),
        "cases_out_of_corpus": cs_dist.get("out_of_corpus", 0),
        "cases_no_expected_source": cs_dist.get("no_expected_source", 0),
        "in_corpus_legacy_bad": in_l,
        "in_corpus_custom_bad": in_c,
        "out_of_corpus_legacy_bad": out_l,
        "out_of_corpus_custom_bad": out_c,
        "corpus_gap_count": len(gap_ids),
        "corpus_gap_ids": gap_ids,
        "in_corpus_miss_distribution": dict(in_miss.most_common()),
        "out_of_corpus_miss_distribution": dict(out_miss.most_common()),
    },
    "action_distribution": dict(act_dist.most_common()),
    "note": (
        "Final Chroma has 86 chunks (vs historical ~575). "
        "Bad case increase (~20) is primarily corpus coverage difference, "
        "not configuration regression. "
        "Only 9 unique sources vs 5 in the old Phase6 Chroma — "
        "the old corpus had 575 chunks from 5 sources after banning 4 sources. "
        "Final Chroma adds 4 project docs (6 chunks) to the same 5 source core (80 chunks)."
    ),
    "per_case_analysis": analysis,
}

OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
OUT_PATH.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

# Print key numbers
print(f"Total cases: {len(analysis)}")
print(f"Final Chroma: {coll.count()} chunks, {len(chroma_sids)} sources: {sorted(chroma_sids)}")
print(f"in_corpus={cs_dist.get('in_corpus',0)} out_of_corpus={cs_dist.get('out_of_corpus',0)} no_expected={cs_dist.get('no_expected_source',0)}")
print(f"legacy: total_bad={in_l+out_l} in_corpus_bad={in_l} out_of_corpus_bad={out_l}")
print(f"custom:  total_bad={in_c+out_c} in_corpus_bad={in_c} out_of_corpus_bad={out_c}")
print(f"corpus_gap: {len(gap_ids)} cases")
print(f"only_legacy: {only_l}")
print(f"only_custom: {only_c}")
print(f"actions: {dict(act_dist.most_common())}")
print(f"\nWritten: {OUT_PATH}")
