#!/usr/bin/env python3
"""Phase 6F HPC Multi-channel Retrieval Real Eval.

在 HPC 上运行，需要:
  - CUDA GPU
  - bge-m3 Chroma official_docs 索引
  - bge-m3 Chroma internal_engineering_docs 索引
  - sentence-transformers

对比 baseline (单路 dense retrieval) vs phase6 multi-channel retrieval。
"""

from __future__ import annotations

import json, sys, time
from pathlib import Path
from typing import Any
from datetime import datetime, timezone

# ── HPC 路径 ──────────────────────────────────────────────────────────
PROJECT = Path.home() / "jupyterlab" / "RAG" / "agent-service-toolkit-clean"
A_DIR = Path.home() / "jupyterlab" / "RAG" / "A"
RESULTS_DIR = A_DIR / "phase6f_hpc_results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)

sys.path.insert(0, str(PROJECT / "src"))

INDEX_CHECK_INTERVAL = 30

# ── 索引验证 ──────────────────────────────────────────────────────────

def verify_indices() -> dict[str, Any]:
    """验证必需索引存在。official/internal 任一缺失 → fatal exit。"""
    import chromadb

    status = {
        "official_available": False, "internal_available": False,
        "index_missing": True, "missing_indices": [], "errors": [],
    }

    # official_docs index
    try:
        from rag.config import rag_settings
        off_persist = PROJECT / rag_settings.CHROMA_PERSIST_DIR
        off_coll = rag_settings.chroma_collection_name
        if not off_persist.exists():
            status["errors"].append(f"official_docs persist_dir not found: {off_persist}")
            status["missing_indices"].append("official_docs")
        else:
            client = chromadb.PersistentClient(path=str(off_persist))
            col = client.get_collection(off_coll)
            cnt = col.count()
            if cnt == 0:
                status["errors"].append(f"official_docs collection '{off_coll}' is empty (0 chunks)")
                status["missing_indices"].append("official_docs")
            else:
                status["official_available"] = True
                status["official_chunk_count"] = cnt
                print(f"[INDEX] official_docs: {cnt} chunks @ {off_persist}")
    except Exception as e:
        status["errors"].append(f"official_docs index error: {e}")
        status["missing_indices"].append("official_docs")

    # internal index
    try:
        from rag.config import rag_settings
        int_persist = PROJECT / rag_settings.CHROMA_INTERNAL_PERSIST_DIR
        int_coll = rag_settings.CHROMA_INTERNAL_COLLECTION_NAME
        if not int_persist.exists():
            status["errors"].append(f"internal persist_dir not found: {int_persist}")
            status["missing_indices"].append("internal_engineering_docs")
        else:
            client = chromadb.PersistentClient(path=str(int_persist))
            col = client.get_collection(int_coll)
            cnt = col.count()
            if cnt == 0:
                status["errors"].append(f"internal collection '{int_coll}' is empty (0 chunks)")
                status["missing_indices"].append("internal_engineering_docs")
            else:
                status["internal_available"] = True
                status["internal_chunk_count"] = cnt
                print(f"[INDEX] internal_engineering_docs: {cnt} chunks @ {int_persist}")
    except Exception as e:
        status["errors"].append(f"internal index error: {e}")
        status["missing_indices"].append("internal_engineering_docs")

    status["index_missing"] = len(status["missing_indices"]) > 0

    if status["index_missing"]:
        print(f"FATAL: indices missing: {status['missing_indices']}")
        for err in status["errors"]:
            print(f"  - {err}")
        sys.exit(1)

    return status


# ── 模型缓存 (避免每 case 重载 SentenceTransformer) ──────────────────

_model_cache: dict = {}

def _cached_get_embedding_model():
    """返回缓存的 bge-m3 模型，避免重复加载。"""
    if "model" not in _model_cache:
        from sentence_transformers import SentenceTransformer
        from pathlib import Path
        from rag.config import rag_settings

        model_path = rag_settings.LOCAL_EMBEDDING_MODEL_PATH
        resolved = Path(model_path).resolve()
        if not resolved.exists():
            raise FileNotFoundError(f"Embedding model not found: {resolved}")
        print(f"[MODEL] Loading bge-m3 from {resolved} (cached)")
        _model_cache["model"] = SentenceTransformer(str(resolved), device="cuda")
    return _model_cache["model"]


# ── 模型预加载 (绕过 retriever 封装, 直接用 Chroma) ────────────────
# 由于 rag.retriever.retrieve() 在 import 时绑定 get_embedding_model 引用，
# monkey-patch 无法穿透已完成的 import。直接使用 Chroma + 缓存模型。

_MODEL = None

def _get_model():
    global _MODEL
    if _MODEL is None:
        from sentence_transformers import SentenceTransformer
        from pathlib import Path
        from rag.config import rag_settings
        model_path = Path(rag_settings.LOCAL_EMBEDDING_MODEL_PATH).resolve()
        if not model_path.exists():
            raise FileNotFoundError(f"Embedding model not found: {model_path}")
        print(f"[MODEL] Loading bge-m3 from {model_path}")
        _MODEL = SentenceTransformer(str(model_path), device="cuda")
        print("[MODEL] Cached.")
    return _MODEL

# Pre-load
_get_model()
del _get_model  # 后续通过 _MODEL 直接访问


# ── Baseline: single vector retrieval ─────────────────────────────────

def _chroma_query(collection_name: str, persist_dir: str, query: str, top_k: int) -> list[dict]:
    """Direct Chroma query with cached bge-m3 model."""
    import chromadb
    emb = _MODEL.encode([query], show_progress_bar=False).tolist()
    client = chromadb.PersistentClient(path=persist_dir)
    col = client.get_collection(collection_name)
    res = col.query(query_embeddings=emb, n_results=top_k, include=["metadatas", "documents", "distances"])
    results = []
    if res["ids"] and res["ids"][0]:
        for i, cid in enumerate(res["ids"][0]):
            meta = res["metadatas"][0][i] if res["metadatas"] else {}
            dist = res["distances"][0][i] if res.get("distances") else 0.0
            results.append({
                "chunk_id": cid,
                "source_id": meta.get("source_id", ""),
                "heading_path": meta.get("heading_path", ""),
                "text_preview": (res["documents"][0][i] or "")[:200] if res.get("documents") else "",
                "score": round(1.0 - float(dist), 4),
                "corpus": "",
                "origin_url": meta.get("source_url", meta.get("origin_url", "")),
            })
    return results


def run_baseline_retrieval(query: str, route_mode: str, top_k: int = 5) -> dict[str, Any]:
    """单路 dense retrieval — 直接 Chroma，不经 rag.retriever 封装。"""
    from rag.config import rag_settings
    from pathlib import Path

    results: list[dict[str, Any]] = []
    errors: list[str] = []

    if route_mode in ("official_only", "dual"):
        try:
            off_dir = str(Path(rag_settings.CHROMA_PERSIST_DIR))
            off_coll = rag_settings.chroma_collection_name
            off = _chroma_query(off_coll, off_dir, query, top_k)
            for r in off:
                r["corpus"] = "official_docs"
            results.extend(off)
        except Exception as e:
            errors.append(f"official: {e}")

    if route_mode in ("internal_only", "dual"):
        try:
            int_dir = str(Path(rag_settings.CHROMA_INTERNAL_PERSIST_DIR))
            int_coll = rag_settings.CHROMA_INTERNAL_COLLECTION_NAME
            intr = _chroma_query(int_coll, int_dir, query, top_k)
            for r in intr:
                r["corpus"] = "internal_engineering_docs"
            results.extend(intr)
        except Exception as e:
            errors.append(f"internal: {e}")

    results.sort(key=lambda x: x.get("score", 0), reverse=True)
    chunk_ids = [r.get("chunk_id", "") for r in results[:top_k]]
    source_ids = list(dict.fromkeys(r.get("source_id", "") for r in results[:top_k]))

    return {
        "results": results[:top_k],
        "chunk_ids": chunk_ids,
        "source_ids": source_ids,
        "errors": errors,
    }


# ── Phase 6 multi-channel ─────────────────────────────────────────────

def run_multichannel_retrieval(query: str, route_mode: str, top_k: int = 5,
                               rewritten_query: str = "") -> dict[str, Any]:
    """Phase 6 多路检索。"""
    from rag.retrieval_orchestrator import run_orchestrator

    orch = run_orchestrator(
        query=query, route_mode=route_mode,
        target_corpora=_mode_to_corpora(route_mode),
        top_k=top_k, rewritten_query=rewritten_query, session_id="eval",
    )

    chunk_ids = [h.chunk_id for h in orch.merged_hits[:top_k]]
    source_ids = list(dict.fromkeys(h.source_id for h in orch.merged_hits[:top_k]))
    channel_names = [cr.channel for cr in orch.channel_results]

    return {
        "results": [
            {"chunk_id": h.chunk_id, "source_id": h.source_id,
             "score": h.score, "corpus": h.corpus, "channel": h.channel}
            for h in orch.merged_hits[:top_k]
        ],
        "chunk_ids": chunk_ids,
        "source_ids": source_ids,
        "channels": channel_names,
        "citation_candidates": [c.chunk_id for c in orch.citation_candidates],
        "errors": orch.errors,
        "total_latency_ms": orch.total_latency_ms,
    }


def _mode_to_corpora(mode: str) -> list[str]:
    if mode == "dual": return ["official_docs", "internal_engineering_docs"]
    if mode == "internal_only": return ["internal_engineering_docs"]
    return ["official_docs"]


# ── Metrics ───────────────────────────────────────────────────────────

def compute_hit_at_k(retrieved_ids: list[str], expected_ids: list[str], k_values: list[int]) -> dict[int, bool]:
    """hit@k: expected_ids 中任意一个出现在 retrieved[:k] 中。"""
    return {k: any(eid in retrieved_ids[:k] for eid in expected_ids) for k in k_values}


def compute_mrr(retrieved_ids: list[str], expected_ids: list[str]) -> float:
    """MRR: 期望 source 首次出现位置的倒数均值。"""
    for i, rid in enumerate(retrieved_ids, 1):
        if rid in expected_ids:
            return 1.0 / i
    return 0.0


def compute_duplicate_rate(results: list[dict]) -> float:
    """重复 chunk_id 比率。"""
    if not results:
        return 0.0
    ids = [r.get("chunk_id", "") for r in results]
    return (len(ids) - len(set(ids))) / len(ids) if ids else 0.0


# ── Main eval ─────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("Phase 6F HPC Multi-channel Retrieval Eval")
    print("=" * 60)

    # 1. Verify indices
    index_status = verify_indices()

    # 2. Load cases
    cases_path = PROJECT / "data" / "enterprise_kb_v1" / "eval" / "phase6f_multichannel_retrieval_cases.jsonl"
    cases = []
    with open(cases_path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                cases.append(json.loads(line))
    print(f"\n[CASES] {len(cases)} cases loaded")

    K_VALUES = [3, 5, 10]

    # 3. Run eval
    per_case: list[dict] = []
    summary = {
        "baseline": {"hit_k_counts": {k: 0 for k in K_VALUES}, "mrr_sum": 0.0, "total": 0,
                     "route_execution_correct": 0, "dual_cases": 0, "dual_correct": 0,
                     "duplicate_rate_sum": 0.0},
        "multichannel": {"hit_k_counts": {k: 0 for k in K_VALUES}, "mrr_sum": 0.0, "total": 0,
                         "route_execution_correct": 0, "dual_cases": 0, "dual_correct": 0,
                         "duplicate_rate_sum": 0.0, "citation_valid_cases": 0,
                         "citation_na_cases": 0, "citation_total": 0},
    }

    for case in cases:
        cid = case["case_id"]
        query = case["query"]
        route_mode = case["expected_route_mode"]
        expected_sids = case.get("expected_source_ids", [])
        rw = case.get("rewritten_query", "")
        case_type = case.get("case_type", "unknown")

        t0 = time.perf_counter()
        failure_reasons = []

        # Baseline
        bl = run_baseline_retrieval(query, route_mode, top_k=10)
        bl_hits = compute_hit_at_k(bl["source_ids"], expected_sids, K_VALUES)
        bl_mrr = compute_mrr(bl["source_ids"], expected_sids) if expected_sids else 0.0
        bl_dup = compute_duplicate_rate(bl["results"])

        # Multi-channel
        mc = run_multichannel_retrieval(query, route_mode, top_k=10, rewritten_query=rw)
        mc_hits = compute_hit_at_k(mc["source_ids"], expected_sids, K_VALUES)
        mc_mrr = compute_mrr(mc["source_ids"], expected_sids) if expected_sids else 0.0
        mc_dup = compute_duplicate_rate(mc["results"])

        # Route correctness
        bl_route_ok = route_mode in ("official_only", "internal_only", "dual")
        mc_route_ok = (route_mode == "dual" and
                       "official_vector" in mc.get("channels", []) and
                       "internal_vector" in mc.get("channels", [])) or \
                      (route_mode == "internal_only" and "internal_vector" in mc.get("channels", [])) or \
                      (route_mode == "official_only" and "official_vector" in mc.get("channels", []))

        # Citation validity — empty candidates 不等于 valid
        mc_citations = mc.get("citation_candidates", [])
        mc_hits_count = len(mc["chunk_ids"])
        if mc_hits_count > 0 and len(mc_citations) == 0:
            mc_citations_valid = False
            mc_citation_status = "no_candidates_with_hits"
        elif mc_hits_count == 0:
            mc_citations_valid = None  # N/A
            mc_citation_status = "not_applicable"
        elif mc_citations:
            mc_citations_valid = all(
                cid in mc["chunk_ids"] for cid in mc_citations
            )
            mc_citation_status = "valid" if mc_citations_valid else "invalid_citation_not_in_merged"
        else:
            mc_citations_valid = None
            mc_citation_status = "unknown"

        # Dual correctness
        if route_mode == "dual":
            summary["baseline"]["dual_cases"] += 1
            summary["multichannel"]["dual_cases"] += 1
            has_both_bl = bool(set(r.get("corpus", "") for r in bl["results"]) >= {"official_docs", "internal_engineering_docs"})
            has_both_mc = bool(set(r["corpus"] for r in mc["results"]) >= {"official_docs", "internal_engineering_docs"})
            if has_both_bl: summary["baseline"]["dual_correct"] += 1
            if has_both_mc: summary["multichannel"]["dual_correct"] += 1

        # No-hit case: 不计数 hit@k
        if case_type == "no_hit":
            no_crash = len(bl["errors"]) == 0 or all("not found" not in e.lower() for e in bl["errors"])
            failure_reasons.append(f"no_hit_case: crash={'yes' if not no_crash else 'no'}")
        else:
            if expected_sids:
                summary["baseline"]["total"] += 1
                summary["multichannel"]["total"] += 1
                for k in K_VALUES:
                    if bl_hits[k]: summary["baseline"]["hit_k_counts"][k] += 1
                    if mc_hits[k]: summary["multichannel"]["hit_k_counts"][k] += 1
                summary["baseline"]["mrr_sum"] += bl_mrr
                summary["multichannel"]["mrr_sum"] += mc_mrr
                summary["baseline"]["duplicate_rate_sum"] += bl_dup
                summary["multichannel"]["duplicate_rate_sum"] += mc_dup
            if bl_route_ok: summary["baseline"]["route_execution_correct"] += 1
            if mc_route_ok: summary["multichannel"]["route_execution_correct"] += 1
            if mc_citations_valid is True:
                summary["multichannel"]["citation_valid_cases"] += 1
                summary["multichannel"]["citation_total"] += 1
            elif mc_citations_valid is False:
                summary["multichannel"]["citation_total"] += 1
            # None -> not_applicable, 不计入分母

        latency = round((time.perf_counter() - t0) * 1000, 2)

        per_case.append({
            "case_id": cid,
            "query": query[:120],
            "route_mode": route_mode,
            "case_type": case_type,
            "expected_source_ids": expected_sids,
            "baseline_hit": {str(k): bl_hits[k] for k in K_VALUES},
            "baseline_mrr": round(bl_mrr, 4),
            "baseline_duplicate_rate": round(bl_dup, 4),
            "baseline_sources": bl["source_ids"][:10],
            "multichannel_hit": {str(k): mc_hits[k] for k in K_VALUES},
            "multichannel_mrr": round(mc_mrr, 4),
            "multichannel_duplicate_rate": round(mc_dup, 4),
            "multichannel_sources": mc["source_ids"][:10],
            "multichannel_channels": mc.get("channels", []),
            "route_execution_ok": mc_route_ok,
            "citation_valid": mc_citations_valid,
            "citation_status": mc_citation_status,
            "failure_reasons": failure_reasons,
            "latency_ms": latency,
            "pass": mc_route_ok and (case_type == "no_hit" or expected_sids == [] or any(mc_hits.values())),
        })

    # 4. Compute final metrics
    total = summary["multichannel"]["total"]
    baseline_metrics = {
        "hit_at_3": round(summary["baseline"]["hit_k_counts"][3] / total, 4) if total else 0,
        "hit_at_5": round(summary["baseline"]["hit_k_counts"][5] / total, 4) if total else 0,
        "hit_at_10": round(summary["baseline"]["hit_k_counts"][10] / total, 4) if total else 0,
        "mrr": round(summary["baseline"]["mrr_sum"] / total, 4) if total else 0,
        "route_execution_accuracy_given_gold_route": round(summary["baseline"]["route_execution_correct"] / len(cases), 4) if cases else 0,
        "duplicate_rate": round(summary["baseline"]["duplicate_rate_sum"] / max(total, 1), 4),
    }
    mc_metrics = {
        "hit_at_3": round(summary["multichannel"]["hit_k_counts"][3] / total, 4) if total else 0,
        "hit_at_5": round(summary["multichannel"]["hit_k_counts"][5] / total, 4) if total else 0,
        "hit_at_10": round(summary["multichannel"]["hit_k_counts"][10] / total, 4) if total else 0,
        "mrr": round(summary["multichannel"]["mrr_sum"] / total, 4) if total else 0,
        "route_execution_accuracy_given_gold_route": round(summary["multichannel"]["route_execution_correct"] / len(cases), 4) if cases else 0,
        "duplicate_rate": round(summary["multichannel"]["duplicate_rate_sum"] / max(total, 1), 4),
        "dual_accuracy": round(summary["multichannel"]["dual_correct"] / max(summary["multichannel"]["dual_cases"], 1), 4),
        "citation_validity": round(summary["multichannel"]["citation_valid_cases"] / max(summary["multichannel"]["citation_total"], 1), 4) if summary["multichannel"]["citation_total"] > 0 else 1.0,
        "citation_na_cases": summary["multichannel"]["citation_na_cases"],
    }

    failed_cases = [c for c in per_case if not c["pass"]]
    indices_ready = index_status.get("index_missing", True) is False
    citation_ok = mc_metrics["citation_validity"] >= 0.8
    dual_ok = mc_metrics["dual_accuracy"] >= 0.8
    hit_degraded = mc_metrics["hit_at_3"] < baseline_metrics["hit_at_3"] - 0.1
    overall_pass = (
        indices_ready
        and citation_ok
        and dual_ok
        and len(failed_cases) <= max(2, len(cases) * 0.1)
    )
    warnings = []
    if hit_degraded:
        warnings.append(f"Multi-channel hit@3 ({mc_metrics['hit_at_3']}) significantly below baseline ({baseline_metrics['hit_at_3']})")

    # 5. Output
    eval_results = {
        "phase": "6F",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "environment": "HPC",
        "total_cases": len(cases),
        "cases_with_expected_sids": total,
        "indices_ready": indices_ready,
        "index_status": index_status,
        "route_metric_note": "route_execution_accuracy_given_gold_route — 使用 gold route 驱动检索，验证 channel 执行正确性。Phase 6F 不评估 classifier route correctness。",
        "baseline": baseline_metrics,
        "multichannel": mc_metrics,
        "delta": {
            "hit_at_3_delta": round(mc_metrics["hit_at_3"] - baseline_metrics["hit_at_3"], 4),
            "hit_at_5_delta": round(mc_metrics["hit_at_5"] - baseline_metrics["hit_at_5"], 4),
            "hit_at_10_delta": round(mc_metrics["hit_at_10"] - baseline_metrics["hit_at_10"], 4),
            "mrr_delta": round(mc_metrics["mrr"] - baseline_metrics["mrr"], 4),
            "duplicate_rate_delta": round(mc_metrics["duplicate_rate"] - baseline_metrics["duplicate_rate"], 4),
        },
        "failed_case_count": len(failed_cases),
        "warnings": warnings,
        "overall_pass": overall_pass,
        "pass_gates": {
            "indices_ready": indices_ready,
            "citation_validity": citation_ok,
            "dual_accuracy": dual_ok,
            "failed_case_threshold": len(failed_cases) <= max(2, len(cases) * 0.1),
        },
    }

    with open(RESULTS_DIR / "phase6f_multichannel_retrieval_eval_results.json", "w", encoding="utf-8") as f:
        json.dump(eval_results, f, ensure_ascii=False, indent=2)
    print(f"\n[OUTPUT] {RESULTS_DIR / 'phase6f_multichannel_retrieval_eval_results.json'}")

    with open(RESULTS_DIR / "phase6f_per_case_results.jsonl", "w", encoding="utf-8") as f:
        for c in per_case:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    print(f"[OUTPUT] {RESULTS_DIR / 'phase6f_per_case_results.jsonl'}")

    # Failure analysis
    with open(RESULTS_DIR / "phase6f_failure_analysis.md", "w", encoding="utf-8") as f:
        f.write(f"# Phase 6F Failure Analysis\n\n**Total cases**: {len(cases)}\n**Failed**: {len(failed_cases)}\n\n")
        for c in failed_cases:
            f.write(f"## {c['case_id']}\n")
            f.write(f"- Query: {c['query'][:100]}\n")
            f.write(f"- Route: {c['route_mode']}\n")
            f.write(f"- Baseline hit@3: {c['baseline_hit']['3']}, MRR: {c['baseline_mrr']}\n")
            f.write(f"- Multi-channel hit@3: {c['multichannel_hit']['3']}, MRR: {c['multichannel_mrr']}\n")
            f.write(f"- Expected sources: {c['expected_source_ids']}\n")
            f.write(f"- Baseline sources: {c['baseline_sources']}\n")
            f.write(f"- Multi-channel sources: {c['multichannel_sources']}\n")
            f.write(f"- Failure: {'; '.join(c['failure_reasons'])}\n\n")

    # Summary
    print(f"\n{'='*40}")
    print(f"Baseline  | hit@3={baseline_metrics['hit_at_3']:.4f} hit@5={baseline_metrics['hit_at_5']:.4f} hit@10={baseline_metrics['hit_at_10']:.4f} MRR={baseline_metrics['mrr']:.4f}")
    print(f"Multichan | hit@3={mc_metrics['hit_at_3']:.4f} hit@5={mc_metrics['hit_at_5']:.4f} hit@10={mc_metrics['hit_at_10']:.4f} MRR={mc_metrics['mrr']:.4f}")
    print(f"Delta     | hit@3={eval_results['delta']['hit_at_3_delta']:+.4f} hit@5={eval_results['delta']['hit_at_5_delta']:+.4f} hit@10={eval_results['delta']['hit_at_10_delta']:+.4f} MRR={eval_results['delta']['mrr_delta']:+.4f}")
    print(f"Route exec (gold): {mc_metrics['route_execution_accuracy_given_gold_route']:.4f}  Citation validity: {mc_metrics['citation_validity']:.4f}")
    print(f"Indices ready: {indices_ready}  Citation OK: {citation_ok}  Dual OK: {dual_ok}")
    if warnings:
        for w in warnings:
            print(f"WARNING: {w}")
    print(f"Failed: {len(failed_cases)}/{len(cases)}  Overall: {'PASS' if overall_pass else 'FAIL'}")

    if not overall_pass:
        sys.exit(1)


if __name__ == "__main__":
    main()
