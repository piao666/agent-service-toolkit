#!/usr/bin/env python3
"""Phase 4F HPC: Internal retrieval eval — 30 cases against bge-m3 internal index.

HPC 独立运行。输出到 A_DIR。
"""

import json, sys, time
from datetime import datetime, timezone
from pathlib import Path

import torch
from sentence_transformers import SentenceTransformer
import chromadb

PROJECT = Path.home() / "jupyterlab" / "RAG" / "agent-service-toolkit-clean"
A_DIR = Path.home() / "jupyterlab" / "RAG" / "A"
MODEL_PATH = Path.home() / "jupyterlab" / "models" / "bge-m3"
COLLECTION_NAME = "enterprise_kb_v1_internal_engineering_bge_m3"
PERSIST_DIR = str(PROJECT / "storage" / "chroma_enterprise_kb_v1_internal_bge_m3")

# ── 30 eval cases (6 categories × 5) ─────────────────────────────────────
EVAL_CASES = [
    # Cat 1: 项目定位与 source governance
    {"case_id": "internal_001", "query": "本项目为什么不是普通 RAG demo？", "expected_source_ids": ["internal_kb_positioning"], "expected_domain": "project_positioning"},
    {"case_id": "internal_002", "query": "为什么 source 默认 enabled=false？", "expected_source_ids": ["internal_kb_admission_policy"], "expected_domain": "source_governance"},
    {"case_id": "internal_003", "query": "allowed_for_answer=false 的作用是什么？", "expected_source_ids": ["internal_kb_admission_policy"], "expected_domain": "source_governance"},
    {"case_id": "internal_004", "query": "source_registry 解决了什么问题？", "expected_source_ids": ["internal_source_registry_spec"], "expected_domain": "source_governance"},
    {"case_id": "internal_005", "query": "official_docs 和 internal_engineering_docs 有什么区别？", "expected_source_ids": ["internal_kb_positioning"], "expected_domain": "project_positioning"},
    # Cat 2: 语料采集与 evidence audit
    {"case_id": "internal_006", "query": "为什么不能只看报告自述判断采集成功？", "expected_source_ids": ["phase3i_evidence_audit"], "expected_domain": "ingestion_audit"},
    {"case_id": "internal_007", "query": "audit.json 在语料采集里起什么作用？", "expected_source_ids": ["internal_evaluation_standard"], "expected_domain": "ingestion_audit"},
    {"case_id": "internal_008", "query": "JS redirect shell 为什么会导致内容缺失？", "expected_source_ids": ["internal_failure_patterns"], "expected_domain": "failure_pattern"},
    {"case_id": "internal_009", "query": "code block extraction 丢失会影响什么？", "expected_source_ids": ["internal_failure_patterns"], "expected_domain": "failure_pattern"},
    {"case_id": "internal_010", "query": "heading_path 为什么对检索有价值？", "expected_source_ids": ["internal_ingestion_pipeline"], "expected_domain": "ingestion_audit"},
    # Cat 3: HPC embedding A/B
    {"case_id": "internal_011", "query": "为什么 embedding 评测必须放到 HPC 跑？", "expected_source_ids": ["internal_hpc_lessons"], "expected_domain": "hpc_workflow"},
    {"case_id": "internal_012", "query": "bge-m3 为什么被选为默认 embedding？", "expected_source_ids": ["phase4d_bge_m3_decision"], "expected_domain": "embedding_evaluation"},
    {"case_id": "internal_013", "query": "qwen3-embedding-0.6b 为什么只作为高精度候选？", "expected_source_ids": ["phase4d_bge_m3_decision"], "expected_domain": "embedding_evaluation"},
    {"case_id": "internal_014", "query": "bge-small 为什么只作为 fallback？", "expected_source_ids": ["phase4d_bge_m3_decision"], "expected_domain": "embedding_evaluation"},
    {"case_id": "internal_015", "query": "per-case debug 为什么比总分更重要？", "expected_source_ids": ["internal_hpc_lessons"], "expected_domain": "hpc_workflow"},
    # Cat 4: runtime retrieval / trace
    {"case_id": "internal_016", "query": "runtime retrieval trace 必须包含哪些字段？", "expected_source_ids": ["phase4e_runtime_verification"], "expected_domain": "runtime_retrieval"},
    {"case_id": "internal_017", "query": "为什么 trace 里必须有 origin_url 或 local_path？", "expected_source_ids": ["internal_failure_patterns"], "expected_domain": "failure_pattern"},
    {"case_id": "internal_018", "query": "Phase 4E 验证了什么？", "expected_source_ids": ["phase4e_runtime_verification"], "expected_domain": "runtime_retrieval"},
    {"case_id": "internal_019", "query": "API-level smoke 的目的是什么？", "expected_source_ids": ["phase4e_runtime_verification"], "expected_domain": "runtime_retrieval"},
    {"case_id": "internal_020", "query": "collection_name 和 persist_dir 为什么要进入 trace？", "expected_source_ids": ["phase4e_runtime_verification"], "expected_domain": "runtime_retrieval"},
    # Cat 5: 失败案例与排错
    {"case_id": "internal_021", "query": "expected_source 字段错误为什么会导致 hit_rate=0？", "expected_source_ids": ["internal_failure_patterns"], "expected_domain": "failure_pattern"},
    {"case_id": "internal_022", "query": "YAML anchor 污染 source metadata 是什么问题？", "expected_source_ids": ["internal_failure_patterns"], "expected_domain": "failure_pattern"},
    {"case_id": "internal_023", "query": "repo hygiene 为什么要忽略 raw_sources/chunks/storage？", "expected_source_ids": ["internal_repo_hygiene_policy"], "expected_domain": "repo_hygiene"},
    {"case_id": "internal_024", "query": "RAG answer eval 和 retrieval context eval 有什么区别？", "expected_source_ids": ["internal_failure_patterns"], "expected_domain": "failure_pattern"},
    {"case_id": "internal_025", "query": "core_029 失败说明了什么？", "expected_source_ids": ["internal_failure_patterns"], "expected_domain": "failure_pattern"},
    # Cat 6: RAG answer citation
    {"case_id": "internal_026", "query": "本项目 RAG answer 为什么必须带 citation？", "expected_source_ids": ["internal_evaluation_standard"], "expected_domain": "ingestion_audit"},
    {"case_id": "internal_027", "query": "evidence 不足时应该怎么回答？", "expected_source_ids": ["internal_evaluation_standard"], "expected_domain": "ingestion_audit"},
    {"case_id": "internal_028", "query": "internal corpus 如何支撑项目级问题回答？", "expected_source_ids": ["internal_kb_positioning"], "expected_domain": "project_positioning"},
    {"case_id": "internal_029", "query": "auto corpus routing 如何决定查哪个库？", "expected_source_ids": ["phase4e_runtime_verification"], "expected_domain": "runtime_retrieval"},
    {"case_id": "internal_030", "query": "unsupported_claims 如何判断？", "expected_source_ids": ["internal_evaluation_standard"], "expected_domain": "ingestion_audit"},
]

TOP_K_VALUES = [3, 5, 10]


def main() -> None:
    print("=" * 60)
    print("Phase 4F HPC: Internal Retrieval Eval (30 cases)")
    print(f"Collection: {COLLECTION_NAME}")
    print("=" * 60)

    if not torch.cuda.is_available():
        print("FATAL: CUDA not available"); sys.exit(1)
    gpu_name = torch.cuda.get_device_name(0)

    # Load model
    print(f"Loading model: {MODEL_PATH}")
    model = SentenceTransformer(str(MODEL_PATH), device="cuda")

    # Connect to index
    client = chromadb.PersistentClient(path=PERSIST_DIR)
    col = client.get_collection(COLLECTION_NAME)
    print(f"Collection: {col.count()} chunks")

    # ── Eval loop ──────────────────────────────────────────────────────
    per_k: dict[int, dict] = {k: {"hits": 0, "total": 0, "mrr_sum": 0.0} for k in TOP_K_VALUES}
    per_case_debug: list[dict] = []

    for case in EVAL_CASES:
        q = case["query"]
        expected = case["expected_source_ids"]
        t0 = time.perf_counter()

        q_emb = model.encode([q], show_progress_bar=False).tolist()
        res = col.query(query_embeddings=q_emb, n_results=max(TOP_K_VALUES),
                        include=["metadatas", "distances"])
        latency = round((time.perf_counter() - t0) * 1000, 2)

        metadatas = res["metadatas"][0] if res["metadatas"] else []
        distances = res["distances"][0] if res["distances"] else []
        sids = [m.get("source_id", "") for m in metadatas]
        chunk_ids = [m.get("chunk_id", "") for m in metadatas]
        scores = [round(1 / (1 + max(d, 0.0)), 4) for d in distances]

        hit_info: dict[int, bool] = {}
        mrr_sum = 0.0
        for k in TOP_K_VALUES:
            top_k_sids = sids[:k]
            hit = any(es in top_k_sids for es in expected)
            hit_info[k] = hit
            per_k[k]["total"] += 1
            if hit:
                per_k[k]["hits"] += 1
                # MRR: best rank of any expected source
                best_rank = min(
                    (i + 1 for i, s in enumerate(top_k_sids) if s in expected),
                    default=k + 1,
                )
                per_k[k]["mrr_sum"] += 1.0 / best_rank

        per_case_debug.append({
            "case_id": case["case_id"],
            "query": q[:120],
            "expected_source_ids": expected,
            "retrieved_source_ids": sids[:10],
            "retrieved_chunk_ids": chunk_ids[:10],
            "scores": scores[:10],
            "hit_at_3": hit_info[3],
            "hit_at_5": hit_info[5],
            "hit_at_10": hit_info[10],
            "latency_ms": latency,
        })

        status = "OK" if hit_info[3] else "MISS"
        print(f"  [{case['case_id']}] {status} k3={hit_info[3]} k5={hit_info[5]} k10={hit_info[10]}")

    # ── Results ────────────────────────────────────────────────────────
    results = {
        "phase": "4F",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "environment": "HPC",
        "gpu": gpu_name,
        "model": "bge-m3",
        "collection": COLLECTION_NAME,
        "total_cases": len(EVAL_CASES),
        "per_k": {},
    }
    for k in TOP_K_VALUES:
        pk = per_k[k]
        hr = round(pk["hits"] / pk["total"], 4) if pk["total"] > 0 else 0
        mrr = round(pk["mrr_sum"] / pk["total"], 4) if pk["total"] > 0 else 0
        results["per_k"][str(k)] = {"hit_rate": hr, "mrr": mrr, "hits": pk["hits"], "total": pk["total"]}
        print(f"\nk={k}: hit_rate={hr:.4f} MRR={mrr:.4f}")

    A_DIR.mkdir(parents=True, exist_ok=True)

    # Save results
    res_path = A_DIR / "phase4fh_internal_retrieval_eval_results.json"
    with open(res_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    # Save per-case debug
    debug_path = A_DIR / "phase4fh_internal_eval_per_case_debug.jsonl"
    with open(debug_path, "w", encoding="utf-8") as f:
        for d in per_case_debug:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")

    print(f"\nResults → {res_path}")
    print(f"Debug → {debug_path}")
    print("DONE: Phase 4F HPC Internal Retrieval Eval")


if __name__ == "__main__":
    main()
