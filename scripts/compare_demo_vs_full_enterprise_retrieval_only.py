"""Demo vs Full corpus multi-mode top-k retrieval sweep (no LLM, no DeepSeek).

支持三种检索模式 × multiple top_k：
  baseline_dense: rag.retriever.retrieve()
  overlay:        rag.retriever.retrieve_with_overlay()
  enterprise_payload: build_enterprise_retrieval_payload() (子进程隔离)
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

try:
    from datetime import UTC as DATETIME_UTC
except ImportError:
    DATETIME_UTC = timezone.utc

DEFAULT_CASES = str(ROOT / "data/knowledge_base/evaluation/phase6d7_expanded_cases.jsonl")
DEFAULT_OUTPUT = str(ROOT / "data/knowledge_base/evaluation/demo_vs_full_enterprise_retrieval_only_topk_sweep.json")
DEMO_PERSIST = "./chroma_enterprise_final"
DEMO_COLLECTION = "enterprise_knowledge_base"
FULL_PERSIST = "./chroma_enterprise_full"
FULL_COLLECTION = "enterprise_knowledge_base_full"

# ═══════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════

def _hit(expected: str, items: list[str]) -> bool:
    if not expected:
        return False
    return expected in items


def _kw_hit_count(expected_kws: list[str], texts: list[str]) -> int:
    if not expected_kws:
        return 0
    combined = " ".join(texts).lower()
    return sum(1 for kw in expected_kws if kw.lower() in combined)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--cases", default=DEFAULT_CASES)
    p.add_argument("--top-k-values", type=str, default="5,10,20")
    p.add_argument("--modes", type=str, default="baseline_dense,overlay,enterprise_payload")
    p.add_argument("--output", default=DEFAULT_OUTPUT)
    return p.parse_args()


# ═══════════════════════════════════════════════════════════════
# Mode 1 & 2: baseline_dense + overlay (in-process)
# ═══════════════════════════════════════════════════════════════

def _run_in_process_mode(mode: str, cases: list[dict], top_k: int, persist: str, collection: str) -> list[dict]:
    """Run baseline_dense or overlay retrieval in-process."""
    from rag.embeddings import get_embedding_model
    from rag.retriever import retrieve, retrieve_with_overlay

    emb = get_embedding_model()
    results = []
    for case in cases:
        query = case.get("query", "")
        if mode == "overlay":
            hits, _debug = retrieve_with_overlay(query, top_k=top_k, persist_dir=persist, collection_name=collection, embeddings=emb)
        else:
            hits = retrieve(query, top_k=top_k, persist_dir=persist, collection_name=collection, embeddings=emb)

        sids = [r.metadata.get("source_id", "") for r in hits]
        dts = [r.metadata.get("doc_type", "") for r in hits]
        cids = [r.chunk_id for r in hits]
        scores = [r.relevance_score for r in hits]
        texts = [r.page_content or "" for r in hits]

        results.append({
            "source_ids": sids,
            "doc_types": dts,
            "chunk_ids": cids,
            "scores": scores,
            "texts": texts,
        })
    return results


# ═══════════════════════════════════════════════════════════════
# Mode 3: enterprise_payload (subprocess isolation)
# ═══════════════════════════════════════════════════════════════

_ENTERPRISE_RUNNER_TEMPLATE = '''
import json, sys; sys.path.insert(0, "{src}")
import os
os.environ["CHROMA_PERSIST_DIR"] = "{persist}"
os.environ["CHROMA_COLLECTION_NAME"] = "{collection}"
os.environ["ENTERPRISE_CHROMA_COLLECTION"] = "{collection}"
os.environ["EMBEDDING_PROVIDER"] = "local"
os.environ["ENTERPRISE_RAG_POLICY_MODE"] = "targeted_overlay"
os.environ["ENTERPRISE_STRUCTURED_RETRIEVAL_MODE"] = "metadata_symbol"
os.environ["ENTERPRISE_AGENT_GRAPH_MODE"] = "legacy"

from src.agents.enterprise_tools import build_enterprise_retrieval_payload

results = []
for case in json.loads(sys.stdin.read()):
    payload = build_enterprise_retrieval_payload(query=case["query"], top_k={top_k})
    sources = payload.get("sources") or []
    sids = [s.get("source_id","") for s in sources]
    dts = [s.get("doc_type","") for s in sources]
    cids = [s.get("chunk_id","") for s in sources]
    scores = [s.get("relevance_score", s.get("score",0)) for s in sources]
    texts = [s.get("content","")[:500] for s in sources]
    results.append({{"source_ids": sids, "doc_types": dts, "chunk_ids": cids, "scores": scores, "texts": texts}})
print(json.dumps(results, ensure_ascii=False))
'''


def _run_enterprise_payload_mode(cases: list[dict], top_k: int, persist: str, collection: str) -> list[dict]:
    """子进程运行 enterprise_payload，隔离 env 变量。"""
    script = _ENTERPRISE_RUNNER_TEMPLATE.format(
        src=str(SRC).replace("\\", "/"),
        persist=persist.replace("\\", "/"),
        collection=collection,
        top_k=top_k,
    )
    proc = subprocess.run(
        [sys.executable, "-c", script],
        input=json.dumps(cases, ensure_ascii=False),
        capture_output=True, text=True, timeout=600,
        cwd=str(ROOT),
    )
    if proc.returncode != 0:
        print(f"[错误] subprocess failed: {proc.stderr[:500]}", file=sys.stderr)
        return []
    return json.loads(proc.stdout)


# ═══════════════════════════════════════════════════════════════
# Aggregation
# ═══════════════════════════════════════════════════════════════

def _compute_metrics(cases: list[dict], demo_hits: list[dict], full_hits: list[dict]) -> dict:
    total = len(cases)
    cases_with_src = sum(1 for c in cases if c.get("expected_source_id"))
    cases_with_dt = sum(1 for c in cases if c.get("expected_doc_type"))

    d_src_hit = d_dt_hit = f_src_hit = f_dt_hit = 0
    d_kw_total = d_kw_expected = f_kw_total = f_kw_expected = 0
    d_zero_kw = f_zero_kw = 0
    improved = regressed = unchanged = 0
    per_source: dict[str, dict[str, int]] = {}
    per_case = []

    for i, case in enumerate(cases):
        cid = case.get("case_id", f"case_{i}")
        exp_src = case.get("expected_source_id", "")
        exp_dt = case.get("expected_doc_type", "")
        exp_kws = case.get("expected_keywords", [])

        dh = demo_hits[i]
        fh = full_hits[i]

        d_s = _hit(exp_src, dh["source_ids"])
        f_s = _hit(exp_src, fh["source_ids"])
        d_d = _hit(exp_dt, dh["doc_types"])
        f_d = _hit(exp_dt, fh["doc_types"])
        d_kw = _kw_hit_count(exp_kws, dh["texts"])
        f_kw = _kw_hit_count(exp_kws, fh["texts"])

        if d_s: d_src_hit += 1
        if f_s: f_src_hit += 1
        if d_d: d_dt_hit += 1
        if f_d: f_dt_hit += 1
        d_kw_total += d_kw; d_kw_expected += len(exp_kws)
        f_kw_total += f_kw; f_kw_expected += len(exp_kws)
        if len(exp_kws) > 0 and d_kw == 0: d_zero_kw += 1
        if len(exp_kws) > 0 and f_kw == 0: f_zero_kw += 1

        d_score = int(d_s) + int(d_d) + d_kw
        f_score = int(f_s) + int(f_d) + f_kw
        if f_score > d_score:
            ct = "improved"; improved += 1
        elif f_score < d_score:
            ct = "regressed"; regressed += 1
        else:
            ct = "unchanged"; unchanged += 1

        if ct != "unchanged" and exp_src:
            ps = per_source.setdefault(exp_src, {"improved": 0, "regressed": 0})
            if ct == "improved": ps["improved"] += 1
            else: ps["regressed"] += 1

        per_case.append({
            "case_id": cid,
            "query": case.get("query", "")[:120],
            "expected_source_id": exp_src,
            "expected_doc_type": exp_dt,
            "expected_keywords": exp_kws[:5],
            "demo_sources_top_k": dh["source_ids"],
            "full_sources_top_k": fh["source_ids"],
            "demo_chunk_ids_top_k": dh["chunk_ids"],
            "full_chunk_ids_top_k": fh["chunk_ids"],
            "demo_scores_top_k": dh["scores"],
            "full_scores_top_k": fh["scores"],
            "demo_source_hit": d_s, "full_source_hit": f_s,
            "demo_doc_type_hit": d_d, "full_doc_type_hit": f_d,
            "demo_keyword_hits": d_kw, "full_keyword_hits": f_kw,
            "change_type": ct,
        })

    return {
        "total_cases": total,
        "cases_with_expected_source": cases_with_src,
        "cases_with_expected_doc_type": cases_with_dt,
        "demo_source_hit": d_src_hit,
        "full_source_hit": f_src_hit,
        "demo_doc_type_hit": d_dt_hit,
        "full_doc_type_hit": f_dt_hit,
        "demo_keyword_hit_rate": round(d_kw_total / d_kw_expected, 4) if d_kw_expected else 0,
        "full_keyword_hit_rate": round(f_kw_total / f_kw_expected, 4) if f_kw_expected else 0,
        "demo_zero_keyword_cases": d_zero_kw,
        "full_zero_keyword_cases": f_zero_kw,
        "improved_cases": improved,
        "regressed_cases": regressed,
        "unchanged_cases": unchanged,
        "per_source_metrics": per_source,
        "per_case": per_case,
    }


# ═══════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════

def main() -> None:
    args = _parse_args()
    now = datetime.now(DATETIME_UTC).isoformat()
    top_k_values = [int(x.strip()) for x in args.top_k_values.split(",")]
    modes = [m.strip() for m in args.modes.split(",")]

    cases = [json.loads(l) for l in Path(args.cases).read_text(encoding="utf-8").splitlines() if l.strip()]
    print(f"[信息] {len(cases)} cases, modes={modes}, top_k={top_k_values}")

    all_results = []
    for mode in modes:
        in_proc_modes = {"baseline_dense", "overlay"}
        for tk in top_k_values:
            print(f"  mode={mode} top_k={tk} ...")

            if mode in in_proc_modes:
                d = _run_in_process_mode(mode, cases, tk, DEMO_PERSIST, DEMO_COLLECTION)
                f = _run_in_process_mode(mode, cases, tk, FULL_PERSIST, FULL_COLLECTION)
            elif mode == "enterprise_payload":
                d = _run_enterprise_payload_mode(cases, tk, DEMO_PERSIST, DEMO_COLLECTION)
                f = _run_enterprise_payload_mode(cases, tk, FULL_PERSIST, FULL_COLLECTION)
            else:
                print(f"  [跳过] 未知 mode: {mode}")
                continue

            metrics = _compute_metrics(cases, d, f)
            metrics["retrieval_mode"] = mode
            metrics["top_k"] = tk
            all_results.append(metrics)

            print(f"    demo src_hit={metrics['demo_source_hit']}/{len(cases)}  "
                  f"full src_hit={metrics['full_source_hit']}/{len(cases)}  "
                  f"kw_rate d={metrics['demo_keyword_hit_rate']:.3f} f={metrics['full_keyword_hit_rate']:.3f}  "
                  f"up={metrics['improved_cases']} down={metrics['regressed_cases']}")

    report = {
        "generated_at": now,
        "modes": modes,
        "top_k_values": top_k_values,
        "results": all_results,
        "calls_llm": False,
        "writes_chroma": False,
    }
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\n[信息] 完成 → {args.output}")


if __name__ == "__main__":
    main()
