from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[1]
EVAL_DIR = ROOT_DIR / "data" / "knowledge_base" / "evaluation"
DEFAULT_CASES_PATH = EVAL_DIR / "phase6d_intent_cases.jsonl"
DEFAULT_RESULTS_PATH = EVAL_DIR / "phase6d_intent_eval_results.jsonl"
DEFAULT_SUMMARY_PATH = EVAL_DIR / "phase6d_intent_eval_summary.json"
DEFAULT_BAD_CASES_PATH = EVAL_DIR / "phase6d_intent_bad_cases.jsonl"

INTENT_TO_ROUTE = {
    "knowledge_lookup": "rag_retrieval",
    "exact_lookup": "exact_or_metadata_lookup",
    "business_action": "business_tool_router",
    "chit_chat": "chat_response",
    "summarization_or_rewrite": "writing_or_summary",
    "unsupported": "refusal_or_safety",
    "clarification_needed": "ask_clarification",
}

INTENT_ORDER = [
    "knowledge_lookup",
    "exact_lookup",
    "business_action",
    "chit_chat",
    "summarization_or_rewrite",
    "unsupported",
    "clarification_needed",
]

HIGH_RISK_MISROUTES = {
    ("business_action", "knowledge_lookup"),
    ("unsupported", "business_action"),
    ("unsupported", "knowledge_lookup"),
    ("exact_lookup", "knowledge_lookup"),
    ("clarification_needed", "knowledge_lookup"),
    ("clarification_needed", "business_action"),
}

RULES: list[tuple[str, re.Pattern[str], str]] = [
    (
        "unsupported",
        re.compile(
            r"破解|绕过权限|绕过登录|窃取|盗取|攻击|伪造|删除审计|密码|"
            r"真实访问密钥|股票.*一定|production credential|bypass access control|unauthorized",
            re.IGNORECASE,
        ),
        "matched safety or unsupported pattern",
    ),
    (
        "clarification_needed",
        re.compile(
            r"那个|它|刚才|继续|帮我处理一下|这个怎么|再来一个|上一条|"
            r"这个有没有问题|previous one|that config|do the same",
            re.IGNORECASE,
        ),
        "matched ambiguous reference pattern",
    ),
    (
        "summarization_or_rewrite",
        re.compile(
            r"总结|改写|润色|写一封邮件|换一种|整理成|翻译成|压缩到|"
            r"改得|改成.*表达|面试表达|rewrite|summarize|polish|bullet points|professional tone",
            re.IGNORECASE,
        ),
        "matched writing or summarization pattern",
    ),
    (
        "business_action",
        re.compile(
            r"创建.*订单|加入黑名单|订单号|物流状态|发送退款通知|标记为高风险|"
            r"cancel invoice|订单状态|新建.*工单|客户.*账户状态|refund notice|"
            r"更新.*联系方式|标记为已处理",
            re.IGNORECASE,
        ),
        "matched business action pattern",
    ),
    (
        "exact_lookup",
        re.compile(
            r"chunk_id|source_id|doc_id|collection_name|doc_type|ingest_candidate|"
            r"metadata|review_status|sample_id|source_catalog|chunk_quality_report|"
            r"endpoint|api 名称|api name|language=|duplicate_chunk_hash_count",
            re.IGNORECASE,
        ),
        "matched exact metadata lookup pattern",
    ),
    (
        "chit_chat",
        re.compile(
            r"^你好$|你是谁|讲个笑话|心情不好|hello|早上好|聊聊天|thanks|"
            r"哈哈|你会做什么|good morning|辛苦了",
            re.IGNORECASE,
        ),
        "matched chat pattern",
    ),
    (
        "knowledge_lookup",
        re.compile(
            r"激活函数|RAG|向量检索|Transformer|自注意力|FastAPI|Request Body|"
            r"NLP|分词|LSTM|GRU|PyTorch|training loop|Agent|BEIR|reranker|"
            r"向量数据库|knowledge|retrieval|深度学习",
            re.IGNORECASE,
        ),
        "matched technical knowledge pattern",
    ),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Phase 6D-1 deterministic intent evaluation.")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS_PATH)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY_PATH)
    parser.add_argument("--bad-cases", type=Path, default=DEFAULT_BAD_CASES_PATH)
    return parser.parse_args()


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            if line.strip():
                row = json.loads(line)
                if "case_id" not in row or "query" not in row or "expected_intent" not in row:
                    raise ValueError(f"Invalid case row at {path}:{line_number}")
                rows.append(row)
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def classify_intent(query: str) -> tuple[str, str]:
    normalized_query = " ".join(query.strip().split())
    for intent, pattern, reason in RULES:
        if pattern.search(normalized_query):
            return intent, reason
    return "clarification_needed", "fallback to clarification for uncertain query"


def compute_macro_f1(per_intent_f1: dict[str, float]) -> float:
    if not per_intent_f1:
        return 0.0
    return round(sum(per_intent_f1.values()) / len(per_intent_f1), 4)


def build_metrics(results: list[dict[str, Any]]) -> dict[str, Any]:
    expected_distribution = Counter(row["expected_intent"] for row in results)
    predicted_distribution = Counter(row["predicted_intent"] for row in results)
    confusion: dict[str, dict[str, int]] = {intent: {} for intent in INTENT_ORDER}

    for row in results:
        expected = row["expected_intent"]
        predicted = row["predicted_intent"]
        confusion.setdefault(expected, {})
        confusion[expected][predicted] = confusion[expected].get(predicted, 0) + 1

    per_intent_precision: dict[str, float] = {}
    per_intent_recall: dict[str, float] = {}
    per_intent_f1: dict[str, float] = {}
    for intent in INTENT_ORDER:
        true_positive = sum(
            1
            for row in results
            if row["expected_intent"] == intent and row["predicted_intent"] == intent
        )
        false_positive = sum(
            1
            for row in results
            if row["expected_intent"] != intent and row["predicted_intent"] == intent
        )
        false_negative = sum(
            1
            for row in results
            if row["expected_intent"] == intent and row["predicted_intent"] != intent
        )
        precision_denominator = true_positive + false_positive
        recall_denominator = true_positive + false_negative
        precision = true_positive / precision_denominator if precision_denominator else 0.0
        recall = true_positive / recall_denominator if recall_denominator else 0.0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        per_intent_precision[intent] = round(precision, 4)
        per_intent_recall[intent] = round(recall, 4)
        per_intent_f1[intent] = round(f1, 4)

    correct_count = sum(1 for row in results if row["correct"])
    high_risk_count = sum(1 for row in results if row["high_risk_misroute"])

    return {
        "case_count": len(results),
        "accuracy": round(correct_count / len(results), 4) if results else 0.0,
        "macro_f1": compute_macro_f1(per_intent_f1),
        "intent_distribution": dict(sorted(expected_distribution.items())),
        "predicted_distribution": dict(sorted(predicted_distribution.items())),
        "per_intent_precision": per_intent_precision,
        "per_intent_recall": per_intent_recall,
        "per_intent_f1": per_intent_f1,
        "confusion_matrix": confusion,
        "bad_case_count": len(results) - correct_count,
        "high_risk_misroute_count": high_risk_count,
        "calls_llm": False,
        "writes_chroma": False,
        "modifies_agent": False,
        "calls_api": False,
        "loads_embedding_model": False,
    }


def build_bad_case(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "case_id": row["case_id"],
        "query": row["query"],
        "expected_intent": row["expected_intent"],
        "predicted_intent": row["predicted_intent"],
        "expected_route": row["expected_route"],
        "predicted_route": row["predicted_route"],
        "high_risk_misroute": row["high_risk_misroute"],
        "diagnosis": (
            f"Expected {row['expected_intent']} but predicted {row['predicted_intent']}; "
            f"classifier reason: {row['reason']}"
        ),
    }


def run_eval(cases: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    results: list[dict[str, Any]] = []
    by_intent_reason_count: dict[str, Counter[str]] = defaultdict(Counter)

    for case in cases:
        predicted_intent, reason = classify_intent(case["query"])
        predicted_route = INTENT_TO_ROUTE[predicted_intent]
        expected_intent = case["expected_intent"]
        expected_route = case.get("expected_route", INTENT_TO_ROUTE.get(expected_intent, "unknown"))
        high_risk = (expected_intent, predicted_intent) in HIGH_RISK_MISROUTES
        result = {
            "case_id": case["case_id"],
            "query": case["query"],
            "expected_intent": expected_intent,
            "predicted_intent": predicted_intent,
            "expected_route": expected_route,
            "predicted_route": predicted_route,
            "correct": expected_intent == predicted_intent and expected_route == predicted_route,
            "high_risk_misroute": high_risk,
            "reason": reason,
        }
        results.append(result)
        by_intent_reason_count[predicted_intent][reason] += 1

    bad_cases = [build_bad_case(row) for row in results if not row["correct"]]
    summary = build_metrics(results)
    summary["rule_reason_distribution"] = {
        intent: dict(counter) for intent, counter in sorted(by_intent_reason_count.items())
    }
    return results, bad_cases, summary


def main() -> None:
    args = parse_args()
    cases = load_jsonl(args.cases)
    results, bad_cases, summary = run_eval(cases)
    write_jsonl(args.results, results)
    write_jsonl(args.bad_cases, bad_cases)
    write_json(args.summary, summary)

    print(f"case_count={summary['case_count']}")
    print(f"accuracy={summary['accuracy']}")
    print(f"macro_f1={summary['macro_f1']}")
    print(f"bad_case_count={summary['bad_case_count']}")
    print(f"high_risk_misroute_count={summary['high_risk_misroute_count']}")
    print(f"results={args.results}")
    print(f"summary={args.summary}")
    print(f"bad_cases={args.bad_cases}")


if __name__ == "__main__":
    main()
