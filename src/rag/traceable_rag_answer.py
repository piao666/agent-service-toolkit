"""Phase 4H: Traceable RAG answer with citations — mock/extractive mode.

无 LLM key 时，使用 mock extractive answer：
1. route_corpus 确定目标 corpus
2. 检索 top-k chunks
3. 取 top-3 chunk text_preview 拼接为答案
4. 每个 chunk 标注 [来源N: source_id | heading_path]
5. 输出 citations 列表
"""

import time
from typing import Any

from rag.config import rag_settings
from rag.corpus_router import route_corpus

CITATION_LABELS: dict[str, str] = {
    "official_docs": "外部技术文档 (official_docs)",
    "internal_engineering_docs": "内部工程文档 (internal_engineering_docs)",
}


def generate_traceable_rag_answer(
    query: str,
    top_k: int = 5,
    corpus: str = "auto",
) -> dict[str, Any]:
    """生成带 citation 的 RAG 回答（mock extractive mode）。

    不使用 LLM，基于检索结果的 text_preview 拼接。

    Returns:
        {"answer": str, "citations": list[dict], "trace": dict,
         "corpus_used": str, "llm_mode": str}
    """
    errors: list[str] = []
    t0 = time.perf_counter()

    # 1. 路由
    target_corpus = route_corpus(query, corpus)
    route_reason = "user_specified" if corpus != "auto" else "auto_routed_by_keywords"
    corpus_label = CITATION_LABELS.get(target_corpus, target_corpus)

    # 2. 检索
    try:
        if target_corpus == "internal_engineering_docs":
            from rag.internal_engineering_retriever import internal_engineering_retrieve
            retrieval_output = internal_engineering_retrieve(query, top_k=top_k)
        else:
            from rag.official_docs_retriever import official_docs_retrieve
            retrieval_output = official_docs_retrieve(query, top_k=top_k)
    except Exception as e:
        errors.append(str(e))
        retrieval_output = {"results": [], "trace": {}}

    results: list[dict[str, Any]] = retrieval_output.get("results", [])
    retrieval_trace: dict[str, Any] = retrieval_output.get("trace", {})

    # 3. 提取 top-3 chunks
    top_chunks = results[:3]
    answer_parts: list[str] = []
    citations: list[dict[str, Any]] = []

    if top_chunks:
        answer_parts.append(f"基于{corpus_label}检索的结果：\n")

        for i, chunk in enumerate(top_chunks):
            sid = chunk.get("source_id", "unknown")
            heading = chunk.get("heading_path", "")
            score = chunk.get("score", 0)
            preview = chunk.get("text_preview", "")
            url_or_path = chunk.get("origin_url", sid)

            label = f"[来源{i + 1}: {sid}"
            if heading:
                label += f" | {heading}"
            label += "]"

            answer_parts.append(f"{label}\n{preview}\n")

            citations.append({
                "citation_id": f"cite_{i + 1}",
                "corpus": target_corpus,
                "source_id": sid,
                "chunk_id": chunk.get("chunk_id", ""),
                "title": chunk.get("title", ""),
                "heading_path": heading,
                "origin_url": url_or_path,
                "quoted_evidence": preview[:300],
                "support_type": "direct" if score >= 0.7 else ("partial" if score >= 0.5 else "weak"),
            })

        # Footer
        answer_parts.append("---\n以上内容来自以下来源：\n")
        for c in citations:
            answer_parts.append(
                f"- [{c['source_id']}] {c['heading_path']} "
                f"(score: {chunk.get('score', 0):.4f}, support: {c['support_type']})\n"
            )

        if target_corpus == "internal_engineering_docs":
            answer_parts.append(
                "\n*内部工程文档，仅用于系统开发参考，不作为外部回答依据。*\n"
            )
    else:
        answer_parts.append("证据不足，无法生成回答。")
        errors.append("retrieval returned no results")

    answer_text = "\n".join(answer_parts)
    latency_ms = round((time.perf_counter() - t0) * 1000, 2)

    # 4. 构建 trace
    trace: dict[str, Any] = {
        "query": query,
        "requested_corpus": corpus,
        "corpus_used": target_corpus,
        "route_reason": route_reason,
        "top_k": top_k,
        "embedding_model": "bge-m3",
        "llm_mode": "mock_extractive",
        "citations_count": len(citations),
        "results_count": len(results),
        "retrieval_trace": retrieval_trace,
        "latency_ms": latency_ms,
        "errors": errors,
    }

    return {
        "answer": answer_text,
        "citations": citations,
        "trace": trace,
        "corpus_used": target_corpus,
        "llm_mode": "mock_extractive",
    }
