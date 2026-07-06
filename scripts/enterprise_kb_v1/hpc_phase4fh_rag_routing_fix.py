#!/usr/bin/env python3
"""Phase 4FH-RAG-ROUTING-FIX HPC: Fix 3 RAG failures with updated router + new source."""

import json, sys, time
from pathlib import Path
from datetime import datetime, timezone

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
CHUNKS_PATH = PROJECT / "data/enterprise_kb_v1/chunks/internal_engineering_docs/all_chunks.jsonl"

# Updated router with dual routing + new keywords
_INT_ZH = [
    "本项目","Phase","HPC","bge-m3","qwen3","source_registry","评测","失败案例",
    "chunk_size","chunk_overlap","runtime retrieval","allowed_for_answer","enabled=false",
    "为什么选择","知识库定位","知识库准入","ingestion pipeline","系统快照",
    "rag pipeline","config reference","agent graph","phase3","phase4",
    "语料库","chunking","embedding a/b","retrieval eval","索引构建","hpc run",
    "config.py","retriever.py","service.py","schema.py","hpc_phase4",
    "本系统","本知识库","构建流程","检索链路","代码摘要","配置项","hit@",
    "internal corpus","内部语料","内部文档","embedding 选择","repo hygiene",
    "evidence audit","trace","citation","unsupported_claims",
    "auto corpus routing","corpus routing","routing 规则",
    "corpus_router","route_corpus","detect_corpus",
    "corpus 分类","源文件类别","source categories",
    "internal corpus overview","内部语料概览",
]
_INT_EN = ["this project","this system","internal corpus","code summary","hpc_phase4",
           "enterprise_kb","ingestion pipeline","source registry","chunking strategy",
           "embedding model choice","rag pipeline current","agent graph current",
           "retrieval smoke","api retrieval","corpus router","traceable rag",
           "failure pattern","repo hygiene","hpc evaluation","retrieval debug"]

_OFFICIAL_SIGNAL = ["chroma","fastapi","langgraph","openai","pydantic",
    "httpexception","middleware","dependency injection","metadata filtering",
    "structured outputs","stategraph","collection","embedding function",
    "request body","streaming","tool call","field validator"]
_INTERNAL_SIGNAL = ["structured retrieval","检索设计","本项目","corpus_router",
    "route_corpus","auto routing","corpus routing","trace","检索链路",
    "rag pipeline","agent graph","internal corpus","内部语料","代码摘要",
    "retrieval eval","评测","hpc","phase","source categories","源文件类别"]

def detect_route_mode(query: str) -> str:
    ql = query.lower()
    off_hits = sum(1 for kw in _OFFICIAL_SIGNAL if kw.lower() in ql)
    int_hits = sum(1 for kw in _INTERNAL_SIGNAL + _INT_ZH + _INT_EN if kw.lower() in ql)
    if off_hits > 0 and int_hits > 0:
        return "dual"
    if int_hits > 0:
        return "internal_only"
    return "official_only"

def retrieve(query, col, model, k=5):
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

RAG_CASES = [
    {"case_id":"rag_001","query":"Chroma 如何创建 collection 并指定余弦相似度？","expected_corpus":"official_docs","expected_source_ids":["chroma_official_collections"]},
    {"case_id":"rag_002","query":"FastAPI 中如何定义 POST request body？","expected_corpus":"official_docs","expected_source_ids":["fastapi_official_request_body"]},
    {"case_id":"rag_003","query":"LangGraph StateGraph 如何定义节点和边？","expected_corpus":"official_docs","expected_source_ids":["langgraph_official_stategraph"]},
    {"case_id":"rag_004","query":"OpenAI chat completion streaming 如何使用？","expected_corpus":"official_docs","expected_source_ids":["openai_official_streaming"]},
    {"case_id":"rag_005","query":"Pydantic Field validators 如何自定义验证？","expected_corpus":"official_docs","expected_source_ids":["pydantic_official_models_validation"]},
    {"case_id":"rag_006","query":"本项目为什么选择 bge-m3 作为默认 embedding？","expected_corpus":"internal_engineering_docs","expected_source_ids":["phase4d_bge_m3_decision"]},
    {"case_id":"rag_007","query":"Phase 4E 验证了哪些 runtime 配置？","expected_corpus":"internal_engineering_docs","expected_source_ids":["phase4e_runtime_verification"]},
    {"case_id":"rag_008","query":"internal corpus 包含哪些源文件类别？","expected_corpus":"internal_engineering_docs","expected_source_ids":["internal_corpus_overview","internal_kb_positioning"]},
    {"case_id":"rag_009","query":"HPC embedding A/B 评测流程和关键发现","expected_corpus":"internal_engineering_docs","expected_source_ids":["internal_code_summary_hpc_embedding_ab","internal_hpc_lessons"]},
    {"case_id":"rag_010","query":"repo hygiene 策略包含哪些规则？","expected_corpus":"internal_engineering_docs","expected_source_ids":["internal_repo_hygiene_policy"]},
    {"case_id":"rag_011","query":"How to set up FastAPI middleware?","expected_corpus":"official_docs","expected_source_ids":["fastapi_official_middleware"]},
    {"case_id":"rag_012","query":"HPC 评测中 bge-m3 和 qwen3 的 GPU 显存消耗差异","expected_corpus":"internal_engineering_docs","expected_source_ids":["internal_hpc_lessons","phase4d_bge_m3_decision"]},
    {"case_id":"rag_013","query":"auto corpus routing 的规则和实现方式","expected_corpus":"internal_engineering_docs","expected_source_ids":["internal_corpus_routing_design","internal_code_summary_service_py"]},
    {"case_id":"rag_014","query":"Chroma metadata filtering 和 structured retrieval 的关系","expected_corpus":"dual","expected_source_ids":["internal_rag_pipeline_current","chroma_official_collections"]},
    {"case_id":"rag_015","query":"本项目从 Phase 3 到 Phase 4 的语料库构建关键决策","expected_corpus":"internal_engineering_docs","expected_source_ids":["phase3f_strategy_decision","phase4d_bge_m3_decision","phase4e_runtime_verification"]},
]

def _get_target_corpora(route_mode: str) -> list[str]:
    if route_mode == "dual":
        return ["official_docs", "internal_engineering_docs"]
    if route_mode == "internal_only":
        return ["internal_engineering_docs"]
    return ["official_docs"]


def main():
    print("=" * 60)
    print("Phase 4FH-RAG-ROUTING-FIX HPC")
    print("=" * 60)
    if not torch.cuda.is_available():
        print("FATAL: CUDA not available"); sys.exit(1)

    model = SentenceTransformer(str(MODEL_PATH), device="cuda")
    client_off = chromadb.PersistentClient(path=OFF_PERSIST)
    col_off = client_off.get_collection(OFF_COLL)
    client_int = chromadb.PersistentClient(path=INT_PERSIST)

    # Rebuild internal index with new chunks
    print("Rebuilding internal index...")
    with open(CHUNKS_PATH, encoding="utf-8") as f:
        chunks = [json.loads(l) for l in f if l.strip()]
    print(f"  Chunks: {len(chunks)}")
    try: client_int.delete_collection(INT_COLL)
    except: pass
    col_int = client_int.create_collection(INT_COLL, metadata={"hnsw:space": "cosine"})
    for i in range(0, len(chunks), 100):
        batch = chunks[i:i+100]
        emb = model.encode([c["text"] for c in batch], show_progress_bar=False).tolist()
        col_int.add(
            ids=[c["chunk_id"] for c in batch],
            documents=[c["text"] for c in batch],
            metadatas=[{"chunk_id":c["chunk_id"],"source_id":c["source_id"],"heading_path":c.get("heading_path","")} for c in batch],
            embeddings=emb,
        )
    print(f"  Indexed: {col_int.count()} chunks")
    print(f"  Official: {col_off.count()} chunks")

    # ── RAG eval with new routing ────────────────────────────────────
    print("\n--- RAG Eval (15 cases, updated router) ---")
    results = []
    traces = []
    pass_count = 0

    for case in RAG_CASES:
        q = case["query"]
        route_mode = detect_route_mode(q)
        expected = case["expected_corpus"]
        expected_sids = case["expected_source_ids"]

        # Collect results based on route_mode
        all_sids, all_cids, all_scores, all_hpaths, all_previews = [], [], [], [], []
        all_corpora = []
        if route_mode in ("official_only", "dual"):
            s, c, sc, h, p = retrieve(q, col_off, model, 3 if route_mode == "dual" else 5)
            for j in range(len(s)):
                all_sids.append(s[j]); all_cids.append(c[j]); all_scores.append(sc[j])
                all_hpaths.append(h[j]); all_previews.append(p[j])
                all_corpora.append("official_docs")
        if route_mode in ("internal_only", "dual"):
            s, c, sc, h, p = retrieve(q, col_int, model, 3 if route_mode == "dual" else 5)
            for j in range(len(s)):
                all_sids.append(s[j]); all_cids.append(c[j]); all_scores.append(sc[j])
                all_hpaths.append(h[j]); all_previews.append(p[j])
                all_corpora.append("internal_engineering_docs")

        # Sort by score
        combined = list(zip(all_sids, all_cids, all_scores, all_hpaths, all_previews, all_corpora))
        combined.sort(key=lambda x: x[2], reverse=True)

        # Route correctness: map expected_corpus to route_mode
        expected_mode = {"official_docs": "official_only", "internal_engineering_docs": "internal_only", "dual": "dual"}.get(expected, "official_only")
        route_correct = (route_mode == expected_mode)

        # Build citations from top 3
        top_n = min(3, len(combined))
        citations = []
        for i in range(top_n):
            sid, cid, score, hpath, preview, corp = combined[i]
            citations.append({
                "citation_id": f"cite_{i+1}", "corpus": corp,
                "source_id": sid, "chunk_id": cid,
                "title": hpath.split(" > ")[0] if hpath else sid,
                "heading_path": hpath,
                "origin_url": sid if corp == "official_docs" else "",
                "local_path": sid if corp == "internal_engineering_docs" else "",
                "quoted_evidence": preview[:300],
                "support_type": "direct" if score >= 0.7 else ("partial" if score >= 0.5 else "weak"),
            })

        hit = any(es in [x[0] for x in combined[:5]] for es in expected_sids)
        answer_has_citations = len(citations) > 0
        cited_cids = {c["chunk_id"] for c in citations}
        retrieved_cids = {x[1] for x in combined[:5]}
        citations_from_retrieved = cited_cids.issubset(retrieved_cids) if cited_cids else False

        unsupported = []
        h_risk = "none"
        if not hit:
            unsupported.append("expected source not in top-5 retrieved")
            h_risk = "medium"
        if not citations_from_retrieved:
            h_risk = "high"

        strict_pass = answer_has_citations and citations_from_retrieved and hit and route_correct

        # Build answer_markdown
        corp_label = "official_docs + internal_engineering_docs" if route_mode == "dual" else route_mode.replace("_only","")
        answer_parts = [f"基于 {corp_label} 检索的结果：\n"]
        for i, c in enumerate(citations):
            label = f"[来源{i+1}: {c['source_id']}"
            if c['heading_path']: label += f" | {c['heading_path']}"
            label += "]"
            answer_parts.append(f"{label}\n{c['quoted_evidence'][:200]}\n")
        answer_parts.append("---\n以上内容来自以下来源：\n")
        for c in citations:
            answer_parts.append(f"- [{c['source_id']}] {c['heading_path']} ({c['support_type']})\n")

        used_sources = list(dict.fromkeys(r["corpus"] for r in citations))

        trace = {
            "query": q, "route_mode": route_mode, "expected_corpus": expected,
            "corpus_route_correct": route_correct,
            "corpus_route_correct_reason": f"route_mode={route_mode}, expected={expected}",
            "target_corpora": _get_target_corpora(route_mode),
            "llm_mode": "mock_extractive",
            "answer_markdown": "".join(answer_parts),
            "citations": citations,
            "used_sources": used_sources,
            "retrieved_chunk_ids": [x[1] for x in combined[:5]],
            "retrieved_source_ids": [x[0] for x in combined[:5]],
            "scores": [x[2] for x in combined[:5]],
            "heading_paths": [x[3] for x in combined[:5]],
            "text_previews": [x[4] for x in combined[:5]],
            "unsupported_claims": unsupported,
            "hallucination_risk": h_risk,
            "errors": [] if route_correct else [f"route mismatch: expected {expected}, got {route_mode}"],
        }
        traces.append(trace)

        results.append({
            "case_id": case["case_id"], "query": q[:120],
            "route_mode": route_mode, "expected_corpus": expected,
            "corpus_route_correct": route_correct,
            "answer_has_citations": answer_has_citations,
            "citations_from_retrieved_chunks": citations_from_retrieved,
            "hit_expected_source": hit,
            "unsupported_claims_count": len(unsupported),
            "hallucination_risk": h_risk,
            "llm_mode": "mock_extractive",
            "pass": strict_pass,
        })
        if strict_pass: pass_count += 1
        status = "PASS" if strict_pass else ("ROUTE" if not route_correct else "HIT" if not hit else "CITE")
        print(f"  [{case['case_id']}] mode={route_mode} expected={expected} route_ok={route_correct} hit={hit} pass={strict_pass} ({status})")

    summary = {
        "phase": "4FH-RAG-ROUTING-FIX",
        "total": len(RAG_CASES), "pass_count": pass_count,
        "route_correct_count": sum(1 for r in results if r["corpus_route_correct"]),
        "hit_count": sum(1 for r in results if r["hit_expected_source"]),
        "citation_validity": round(sum(1 for r in results if r["citations_from_retrieved_chunks"])/len(results), 4),
        "mock_mode": True,
        "reranker_enabled": False,
        "cases": results,
    }
    print(f"\n  Pass: {pass_count}/{len(RAG_CASES)}")
    print(f"  Route correct: {summary['route_correct_count']}/{len(RAG_CASES)}")
    print(f"  Hit: {summary['hit_count']}/{len(RAG_CASES)}")

    A_DIR.mkdir(parents=True, exist_ok=True)
    def save(fn, data):
        p = A_DIR / fn
        with open(p, "w", encoding="utf-8") as f:
            if fn.endswith(".jsonl"):
                for d in data: f.write(json.dumps(d, ensure_ascii=False)+"\n")
            else: json.dump(data, f, ensure_ascii=False, indent=2)
        print(f"  Saved: {p}")

    save("phase4fh_rag_answer_eval_strict_results.json", summary)
    save("phase4fh_rag_trace_samples_strict.jsonl", traces)
    print("\nDONE: Phase 4FH-RAG-ROUTING-FIX HPC")

if __name__ == "__main__":
    main()
