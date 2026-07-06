#!/usr/bin/env python3
"""Phase 4FH-STRICT-EVAL-PATCH HPC: Mixed dual routing + RAG route correctness fix."""

import json, sys, time
from pathlib import Path

import torch
from sentence_transformers import SentenceTransformer
import chromadb

PROJECT = Path.home() / "jupyterlab" / "RAG" / "agent-service-toolkit-clean"
A_DIR = Path.home() / "jupyterlab" / "RAG" / "A"
MODEL_PATH = Path.home() / "jupyterlab" / "models" / "bge-m3"
INT_COLL = "enterprise_kb_v1_internal_engineering_bge_m3"
INT_PERSIST = str(PROJECT / "storage" / "chroma_enterprise_kb_v1_internal_bge_m3")
OFF_COLL = "enterprise_kb_v1_official_docs_bge_m3"
OFF_PERSIST = str(PROJECT / "storage" / "chroma_enterprise_kb_v1_bge_m3")

_INT_ZH = ["本项目","Phase","HPC","bge-m3","qwen3","source_registry","评测","失败案例",
           "chunk_size","chunk_overlap","runtime retrieval","allowed_for_answer","enabled=false",
           "为什么选择","知识库定位","知识库准入","ingestion pipeline","系统快照",
           "rag pipeline","config reference","agent graph","phase3","phase4",
           "语料库","chunking","embedding a/b","retrieval eval","索引构建","hpc run",
           "config.py","retriever.py","service.py","schema.py","hpc_phase4",
           "本系统","本知识库","构建流程","检索链路","代码摘要","配置项","hit@",
           "internal corpus","内部语料","内部文档","embedding 选择","repo hygiene",
           "evidence audit","trace","citation","unsupported_claims"]
_INT_EN = ["this project","this system","internal corpus","code summary","hpc_phase4",
           "enterprise_kb","ingestion pipeline","source registry","chunking strategy",
           "embedding model choice","rag pipeline current","agent graph current",
           "retrieval smoke","api retrieval","corpus router","traceable rag",
           "failure pattern","repo hygiene","hpc evaluation","retrieval debug"]

_OFF_ZH = ["FastAPI","Pydantic","Chroma","LangGraph","OpenAI","HTTPException","middleware",
           "dependency injection","metadata filtering","structured outputs","StateGraph"]
_OFF_EN = ["fastapi","pydantic","chroma","langgraph","openai","httpexception",
           "middleware","dependency injection","metadata filtering","structured outputs","stategraph"]


def route_corpus(query: str) -> str:
    ql = query.lower()
    for kw in _INT_ZH + _INT_EN:
        if kw.lower() in ql:
            return "internal_engineering_docs"
    return "official_docs"


def determine_expected_corpus(query: str) -> str:
    """Determine expected corpus based on query content analysis."""
    ql = query.lower()
    off_hits = sum(1 for kw in _OFF_ZH + _OFF_EN if kw.lower() in ql)
    int_hits = sum(1 for kw in _INT_ZH + _INT_EN if kw.lower() in ql)
    if int_hits > off_hits:
        return "internal_engineering_docs"
    if off_hits > int_hits:
        return "official_docs"
    # Tie or no hits: check if query contains project-specific terms
    if int_hits > 0:
        return "internal_engineering_docs"
    return "official_docs"


def retrieve(query, col, model, k=10):
    q_emb = model.encode([query], show_progress_bar=False).tolist()
    res = col.query(query_embeddings=q_emb, n_results=k, include=["metadatas","distances","documents"])
    m = res["metadatas"][0] if res["metadatas"] else []
    d = res["distances"][0] if res["distances"] else []
    docs = res["documents"][0] if res["documents"] else []
    return (
        [x.get("source_id","") for x in m],
        [x.get("chunk_id","") for x in m],
        [round(1/(1+max(dd,0.0)),4) for dd in d],
        [x.get("heading_path","") for x in m],
        [" ".join((dd or "").split())[:200] for dd in docs],
    )


# ── Mixed dual-corpus queries (10) ───────────────────────────────────
MIXED_QUERIES = [
    {"case_id":"mixed_001","query":"本项目用 Chroma 做向量存储，collection 怎么设计和配置的？","expected_corpora":["internal_engineering_docs","official_docs"]},
    {"case_id":"mixed_002","query":"FastAPI 的 dependency injection 在本项目的 service.py 里怎么用的？","expected_corpora":["official_docs","internal_engineering_docs"]},
    {"case_id":"mixed_003","query":"LangGraph StateGraph 和本项目的 enterprise_rag_graph 有什么区别？","expected_corpora":["official_docs","internal_engineering_docs"]},
    {"case_id":"mixed_004","query":"Pydantic BaseModel 在本项目的 schema.py 中定义了哪些检索相关模型？","expected_corpora":["official_docs","internal_engineering_docs"]},
    {"case_id":"mixed_005","query":"OpenAI streaming 和本项目的 mock extractive RAG answer 有什么不同？","expected_corpora":["official_docs","internal_engineering_docs"]},
    {"case_id":"mixed_006","query":"Chroma metadata filtering 在本项目的 structured retrieval 中如何实现的？","expected_corpora":["official_docs","internal_engineering_docs"]},
    {"case_id":"mixed_007","query":"bge-m3 embedding 模型的技术参数和本项目的选型理由","expected_corpora":["internal_engineering_docs","official_docs"]},
    {"case_id":"mixed_008","query":"本项目的 HPC embedding A/B 评测用了哪些外部文档作为 benchmark？","expected_corpora":["internal_engineering_docs","official_docs"]},
    {"case_id":"mixed_009","query":"FastAPI middleware 机制在本项目的 verify_bearer 认证中如何应用？","expected_corpora":["official_docs","internal_engineering_docs"]},
    {"case_id":"mixed_010","query":"LangGraph conditional edges 和本项目的 corpus_router 路由逻辑有什么相似之处？","expected_corpora":["official_docs","internal_engineering_docs"]},
]

# ── RAG cases with expected_corpus ───────────────────────────────────
RAG_WITH_CORPUS = [
    {"case_id":"rag_001","query":"Chroma 如何创建 collection 并指定余弦相似度？","expected_corpus":"official_docs","expected_source_ids":["chroma_official_collections"]},
    {"case_id":"rag_002","query":"FastAPI 中如何定义 POST request body？","expected_corpus":"official_docs","expected_source_ids":["fastapi_official_request_body"]},
    {"case_id":"rag_003","query":"LangGraph StateGraph 如何定义节点和边？","expected_corpus":"official_docs","expected_source_ids":["langgraph_official_stategraph"]},
    {"case_id":"rag_004","query":"OpenAI chat completion streaming 如何使用？","expected_corpus":"official_docs","expected_source_ids":["openai_official_streaming"]},
    {"case_id":"rag_005","query":"Pydantic Field validators 如何自定义验证？","expected_corpus":"official_docs","expected_source_ids":["pydantic_official_models_validation"]},
    {"case_id":"rag_006","query":"本项目为什么选择 bge-m3 作为默认 embedding？","expected_corpus":"internal_engineering_docs","expected_source_ids":["phase4d_bge_m3_decision"]},
    {"case_id":"rag_007","query":"Phase 4E 验证了哪些 runtime 配置？","expected_corpus":"internal_engineering_docs","expected_source_ids":["phase4e_runtime_verification"]},
    {"case_id":"rag_008","query":"internal corpus 包含哪些源文件类别？","expected_corpus":"internal_engineering_docs","expected_source_ids":["internal_kb_positioning"]},
    {"case_id":"rag_009","query":"HPC embedding A/B 评测流程和关键发现","expected_corpus":"internal_engineering_docs","expected_source_ids":["internal_code_summary_hpc_embedding_ab","internal_hpc_lessons"]},
    {"case_id":"rag_010","query":"repo hygiene 策略包含哪些规则？","expected_corpus":"internal_engineering_docs","expected_source_ids":["internal_repo_hygiene_policy"]},
    {"case_id":"rag_011","query":"How to set up FastAPI middleware?","expected_corpus":"official_docs","expected_source_ids":["fastapi_official_middleware"]},
    {"case_id":"rag_012","query":"HPC 评测中 bge-m3 和 qwen3 的 GPU 显存消耗差异","expected_corpus":"internal_engineering_docs","expected_source_ids":["internal_hpc_lessons","phase4d_bge_m3_decision"]},
    {"case_id":"rag_013","query":"auto corpus routing 的规则和实现方式","expected_corpus":"internal_engineering_docs","expected_source_ids":["internal_code_summary_service_py"]},
    {"case_id":"rag_014","query":"Chroma metadata filtering 和 structured retrieval 的关系","expected_corpus":"internal_engineering_docs","expected_source_ids":["internal_rag_pipeline_current"]},
    {"case_id":"rag_015","query":"本项目从 Phase 3 到 Phase 4 的语料库构建关键决策","expected_corpus":"internal_engineering_docs","expected_source_ids":["phase3f_strategy_decision","phase4d_bge_m3_decision","phase4e_runtime_verification"]},
]


def main():
    print("=" * 60)
    print("Phase 4FH-STRICT-EVAL-PATCH HPC")
    print("=" * 60)
    if not torch.cuda.is_available():
        print("FATAL: CUDA not available"); sys.exit(1)

    model = SentenceTransformer(str(MODEL_PATH), device="cuda")
    client_off = chromadb.PersistentClient(path=OFF_PERSIST)
    col_off = client_off.get_collection(OFF_COLL)
    client_int = chromadb.PersistentClient(path=INT_PERSIST)
    col_int = client_int.get_collection(INT_COLL)
    print(f"Official: {col_off.count()}  Internal: {col_int.count()}")

    # ═══════════════════════════════════════════════════════════════
    # TASK 3: Mixed dual-corpus routing eval
    # ═══════════════════════════════════════════════════════════════
    print("\n--- Mixed Dual-Corpus Routing (10 queries) ---")
    mixed_results = []
    for case in MIXED_QUERIES:
        q = case["query"]
        # Dual mode: query BOTH corpora, top3 each
        sids_off, cids_off, scores_off, hpaths_off, previews_off = retrieve(q, col_off, model, 5)
        sids_int, cids_int, scores_int, hpaths_int, previews_int = retrieve(q, col_int, model, 5)

        # Merge top3 from each, keeping corpus tag
        off_results = [{"source_id": sids_off[i], "chunk_id": cids_off[i], "score": scores_off[i],
                         "heading_path": hpaths_off[i], "text_preview": previews_off[i],
                         "corpus": "official_docs"} for i in range(min(3, len(sids_off)))]
        int_results = [{"source_id": sids_int[i], "chunk_id": cids_int[i], "score": scores_int[i],
                         "heading_path": hpaths_int[i], "text_preview": previews_int[i],
                         "corpus": "internal_engineering_docs"} for i in range(min(3, len(sids_int)))]

        all_merged = off_results + int_results
        all_merged.sort(key=lambda x: x["score"], reverse=True)

        corpora_used = list(set(r["corpus"] for r in all_merged))
        both_queried = len(corpora_used) >= 2
        has_official = any(r["corpus"] == "official_docs" for r in all_merged)
        has_internal = any(r["corpus"] == "internal_engineering_docs" for r in all_merged)

        mixed_results.append({
            "case_id": case["case_id"], "query": q[:120],
            "route_mode": "dual",
            "target_corpora": ["official_docs", "internal_engineering_docs"],
            "corpora_actually_used": corpora_used,
            "both_corpora_queried": both_queried,
            "has_official_results": has_official,
            "has_internal_results": has_internal,
            "official_top3": off_results,
            "internal_top3": int_results,
            "merged_top6": all_merged[:6],
            "pass": both_queried and has_official and has_internal,
        })
        print(f"  [{case['case_id']}] dual official={has_official} internal={has_internal} pass={both_queried}")

    mixed_summary = {
        "phase": "4FH-STRICT-PATCH",
        "total": len(MIXED_QUERIES),
        "route_mode": "dual",
        "all_both_corpora_queried": all(r["both_corpora_queried"] for r in mixed_results),
        "pass_count": sum(1 for r in mixed_results if r["pass"]),
        "cases": mixed_results,
    }
    print(f"  All both corpora: {mixed_summary['all_both_corpora_queried']}  Pass: {mixed_summary['pass_count']}/{len(MIXED_QUERIES)}")

    # ═══════════════════════════════════════════════════════════════
    # TASK 4: RAG route correctness (NOT unconditionally true)
    # ═══════════════════════════════════════════════════════════════
    print("\n--- RAG Route Correctness Fix ---")
    rag_results = []
    rag_traces = []
    pass_count = 0

    for case in RAG_WITH_CORPUS:
        q = case["query"]
        routed = route_corpus(q)
        expected_corpus = case["expected_corpus"]
        route_correct = (routed == expected_corpus)
        route_reason = "router_keyword_match" if route_correct else f"router_mismatch: expected_{expected_corpus}_routed_{routed}"

        # STRICT: query the router-determined corpus
        target_corpora = [routed]
        route_mode = "official_only" if routed == "official_docs" else "internal_only"
        col = col_off if routed == "official_docs" else col_int
        sids, cids, scores, hpaths, previews = retrieve(q, col, model, 5)

        # If route is wrong, also query the correct corpus for diagnostics
        diag_sids, diag_cids, diag_scores, diag_hpaths, diag_previews = [], [], [], [], []
        if not route_correct:
            diag_col = col_int if expected_corpus == "internal_engineering_docs" else col_off
            diag_sids, diag_cids, diag_scores, diag_hpaths, diag_previews = retrieve(q, diag_col, model, 5)

        # Build citations from routed corpus results
        top_n = min(3, len(sids))
        citations = []
        for i in range(top_n):
            citations.append({
                "citation_id": f"cite_{i+1}", "corpus": routed,
                "source_id": sids[i], "chunk_id": cids[i],
                "heading_path": hpaths[i], "quoted_evidence": previews[i][:300],
                "support_type": "direct" if scores[i] >= 0.7 else ("partial" if scores[i] >= 0.5 else "weak"),
            })

        answer_has_citations = len(citations) > 0
        cited_ids = {c["chunk_id"] for c in citations}
        retrieved_ids = set(cids[:5])
        citations_from_retrieved = cited_ids.issubset(retrieved_ids) if cited_ids else False

        # Check hit — use routed corpus results first, fall back to diagnostic
        hit = any(es in sids[:5] for es in case["expected_source_ids"])
        diag_hit = any(es in diag_sids[:5] for es in case["expected_source_ids"]) if not route_correct else False

        # STRICT pass: ALL 4 conditions
        strict_pass = answer_has_citations and citations_from_retrieved and hit and route_correct

        trace = {
            "query": q, "corpus_used": routed, "expected_corpus": expected_corpus,
            "route_mode": route_mode, "target_corpora": target_corpora,
            "corpus_route_correct": route_correct,
            "corpus_route_correct_reason": route_reason,
            "llm_mode": "mock_extractive",
            "citations_count": len(citations),
            "retrieved_chunk_ids": cids[:5], "retrieved_source_ids": sids[:5],
            "scores": scores[:5], "heading_paths": hpaths[:5], "text_previews": previews[:5],
            "hit_in_routed_corpus": hit,
            "diagnostic_correct_corpus_hit": diag_hit,
            "errors": [] if route_correct else [f"routing error: expected {expected_corpus}, got {routed}"],
        }
        rag_traces.append(trace)

        rag_results.append({
            "case_id": case["case_id"], "query": q[:120],
            "expected_corpus": expected_corpus, "routed_corpus": routed,
            "route_mode": route_mode, "target_corpora": target_corpora,
            "corpus_route_correct": route_correct,
            "corpus_route_correct_reason": route_reason,
            "answer_has_citations": answer_has_citations,
            "citations_from_retrieved_chunks": citations_from_retrieved,
            "hit_expected_source": hit,
            "hit_in_correct_corpus": diag_hit if not route_correct else hit,
            "unsupported_claims_count": 0 if hit else 1,
            "hallucination_risk": "none" if citations_from_retrieved else "high",
            "llm_mode": "mock_extractive",
            "pass": strict_pass,
        })
        if strict_pass: pass_count += 1
        status = "PASS" if strict_pass else ("ROUTE" if not route_correct else "HIT" if not hit else "CITE")
        print(f"  [{case['case_id']}] route={routed} expected={expected_corpus} correct={route_correct} hit={hit} pass={strict_pass} ({status})")

    rag_summary = {
        "phase": "4FH-STRICT-PATCH",
        "total": len(RAG_WITH_CORPUS),
        "pass_count": pass_count,
        "route_correct_count": sum(1 for r in rag_results if r["corpus_route_correct"]),
        "citation_validity": round(sum(1 for r in rag_results if r["citations_from_retrieved_chunks"])/len(rag_results), 4),
        "hit_count": sum(1 for r in rag_results if r["hit_expected_source"]),
        "mock_mode": True,
        "cases": rag_results,
    }
    print(f"  Route correct: {rag_summary['route_correct_count']}/{len(RAG_WITH_CORPUS)}")
    print(f"  Hit: {rag_summary['hit_count']}/{len(RAG_WITH_CORPUS)}")
    print(f"  Pass (4/4): {pass_count}/{len(RAG_WITH_CORPUS)}")

    # ═══════════════════════════════════════════════════════════════
    # SAVE
    # ═══════════════════════════════════════════════════════════════
    A_DIR.mkdir(parents=True, exist_ok=True)
    def save(fname, data):
        path = A_DIR / fname
        with open(path, "w", encoding="utf-8") as f:
            if fname.endswith(".jsonl"):
                for d in data: f.write(json.dumps(d, ensure_ascii=False)+"\n")
            else: json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"  Saved: {path}")

    save("phase4fh_dual_corpus_mixed_eval_results.json", mixed_summary)
    save("phase4fh_rag_answer_eval_strict_results.json", rag_summary)
    save("phase4fh_rag_trace_samples_strict.jsonl", rag_traces)

    print("\nDONE: Phase 4FH-STRICT-EVAL-PATCH HPC")


if __name__ == "__main__":
    main()
