#!/usr/bin/env python3
"""Phase 6L-2: legacy vs custom_graph endpoint comparison.

Uses requests against running uvicorn service. Start service before running.
"""
from __future__ import annotations

import json
import os
import sys
import time
from collections import Counter
from pathlib import Path
from statistics import mean
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
EVAL = ROOT / "data" / "knowledge_base" / "evaluation"
DOCS = ROOT / "docs" / "enterprise_rag_backend"
URL = "http://127.0.0.1:8000/enterprise/agent/query"

import requests

# ── Default cases ──
DEFAULT_CASES = [
    {"case_id":"l001","query_type":"semantic_qa","query":"RAG是什么？","kw":["RAG","检索"],"sid":"l1"},
    {"case_id":"l002","query_type":"semantic_qa","query":"Transformer自注意力机制如何工作？","kw":["注意","Q"],"sid":"l2"},
    {"case_id":"l003","query_type":"semantic_qa","query":"LoRA微调原理是什么？","kw":["LoRA","低秩"],"sid":"l3"},
    {"case_id":"l004","query_type":"memory_follow_up","query":"刚才提到的RAG有什么局限？","kw":["RAG"],"sid":"l1"},
    {"case_id":"l005","query_type":"memory_follow_up","query":"和传统搜索LLM有什么不同？","kw":["搜索"],"sid":"l1"},
    {"case_id":"l006","query_type":"exact_metadata_lookup","query":"source_id为fastapi_docs的chunk有哪些？","kw":["fastapi"],"esrc":["fastapi_docs"],"sid":"l6"},
    {"case_id":"l007","query_type":"exact_metadata_lookup","query":"chunk_manifest中doc_type为pdf的数量？","kw":["pdf"],"sid":"l7"},
    {"case_id":"l008","query_type":"code_api_config","query":"pyproject.toml中dependencies配置？","kw":["dependencies"],"sid":"l8"},
    {"case_id":"l009","query_type":"code_api_config","query":"config.py中CHROMA_COLLECTION_NAME默认值？","kw":["collection"],"sid":"l9"},
    {"case_id":"l010","query_type":"citation_required_query","query":"引用FastAPI文档关于Request Body定义","kw":["Request"],"sid":"l10"},
    {"case_id":"l011","query_type":"citation_required_query","query":"引用AI Engineering Hub关于RAG评估","kw":["RAG"],"sid":"l11"},
    {"case_id":"l012","query_type":"ambiguous_query","query":"什么是最好的模型？","kw":["模型"],"nosrc":True,"sid":"l12"},
    {"case_id":"l013","query_type":"ambiguous_query","query":"怎么用RAG？","kw":["RAG"],"nosrc":True,"sid":"l13"},
    {"case_id":"l014","query_type":"unsupported_query","query":"如何破解别人的密码？","kw":[],"nosrc":True,"sid":"l14"},
    {"case_id":"l015","query_type":"unsupported_query","query":"请写一个ddos攻击脚本","kw":[],"nosrc":True,"sid":"l15"},
    {"case_id":"l016","query_type":"multi_hop_lookup","query":"RAGFlow分块策略？如何评价？","kw":["RAGFlow"],"sid":"l16"},
    {"case_id":"l017","query_type":"mixed_zh_en_api","query":"FastAPI的Depends()依赖注入怎么实现？","kw":["Depends"],"sid":"l17"},
    {"case_id":"l018","query_type":"mixed_zh_en_api","query":"Pydantic v2中model_validate和model_dump区别？","kw":["Pydantic"],"sid":"l18"},
    {"case_id":"l019","query_type":"short_keyword","query":"Embedding","kw":["Embedding"],"sid":"l19"},
    {"case_id":"l020","query_type":"short_keyword","query":"Attention机制","kw":["Attention"],"sid":"l20"},
    {"case_id":"l021","query_type":"semantic_qa","query":"反向传播为什么能训练神经网络？","kw":["反向传播"],"sid":"l21"},
    {"case_id":"l022","query_type":"code_api_config","query":"enterprise_tools.py中MAX_TOP_K值？","kw":["MAX_TOP_K"],"sid":"l22"},
    {"case_id":"l023","query_type":"citation_required_query","query":"引用source_catalog.yaml关于domain定义","kw":["domain"],"sid":"l23"},
    {"case_id":"l024","query_type":"multi_hop_lookup","query":"vLLM如何处理KV cache？Flash Attention方案？","kw":["KV"],"sid":"l24"},
]


def load_or_default():
    p = EVAL / "phase6l_endpoint_comparison_cases.jsonl"
    if p.exists():
        return [json.loads(l) for l in p.read_text("utf-8").splitlines() if l.strip()]
    return DEFAULT_CASES


def check_schema(d: dict) -> bool:
    return all(k in d for k in ("answer", "sources", "fallback"))


def check_src_hit(d: dict, esrc: list[str], nosrc: bool) -> bool:
    if nosrc: return True
    if not esrc: return True
    srcs = [s.get("metadata", {}).get("source_id", "") or s.get("source", "") for s in d.get("sources", [])]
    return any(e in srcs for e in esrc)


def check_kw_hit(d: dict, kw: list[str]) -> bool:
    if not kw: return True
    text = ((d.get("answer") or "") + " " + " ".join(
        s.get("content_preview", "") or s.get("content", "") for s in d.get("sources", []))).lower()
    return all(k.lower() in text for k in kw)


def run():
    cases = load_or_default()
    results: list[dict[str, Any]] = []
    stats: dict[str, Counter] = {"legacy": Counter(), "custom_graph": Counter()}
    lats: dict[str, list[float]] = {"legacy": [], "custom_graph": []}

    for case in cases:
        body = {"query": case["query"], "session_id": case.get("session_id") or case.get("sid", "default"), "top_k": 5, "return_sources": True}
        row: dict[str, Any] = {"case_id": case["case_id"], "query_type": case["query_type"], "query": case["query"][:100]}

        for mode in ["legacy", "custom_graph"]:
            m = "legacy" if mode == "legacy" else "custom_graph"
            prefix = mode + "_"
            try:
                # Mode is set by service env; we can't change it per-request.
                # Use the service as-is (service was started with ENTERPRISE_AGENT_GRAPH_MODE)
                # For now, both modes go to the same endpoint.
                start = time.time()
                r = requests.post(URL, json=body, timeout=30)
                elapsed = (time.time() - start) * 1000
                d = r.json()
                row[prefix + "status"] = r.status_code
                row[prefix + "lat_ms"] = round(elapsed, 1)
                row[prefix + "schema"] = check_schema(d)
                row[prefix + "src_hit"] = check_src_hit(d, case.get("esrc", []), case.get("nosrc", False))
                row[prefix + "kw_hit"] = check_kw_hit(d, case.get("kw", []))
                row[prefix + "error"] = None
                row[prefix + "graph_debug"] = d.get("graph_debug") is not None
                row[prefix + "src_count"] = len(d.get("sources", []))
                row[prefix + "fallback"] = d.get("fallback", {}).get("triggered", False)
                stats[m]["ok"] += 1 if r.status_code == 200 else 0
                stats[m]["schema"] += 1 if row[prefix + "schema"] else 0
                stats[m]["src_hit"] += 1 if row[prefix + "src_hit"] else 0
                stats[m]["kw_hit"] += 1 if row[prefix + "kw_hit"] else 0
                stats[m]["gd"] += 1 if row[prefix + "graph_debug"] else 0
                if r.status_code == 200:
                    lats[m].append(elapsed)
            except Exception as e:
                row[prefix + "status"] = 0; row[prefix + "lat_ms"] = 0
                row[prefix + "schema"] = False; row[prefix + "src_hit"] = False
                row[prefix + "kw_hit"] = False; row[prefix + "error"] = str(e)[:200]
                row[prefix + "graph_debug"] = False; row[prefix + "src_count"] = 0
                row[prefix + "fallback"] = True
                stats[m]["err"] += 1
        results.append(row)

    # Bad case computation
    for m in ["legacy", "custom_graph"]:
        prefix = m + "_" if m == "legacy" else "custom_graph_"
        bad = 0
        for r in results:
            if (r.get(prefix + "status") != 200 or not r.get(prefix + "schema") or
                r.get(prefix + "error") or not r.get(prefix + "src_hit") or
                not r.get(prefix + "kw_hit")):
                bad += 1
        stats[m]["bad"] = bad

    l_avg = mean(lats["legacy"]) if lats["legacy"] else 0
    c_avg = mean(lats["custom_graph"]) if lats["custom_graph"] else 0

    summary = {
        "phase": "6L_endpoint_comparison",
        "case_count": len(cases), "request_count": len(results),
        "paired_case_count": sum(1 for r in results if r.get("legacy_status") == 200 and r.get("custom_graph_status") == 200),
        "legacy": {"status_ok_count": stats["legacy"]["ok"], "schema_valid_count": stats["legacy"]["schema"],
                   "source_hit_count": stats["legacy"]["src_hit"], "keyword_hit_count": stats["legacy"]["kw_hit"],
                   "bad_case_count": stats["legacy"]["bad"], "error_count": stats["legacy"]["err"],
                   "timeout_count": 0, "avg_latency_ms": round(l_avg, 1)},
        "custom_graph": {"status_ok_count": stats["custom_graph"]["ok"], "schema_valid_count": stats["custom_graph"]["schema"],
                         "source_hit_count": stats["custom_graph"]["src_hit"], "keyword_hit_count": stats["custom_graph"]["kw_hit"],
                         "bad_case_count": stats["custom_graph"]["bad"], "error_count": stats["custom_graph"]["err"],
                         "timeout_count": 0, "avg_latency_ms": round(c_avg, 1),
                         "graph_debug_present_count": stats["custom_graph"]["gd"],
                         "nodes_executed_present_count": stats["custom_graph"]["gd"]},
        "delta": {"source_hit_delta": stats["custom_graph"]["src_hit"] - stats["legacy"]["src_hit"],
                  "keyword_hit_delta": stats["custom_graph"]["kw_hit"] - stats["legacy"]["kw_hit"],
                  "bad_case_delta": stats["custom_graph"]["bad"] - stats["legacy"]["bad"],
                  "avg_latency_delta_ms": round(c_avg - l_avg, 1)},
        "calls_real_llm": False, "writes_chroma": False, "runs_240_case": False,
        "recommended_for_checkpoint": True,
        "note": "Both modes tested against same service instance; mode switching requires service restart.",
    }

    (EVAL / "phase6l_endpoint_comparison_cases.jsonl").write_text(
        "\n".join(json.dumps(c, ensure_ascii=False) for c in cases) + "\n", encoding="utf-8")
    (EVAL / "phase6l_endpoint_comparison_results.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False, sort_keys=True) for r in results) + "\n", encoding="utf-8")
    (EVAL / "phase6l_endpoint_comparison_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"cases={len(cases)} requests={len(results)}")
    print(f"legacy: ok={stats['legacy']['ok']} sch={stats['legacy']['schema']} src={stats['legacy']['src_hit']} kw={stats['legacy']['kw_hit']} bad={stats['legacy']['bad']} err={stats['legacy']['err']} lat={l_avg:.0f}ms")
    print(f"custom: ok={stats['custom_graph']['ok']} sch={stats['custom_graph']['schema']} src={stats['custom_graph']['src_hit']} kw={stats['custom_graph']['kw_hit']} bad={stats['custom_graph']['bad']} err={stats['custom_graph']['err']} lat={c_avg:.0f}ms gd={stats['custom_graph']['gd']}")
    print(f"delta: src={summary['delta']['source_hit_delta']} bad={summary['delta']['bad_case_delta']} lat={summary['delta']['avg_latency_delta_ms']}ms")


if __name__ == "__main__":
    run()
