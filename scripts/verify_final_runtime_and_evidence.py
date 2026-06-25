"""Evidence Verifier V2 验证脚本。

默认不调用真实 LLM，使用 USE_FAKE_MODEL=true 做 runtime + verifier fixture 验证。

用法：
  python scripts/verify_final_runtime_and_evidence.py
  python scripts/verify_final_runtime_and_evidence.py --execute  # 实际调用 API
"""

from __future__ import annotations

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

OUTPUT_PATH = (
    ROOT_DIR / "data" / "knowledge_base" / "evaluation"
    / "final_runtime_evidence_verification.json"
)

FINAL_PERSIST_DIR = "./chroma_enterprise_final"
FINAL_COLLECTION = "enterprise_knowledge_base"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evidence Verifier V2 验证")
    parser.add_argument("--execute", action="store_true", help="实际调用 API 端点")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--output", default=str(OUTPUT_PATH))
    return parser.parse_args()


# ═══════════════════════════════════════════════════════════════
# A. Runtime retrieval 验证 (offline, via retriever)
# ═══════════════════════════════════════════════════════════════

def _run_retrieval_verification() -> list[dict[str, Any]]:
    """直接使用本地 retriever + verifier 验证（不启动服务）。"""
    from rag.evidence_verifier import verify_answer_grounding
    from rag.retriever import retrieve

    cases = [
        {
            "id": "fastapi_request_body",
            "query": "FastAPI 里 Request Body 如何定义？",
            "answer": (
                "在 FastAPI 中，Request Body 使用 Pydantic BaseModel 定义。"
                "创建一个继承自 BaseModel 的类，声明字段及类型，"
                "然后在路径操作函数中声明该类型的参数。"
                "FastAPI 会自动解析 JSON 请求体，生成 Swagger UI 文档。"
            ),
        },
        {
            "id": "rag_definition",
            "query": "RAG 是什么？",
            "answer": (
                "RAG（Retrieval-Augmented Generation，检索增强生成）是一种"
                "结合检索和生成的技术架构。它先从知识库中检索相关文档片段，"
                "然后将检索结果作为上下文提供给大语言模型进行回答生成。"
                "RAG 能有效减少幻觉，提高回答的事实准确性。"
            ),
        },
        {
            "id": "system_retrieval",
            "query": "这个系统是如何进行检索的？",
            "answer": (
                "本系统的检索流程为：document -> chunk -> embedding -> "
                "vector store -> retrieval -> context -> answer。"
                "文档先被分割为 chunks，然后通过 embedding 模型向量化后存入 Chroma 向量库。"
                "查询时使用相同的 embedding 模型将问题向量化，在向量库中做相似度检索，"
                "返回 top-k 最相关的文档片段作为回答的上下文。"
            ),
        },
        {
            "id": "lora_corpus_gap",
            "query": "LoRA 有什么作用？",
            "answer": (
                "LoRA（Low-Rank Adaptation，低秩适配）是一种参数高效的微调方法。"
                "它在预训练模型的权重矩阵中注入低秩分解矩阵，"
                "只训练这些低秩矩阵而不修改原始权重。"
                "LoRA 显著减少了微调所需的参数量和显存占用。"
            ),
        },
    ]

    results: list[dict[str, Any]] = []
    for case in cases:
        retrieval = retrieve(
            case["query"], top_k=5,
            persist_dir=FINAL_PERSIST_DIR,
            collection_name=FINAL_COLLECTION,
        )

        # 构建 sources（模拟 API 返回格式）
        sources = []
        for r in retrieval:
            meta = dict(r.metadata or {})
            sources.append({
                "source": r.source,
                "source_id": meta.get("source_id", ""),
                "title": r.title or "",
                "doc_type": r.doc_type or "",
                "chunk_id": r.chunk_id,
                "chunk_index": r.chunk_index,
                "distance": r.distance,
                "relevance_score": r.relevance_score,
                "score": r.score,
                "content_preview": r.content_preview or "",
                "content": r.page_content or "",
                "page_content": r.page_content or "",
                "metadata": meta,
            })

        source_ids = [s["source_id"] for s in sources]
        titles = [s["title"] for s in sources]
        source_unknown_count = sum(1 for s in sources if s["source"] == "unknown")

        # 调用 V2 verifier
        verifier_result = verify_answer_grounding(
            query=case["query"],
            answer=case["answer"],
            sources=sources,
            mode="rule_based",
        )
        vd = verifier_result.as_debug()

        results.append({
            "id": case["id"],
            "query": case["query"],
            "source_id_sequence": source_ids[:5],
            "title_sequence": titles[:5],
            "source_unknown_count": source_unknown_count,
            "grounding_status": vd.get("grounding_status"),
            "grounding_score": vd.get("grounding_score"),
            "source_quality_gate": vd.get("source_quality_gate"),
            "corpus_gap_detected": vd.get("corpus_gap_detected"),
            "diagnosis": vd.get("diagnosis"),
            "verifier_version": vd.get("verifier_version"),
            "critical_terms_count": len(vd.get("critical_terms") or []),
            "matched_critical_count": len(vd.get("matched_critical_terms") or []),
            "support_terms_count": len(vd.get("support_terms") or []),
            "matched_support_count": len(vd.get("matched_support_terms") or []),
            "example_terms_count": len(vd.get("example_terms") or []),
            "matched_example_count": len(vd.get("matched_example_terms") or []),
        })

    return results


# ═══════════════════════════════════════════════════════════════
# B. API 端点验证 (需要服务运行)
# ═══════════════════════════════════════════════════════════════

def _run_api_verification(base_url: str) -> list[dict[str, Any]] | None:
    """调用 /enterprise/agent/query 验证（需要 USE_FAKE_MODEL=true）。"""
    import urllib.error
    import urllib.request

    url = f"{base_url.rstrip('/')}/enterprise/agent/query"
    cases = [
        {
            "id": "api_fastapi",
            "query": "FastAPI 里 Request Body 如何定义？",
        },
        {
            "id": "api_lora",
            "query": "LoRA 有什么作用？",
        },
    ]

    results: list[dict[str, Any]] = []
    for case in cases:
        payload = json.dumps({
            "query": case["query"],
            "top_k": 5,
            "return_sources": True,
        }, ensure_ascii=False).encode("utf-8")

        try:
            req = urllib.request.Request(
                url, data=payload,
                headers={"Content-Type": "application/json", "Accept": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:
            results.append({
                "id": case["id"],
                "query": case["query"],
                "api_error": f"{type(exc).__name__}: {str(exc)[:200]}",
            })
            continue

        sources = body.get("sources") or []
        vd = body.get("verifier_debug") or {}
        source_ids = [s.get("source_id", "") for s in sources]
        source_unknown = sum(1 for s in sources if s.get("source") == "unknown")

        results.append({
            "id": case["id"],
            "query": case["query"],
            "source_id_sequence": source_ids[:5],
            "source_unknown_count": source_unknown,
            "grounding_status": vd.get("grounding_status"),
            "grounding_score": vd.get("grounding_score"),
            "source_quality_gate": vd.get("source_quality_gate"),
            "corpus_gap_detected": vd.get("corpus_gap_detected"),
            "diagnosis": vd.get("diagnosis"),
            "verifier_version": vd.get("verifier_version"),
            "answer_preview": (body.get("answer") or "")[:200],
            "fallback_triggered": (body.get("fallback") or {}).get("triggered", False),
        })

    return results


# ═══════════════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════════════

def main() -> None:
    args = _parse_args()
    now = datetime.now(DATETIME_UTC).isoformat()

    report: dict[str, Any] = {
        "generated_at": now,
        "verifier_version": "v2_weighted_rule_based",
        "calls_llm": False,
        "writes_chroma": False,
        "execute": args.execute,
    }

    # A. 离线 verifier 验证
    print("[信息] 运行离线 Evidence Verifier V2 验证...")
    offline_results = _run_retrieval_verification()
    report["offline_verification"] = offline_results

    # 汇总
    statuses = Counter(r.get("grounding_status") for r in offline_results)
    report["offline_summary"] = {
        "total_cases": len(offline_results),
        "grounding_status_distribution": dict(statuses),
        "corpus_gap_count": sum(1 for r in offline_results if r.get("corpus_gap_detected")),
    }

    # 打印验收结果
    for r in offline_results:
        status = r.get("grounding_status", "?")
        gate = r.get("source_quality_gate", "none")
        gap = " [语料缺口]" if r.get("corpus_gap_detected") else ""
        unknown = r.get("source_unknown_count", 0)
        print(f"  [{r['id']}] status={status} gate={gate} score={r.get('grounding_score', 0):.3f} unknown_src={unknown}{gap}")
        print(f"           source_ids={r.get('source_id_sequence', [])[:3]}")

    # B. API 验证（可选）
    if args.execute:
        print("\n[信息] 运行 API 端点验证...")
        api_results = _run_api_verification(args.base_url)
        report["api_verification"] = api_results
        for r in (api_results or []):
            if r.get("api_error"):
                print(f"  [{r['id']}] ERROR: {r['api_error']}")
            else:
                print(f"  [{r['id']}] status={r.get('grounding_status')} score={r.get('grounding_score', 0):.3f}")

    # 写入输出
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"\n[信息] 验证报告已写入: {output_path}")


if __name__ == "__main__":
    main()
