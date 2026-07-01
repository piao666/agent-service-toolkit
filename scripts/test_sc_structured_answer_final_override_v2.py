"""source_catalog structured answer final override 最小验证 v2。
用法 (HPC):
  SOURCE_CATALOG_PATCH_ENABLED=true \
  SOURCE_CATALOG_STRUCTURED_ANSWER_ENABLED=true \
  python scripts/test_sc_structured_answer_final_override_v2.py \
    --base-url http://127.0.0.1:8011 --timeout 120 \
    --output-dir data/knowledge_base/evaluation/sc_final_override_v2
"""
import argparse, json, csv, time, urllib.request, sys
from datetime import datetime, timezone
from pathlib import Path

try:
    from datetime import UTC as DT_UTC
except ImportError:
    DT_UTC = timezone.utc

# ── 评估常量 ──
EXPECTED_MAPPING = {
    "agent_workflow": ["langgraph_docs"],
    "ai_agent": ["local_ai_agent_course_pdf"],
    "ai_risk_management": ["nist_ai_rmf_docs"],
    "api_backend": ["fastapi_docs"],
    "deep_learning": ["local_deep_learning_course_docx", "pytorch_docs"],
    "llm_security": ["owasp_llm_security_docs"],
    "model_serving": ["vllm_docs"],
    "nlp": ["local_nlp_course_docx"],
    "orchestration": ["kubernetes_cn_docs"],
    "programming_language": ["python_cn_docs"],
    "retrieval_augmented_generation": ["rag_arxiv_papers"],
    "retrieval_evaluation": ["retrieval_eval_papers"],
    "transformer_models": ["huggingface_transformers_docs", "transformer_arxiv_papers"],
    "vector_database": ["chroma_docs"],
}
DOMAINS = list(EXPECTED_MAPPING.keys())
INSUFFICIENT = [
    "上下文不足", "未完整", "无法确定", "中断", "未列出",
    "知识库中没有", "不能完整回答", "不足以", "没有足够依据",
]

# ── 测试用例 ──
POSITIVES = [
    ("exp_099", "source_catalog.yaml 中 domain 字段有哪些取值？"),
    ("exp_224", "source_catalog 中哪些 domain，每个 domain 有哪些 source？"),
    ("pos_3", "source_catalog.yaml 里有哪些 source_id？"),
    ("pos_4", "每个 domain 下有哪些 source_id？"),
]
NEGATIVES = [
    ("neg_1", "domain adaptation 是什么？"),
    ("neg_2", "FastAPI domain model 是什么？"),
    ("neg_3", "RAG source tracing 是什么？"),
    ("neg_4", "Python source code 如何组织？"),
    ("neg_5", "Transformer source-target attention 是什么？"),
    ("neg_6", "数据库 domain modeling 是什么？"),
    ("neg_7", "domain driven design 是什么？"),
    ("neg_8", "FastAPI 中的 dependency source 是什么？"),
]
REGRESSIONS = [
    ("reg_1", "RAG 是什么？"),
    ("reg_2", "FastAPI Request Body 如何定义？"),
    ("reg_3", "Python 装饰器是什么？"),
]


def now_iso():
    return datetime.now(DT_UTC).isoformat()


def check_positive(case_id, answer):
    """严格检查: exp_099 检查所有 domain；exp_224 检查所有 domain+source 映射。"""
    ans_lower = answer.lower()
    missing_d = [d for d in DOMAINS if d.lower() not in ans_lower]

    missing_s = {}
    if case_id != "exp_099":  # exp_099 只问 domain 列表
        for domain, sources in EXPECTED_MAPPING.items():
            if domain.lower() in ans_lower:
                for src in sources:
                    if src.lower() not in ans_lower:
                        missing_s.setdefault(domain, []).append(src)

    missing_d = sorted(set(missing_d))
    insuff = [ph for ph in INSUFFICIENT if ph.lower() in ans_lower]
    ok = len(missing_d) == 0 and len(missing_s) == 0 and len(insuff) == 0
    return ok, missing_d, missing_s, insuff


def api_call(url, query, timeout):
    payload = json.dumps({"query": query, "top_k": 5}).encode()
    req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
    t0 = time.time()
    resp = urllib.request.urlopen(req, timeout=timeout)
    data = json.loads(resp.read())
    latency = round(time.time() - t0, 2)
    return data, latency


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--base-url", default="http://127.0.0.1:8011")
    p.add_argument("--timeout", type=int, default=120)
    p.add_argument("--output-dir", required=True)
    args = p.parse_args()

    url = f"{args.base_url}/enterprise/agent/query"
    od = Path(args.output_dir)
    od.mkdir(parents=True, exist_ok=True)
    results = []

    # ── Positive cases ──
    for cid, query in POSITIVES:
        print(f"[+] {cid}: {query[:80]}...")
        try:
            data, latency = api_call(url, query, args.timeout)
        except Exception as e:
            data, latency = {}, 0
            print(f"    ERROR: {e}")

        answer = str(data.get("answer", ""))
        rd = data.get("retrieval_debug", {})
        gd = data.get("graph_debug", data.get("metadata", {}).get("graph_debug", {}))
        md = data.get("model_debug", {})

        ok, md_list, ms, insuff = check_positive(cid, answer)
        sa_final = gd.get("structured_answer_final_override_used", False)
        ag = gd.get("answer_generator", md.get("answer_generator", "unknown"))
        calls_llm = gd.get("calls_llm_for_answer", gd.get("calls_llm"))
        sa_built = rd.get("structured_answer_built", gd.get("structured_answer_built", False))
        sa_ctx = rd.get("structured_answer_context_injected", gd.get("structured_answer_context_injected", False))

        r = {
            "case_id": cid, "type": "positive", "query": query,
            "http_status": 200, "latency_seconds": latency,
            "strict_pass": ok,
            "answer_full": answer,
            "answer_preview": answer[:300],
            "answer_chars": len(answer),
            "structured_answer_final_override_used": sa_final,
            "structured_answer_built": sa_built,
            "structured_answer_context_injected": sa_ctx,
            "answer_generator": ag,
            "calls_llm_for_answer": calls_llm,
            "missing_domains": md_list,
            "missing_domains_count": len(md_list),
            "missing_sources": ms,
            "missing_sources_total": sum(len(v) for v in ms.values()),
            "insufficient_phrases": insuff,
            "insufficient_phrases_count": len(insuff),
            "retrieval_debug": rd,
            "graph_debug": gd,
            "model_debug": md,
        }
        results.append(r)
        status = "PASS" if ok else "FAIL"
        print(f"    {status} | sa_final={sa_final} | ag={ag} | calls_llm={calls_llm} | miss_d={len(md_list)} | miss_s={sum(len(v) for v in ms.values())} | insuff={len(insuff)}")

    # ── Negative + Regression cases ──
    for cid, query in NEGATIVES + REGRESSIONS:
        typ = "negative" if cid in [n[0] for n in NEGATIVES] else "regression"
        print(f"[{typ[0]}] {cid}: {query[:80]}...")
        try:
            data, latency = api_call(url, query, args.timeout)
        except Exception as e:
            data, latency = {}, 0
            print(f"    ERROR: {e}")

        rd = data.get("retrieval_debug", {})
        gd = data.get("graph_debug", data.get("metadata", {}).get("graph_debug", {}))
        sa = gd.get("structured_answer_used", rd.get("structured_answer_used", False))
        sc = rd.get("source_catalog_route_triggered", False)
        ok = not sa and not sc

        r = {
            "case_id": cid, "type": typ, "query": query,
            "pass": ok,
            "structured_answer_used": sa,
            "source_catalog_triggered": sc,
            "answer_preview": str(data.get("answer", ""))[:200],
        }
        results.append(r)
        if not ok:
            print(f"    FAIL (sa={sa}, sc={sc})")
        else:
            print(f"    PASS")

    # ── 写入结果 ──
    raw_path = od / "sc_final_override_v2_raw_results.jsonl"
    with open(raw_path, "w", encoding="utf-8", newline="\n") as f:
        for r in results:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    pos_pass = sum(1 for r in results if r["type"] == "positive" and r.get("strict_pass", r.get("pass")))
    neg_pass = sum(1 for r in results if r["type"] == "negative" and r["pass"])
    reg_pass = sum(1 for r in results if r["type"] == "regression" and r["pass"])

    # ── exp_099 / exp_224 硬性检查 (加严版) ──
    exp_099 = next((r for r in results if r["case_id"] == "exp_099"), {})
    exp_224 = next((r for r in results if r["case_id"] == "exp_224"), {})

    # 五条硬性判定准则
    _h1 = exp_224.get("answer_generator") == "source_catalog_structured_answer"
    _h2 = exp_224.get("calls_llm_for_answer") is False  # 必须是 false，不是 None
    _h3 = exp_224.get("structured_answer_final_override_used") is True  # 必须是 true
    _h4 = exp_224.get("strict_pass") is True
    _h5 = pos_pass == 4 and neg_pass == 8 and reg_pass == 3

    hard_checks = {
        "H1_answer_generator_source_catalog_structured_answer": _h1,
        "H2_calls_llm_for_answer_explicit_false": _h2,
        "H3_structured_answer_final_override_used_explicit_true": _h3,
        "H4_exp_224_strict_pass": _h4,
        "H5_all_15_pass": _h5,
    }

    final_decision = "PASS" if all(hard_checks.values()) else "FAIL"

    known_failures = []
    for label, ok in hard_checks.items():
        if not ok:
            if label == "H1_answer_generator_source_catalog_structured_answer":
                known_failures.append(f"H1: answer_generator={exp_224.get('answer_generator')} (expected source_catalog_structured_answer)")
            elif label == "H2_calls_llm_for_answer_explicit_false":
                known_failures.append(f"H2: calls_llm_for_answer={exp_224.get('calls_llm_for_answer')} (expected explicit False)")
            elif label == "H3_structured_answer_final_override_used_explicit_true":
                known_failures.append(f"H3: structured_answer_final_override_used={exp_224.get('structured_answer_final_override_used')} (expected explicit True)")
            elif label == "H4_exp_224_strict_pass":
                known_failures.append(f"H4: strict_pass={exp_224.get('strict_pass')} (missing_d={exp_224.get('missing_domains_count')}, missing_s={exp_224.get('missing_sources_total')}, insuff={exp_224.get('insufficient_phrases_count')})")
            elif label == "H5_all_15_pass":
                known_failures.append(f"H5: pos={pos_pass}/4, neg={neg_pass}/8, reg={reg_pass}/3")

    summary = {
        "generated_at": now_iso(),
        "test_name": "source_catalog_structured_answer_final_override_v2",
        "positive_count": len(POSITIVES), "positive_pass": pos_pass,
        "negative_count": len(NEGATIVES), "negative_pass": neg_pass, "negative_fp": len(NEGATIVES) - neg_pass,
        "regression_count": len(REGRESSIONS), "regression_pass": reg_pass,
        "exp_099": {
            "strict_pass": exp_099.get("strict_pass"),
            "structured_answer_final_override_used": exp_099.get("structured_answer_final_override_used"),
            "answer_generator": exp_099.get("answer_generator"),
            "calls_llm_for_answer": exp_099.get("calls_llm_for_answer"),
        },
        "exp_224": {
            "strict_pass": exp_224.get("strict_pass"),
            "structured_answer_final_override_used": exp_224.get("structured_answer_final_override_used"),
            "answer_generator": exp_224.get("answer_generator"),
            "calls_llm_for_answer": exp_224.get("calls_llm_for_answer"),
            "missing_domains": exp_224.get("missing_domains"),
            "missing_sources": exp_224.get("missing_sources"),
            "insufficient_phrases": exp_224.get("insufficient_phrases"),
        },
        "final_decision": final_decision,
        "hard_checks": hard_checks,
        "known_failures": known_failures,
        "modified_files": [
            "src/agents/enterprise_rag_graph.py",
            "src/agents/enterprise_tools.py",
        ],
    }
    summary_path = od / "sc_final_override_v2_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    # CSV
    csv_fields = ["case_id", "type", "query", "strict_pass", "pass",
                  "structured_answer_final_override_used", "answer_generator",
                  "calls_llm_for_answer", "missing_domains_count", "insufficient_phrases_count"]
    csv_path = od / "sc_final_override_v2_review.csv"
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=csv_fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(results)

    print(f"\n{'='*60}")
    print(f"[完成] pos={pos_pass}/{len(POSITIVES)}  neg={neg_pass}/{len(NEGATIVES)}  reg={reg_pass}/{len(REGRESSIONS)}")
    print(f"[决策] {final_decision}")
    if known_failures:
        for kf in known_failures:
            print(f"  [KNOWN_FAILURE] {kf}")
    print(f"[输出] {raw_path}")
    print(f"[输出] {summary_path}")
    print(f"[输出] {csv_path}")

    return 0 if final_decision == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
