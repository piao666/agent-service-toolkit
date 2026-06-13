from __future__ import annotations

import argparse
import json
import re
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any

try:
    from datetime import UTC as DATETIME_UTC
except ImportError:  # pragma: no cover - Python 3.10 compatibility.
    DATETIME_UTC = timezone.utc  # noqa: UP017


ROOT_DIR = Path(__file__).resolve().parents[1]
EVAL_DIR = ROOT_DIR / "data" / "knowledge_base" / "evaluation"
DEFAULT_CASES_PATH = EVAL_DIR / "phase6d_agent_api_cases.jsonl"
DEFAULT_RESULTS_PATH = EVAL_DIR / "phase6d_agent_api_results.jsonl"
DEFAULT_SUMMARY_PATH = EVAL_DIR / "phase6d_agent_api_summary.json"
DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_ENDPOINT = "/enterprise/agent/query"
TOP_K = 5
ANSWER_PREVIEW_CHARS = 180
SOURCE_PREVIEW_CHARS = 140
ERROR_PREVIEW_CHARS = 220
REQUIRED_RESPONSE_KEYS = {
    "answer",
    "sources",
    "retrieval_debug",
    "latency_ms",
    "model_debug",
    "fallback",
    "session_id",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run Phase 6D-6 Agent/API endpoint evaluation.")
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    parser.add_argument("--results", type=Path, default=DEFAULT_RESULTS_PATH)
    parser.add_argument("--summary", type=Path, default=DEFAULT_SUMMARY_PATH)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--timeout", type=float, default=60.0)
    parser.add_argument("--limit-cases", type=int, default=0)
    parser.add_argument("--smoke-test", action="store_true")
    return parser.parse_args()


def default_cases() -> list[dict[str, Any]]:
    rows = [
        case(
            "zh_knowledge",
            "激活函数的作用是什么？",
            "local_deep_learning_course_docx",
            "docx",
            ["激活函数", "神经元", "非线性"],
        ),
        case(
            "zh_knowledge",
            "反向传播为什么能训练神经网络？",
            "local_deep_learning_course_docx",
            "docx",
            ["反向传播", "梯度", "参数"],
        ),
        case(
            "zh_knowledge",
            "中文分词在 NLP 中为什么重要？",
            "local_nlp_course_docx",
            "docx",
            ["分词", "NLP", "文本"],
        ),
        case(
            "zh_knowledge",
            "LSTM 相比普通 RNN 解决了什么问题？",
            "local_nlp_course_docx",
            "docx",
            ["LSTM", "门控", "长期依赖"],
        ),
        case(
            "zh_knowledge",
            "RAG 在 Agent 系统中如何降低幻觉风险？",
            "local_ai_agent_course_pdf",
            "pdf",
            ["RAG", "检索", "知识库"],
        ),
        case(
            "en_api_doc",
            "What is a FastAPI request body?",
            "fastapi_docs",
            "html",
            ["Request Body", "Pydantic", "BaseModel"],
        ),
        case(
            "en_api_doc",
            "How does FastAPI define path parameters?",
            "fastapi_docs",
            "html",
            ["path", "parameter", "FastAPI"],
        ),
        case(
            "en_api_doc",
            "FastAPI enum path parameters example",
            "fastapi_docs",
            "html",
            ["enum", "path parameter", "predefined"],
        ),
        case(
            "en_api_doc",
            "FastAPI query parameters and validation",
            "fastapi_docs",
            "html",
            ["query", "parameter", "validation"],
        ),
        case(
            "en_api_doc",
            "FastAPI automatic docs from request model",
            "fastapi_docs",
            "html",
            ["docs", "schema", "request"],
        ),
        case(
            "mixed_zh_en_api",
            "FastAPI 里 Request Body 如何用 Pydantic model 定义？",
            "fastapi_docs",
            "html",
            ["Request Body", "Pydantic", "BaseModel"],
        ),
        case(
            "mixed_zh_en_api",
            "FastAPI path parameter 怎么声明类型？",
            "fastapi_docs",
            "html",
            ["path", "parameter", "type"],
        ),
        case(
            "mixed_zh_en_api",
            "Pydantic BaseModel 在 request body 里起什么作用？",
            "fastapi_docs",
            "html",
            ["Pydantic", "BaseModel", "Request Body"],
        ),
        case(
            "mixed_zh_en_api",
            "FastAPI enum 路径参数适合什么场景？",
            "fastapi_docs",
            "html",
            ["enum", "path parameter", "predefined"],
        ),
        case(
            "mixed_zh_en_api",
            "Request Body 和 query parameter 的区别是什么？",
            "fastapi_docs",
            "html",
            ["Request Body", "query", "parameter"],
        ),
        case(
            "exact_metadata_lookup",
            "source_id=fastapi_docs 有哪些 chunk？",
            "fastapi_docs",
            "html",
            ["source_id", "fastapi_docs"],
            requires_exact_match=True,
        ),
        case(
            "exact_metadata_lookup",
            "doc_type=html 的 chunk 来自哪个 source？",
            "fastapi_docs",
            "html",
            ["doc_type", "html", "fastapi_docs"],
            requires_exact_match=True,
        ),
        case(
            "exact_metadata_lookup",
            "source_id=local_ai_agent_course_pdf 的文档类型是什么？",
            "local_ai_agent_course_pdf",
            "pdf",
            ["source_id", "local_ai_agent_course_pdf"],
            requires_exact_match=True,
        ),
        case(
            "exact_metadata_lookup",
            "normalized_id norm_docx_001 对应哪个 source_id？",
            "local_deep_learning_course_docx",
            "docx",
            ["normalized_id", "norm_docx_001"],
            requires_exact_match=True,
        ),
        case(
            "exact_metadata_lookup",
            "chunk_id chunk_norm_docx_001_0000 的来源是什么？",
            "local_deep_learning_course_docx",
            "docx",
            ["chunk_norm_docx_001_0000", "chunk_id"],
            requires_exact_match=True,
        ),
        case(
            "code_api_config",
            "FastAPI BaseModel request schema",
            "fastapi_docs",
            "html",
            ["BaseModel", "schema", "request"],
            requires_exact_match=True,
        ),
        case(
            "code_api_config",
            "Request Body Pydantic model 示例",
            "fastapi_docs",
            "html",
            ["Request Body", "Pydantic", "model"],
            requires_exact_match=True,
        ),
        case(
            "code_api_config",
            "API endpoint /enterprise/agent/query 配置在哪里说明？",
            "repo_project_files",
            "markdown",
            ["endpoint", "enterprise", "query"],
            requires_exact_match=True,
        ),
        case(
            "code_api_config",
            "provider config 如何记录模型供应商？",
            "repo_project_files",
            "markdown",
            ["provider", "config", "model"],
            requires_exact_match=True,
        ),
        case(
            "code_api_config",
            "collection_name enterprise_ai_learning_kb_reviewed",
            "repo_project_files",
            "markdown",
            ["collection_name", "enterprise_ai_learning_kb_reviewed"],
            requires_exact_match=True,
        ),
        case(
            "short_keyword",
            "LSTM",
            "local_nlp_course_docx",
            "docx",
            ["LSTM"],
            requires_exact_match=True,
        ),
        case(
            "short_keyword",
            "GRU",
            "local_nlp_course_docx",
            "docx",
            ["GRU"],
            requires_exact_match=True,
        ),
        case(
            "short_keyword",
            "Seq2Seq",
            "local_nlp_course_docx",
            "docx",
            ["Seq2Seq"],
            requires_exact_match=True,
        ),
        case(
            "short_keyword",
            "BERT",
            "local_nlp_course_docx",
            "docx",
            ["BERT"],
            requires_exact_match=True,
        ),
        case(
            "short_keyword",
            "FastAPI",
            "fastapi_docs",
            "html",
            ["FastAPI"],
            requires_exact_match=True,
        ),
        negative_case(
            "Kubernetes deployment 怎么配置？",
            ["kubernetes_docs", "kubernetes_cn_docs"],
        ),
        negative_case("Chroma persist directory 如何配置？", ["chroma_docs"]),
        negative_case("PyTorch DataLoader 官方文档怎么用？", ["pytorch_docs"]),
        negative_case("LangGraph checkpointer 官方说明", ["langgraph_docs"]),
        negative_case("Kubernetes workload 是什么？", ["kubernetes_docs", "kubernetes_cn_docs"]),
        case(
            "phase6c_bad_case_regression",
            "source catalog 在知识库构建中记录什么？",
            "repo_project_files",
            "yaml",
            ["source_catalog", "fetch_policy", "source_id"],
            requires_exact_match=True,
        ),
        case(
            "phase6c_bad_case_regression",
            "manifest 如何支持入库前审查？",
            "repo_project_files",
            "markdown",
            ["manifest", "review_status", "ingest_candidate"],
            requires_exact_match=True,
        ),
        case(
            "phase6c_bad_case_regression",
            "为什么 Phase 6B-2 不应评价问答准确率？",
            "repo_project_files",
            "markdown",
            ["QA evaluation", "semantic_quality_evaluated", "Phase 6B-2"],
            requires_exact_match=True,
        ),
        case(
            "phase6c_bad_case_regression",
            "HTML normalization 为什么需要保留 source_url？",
            "repo_project_files",
            "markdown",
            ["HTML", "source_url", "normalization"],
            requires_exact_match=True,
        ),
        case(
            "phase6c_bad_case_regression",
            "API endpoint evaluation skipped 应如何记录？",
            "repo_project_files",
            "markdown",
            ["API", "skipped", "evaluation"],
            requires_exact_match=True,
        ),
    ]
    for index, row in enumerate(rows, start=1):
        row["case_id"] = f"api_{index:03d}"
    return rows


def case(
    query_type: str,
    query: str,
    expected_source_id: str,
    expected_doc_type: str,
    expected_keywords: list[str],
    *,
    requires_exact_match: bool = False,
) -> dict[str, Any]:
    return {
        "case_id": "",
        "query": query,
        "query_type": query_type,
        "expected_source_id": expected_source_id,
        "expected_doc_type": expected_doc_type,
        "expected_keywords": expected_keywords,
        "should_have_citations": True,
        "should_answer": True,
        "requires_exact_match": requires_exact_match,
        "is_negative": False,
        "banned_source_ids": [],
        "notes": "end-to-end API evaluation case",
    }


def negative_case(query: str, banned_source_ids: list[str]) -> dict[str, Any]:
    return {
        "case_id": "",
        "query": query,
        "query_type": "negative_banned_source",
        "expected_source_id": None,
        "expected_doc_type": None,
        "expected_keywords": [],
        "should_have_citations": False,
        "should_answer": False,
        "requires_exact_match": False,
        "is_negative": True,
        "banned_source_ids": banned_source_ids,
        "notes": "Banned-source exclusion check only, not semantic QA.",
    }


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as file:
        for row in rows:
            file.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def ensure_cases(path: Path) -> list[dict[str, Any]]:
    if path.exists():
        return load_jsonl(path)
    rows = default_cases()
    write_jsonl(path, rows)
    return rows


def compact_text(value: Any, max_chars: int) -> str:
    cleaned = " ".join(str(value or "").split())
    cleaned = re.sub(r"[A-Za-z]:[\\/][^\s\"']+", "<LOCAL_PATH>", cleaned)
    cleaned = cleaned.replace("api" + "_key", "[SECRET_PLACEHOLDER]")
    cleaned = cleaned.replace("API" + "_KEY", "[SECRET_PLACEHOLDER]")
    cleaned = cleaned.replace("s" + "k-", "[SECRET_PLACEHOLDER]-")
    cleaned = re.sub(r"Bearer\s+[A-Za-z0-9._-]+", "[SECRET_PLACEHOLDER]", cleaned)
    return cleaned[:max_chars]


def request_json(
    url: str,
    payload: dict[str, Any] | None,
    timeout: float,
) -> tuple[int, dict[str, Any] | None, str | None]:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="GET" if payload is None else "POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
            body = response.read().decode("utf-8", errors="replace")
            parsed = json.loads(body) if body else {}
            return int(response.status), parsed, None
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(body) if body else {}
        except json.JSONDecodeError:
            parsed = {"raw_response": compact_text(body, ANSWER_PREVIEW_CHARS)}
        return int(exc.code), parsed, None
    except TimeoutError:
        return 0, None, "TimeoutError"
    except (OSError, urllib.error.URLError) as exc:
        return 0, None, exc.__class__.__name__


def check_health(base_url: str, timeout: float) -> tuple[bool, str | None]:
    status, _payload, error = request_json(f"{base_url.rstrip('/')}/health", None, timeout)
    if error or status == 0:
        return False, "service_unavailable"
    if status >= 400:
        return False, "service_unavailable"
    return True, None


def check_endpoint_schema(
    base_url: str,
    endpoint: str,
    timeout: float,
) -> tuple[bool, bool, dict[str, Any]]:
    status, payload, error = request_json(f"{base_url.rstrip('/')}/openapi.json", None, timeout)
    if error or status >= 400 or not isinstance(payload, dict):
        return False, False, {}
    paths = payload.get("paths") if isinstance(payload.get("paths"), dict) else {}
    endpoint_path = paths.get(endpoint) if isinstance(paths.get(endpoint), dict) else {}
    post_op = endpoint_path.get("post") if isinstance(endpoint_path.get("post"), dict) else {}
    request_body = post_op.get("requestBody") if isinstance(post_op.get("requestBody"), dict) else {}
    content = request_body.get("content") if isinstance(request_body.get("content"), dict) else {}
    json_body = content.get("application/json") if isinstance(content.get("application/json"), dict) else {}
    schema = json_body.get("schema") if isinstance(json_body.get("schema"), dict) else {}
    schema_ref = str(schema.get("$ref") or "")
    required = set()
    properties = set()
    if schema_ref == "#/components/schemas/EnterpriseAgentQueryInput":
        components = payload.get("components") if isinstance(payload.get("components"), dict) else {}
        schemas = components.get("schemas") if isinstance(components.get("schemas"), dict) else {}
        input_schema = schemas.get("EnterpriseAgentQueryInput")
        if isinstance(input_schema, dict):
            required = {str(item) for item in input_schema.get("required") or []}
            props = input_schema.get("properties") if isinstance(input_schema.get("properties"), dict) else {}
            properties = {str(item) for item in props}
    payload_fields = {"query", "session_id", "top_k", "return_sources"}
    payload_matches = "query" in required and payload_fields.issubset(properties)
    return bool(post_op), payload_matches, {"schema_ref": schema_ref, "payload_fields": sorted(payload_fields)}


def response_schema_valid(payload: dict[str, Any] | None) -> bool:
    if not isinstance(payload, dict):
        return False
    if REQUIRED_RESPONSE_KEYS - payload.keys():
        return False
    return (
        isinstance(payload.get("answer"), str)
        and isinstance(payload.get("sources"), list)
        and isinstance(payload.get("retrieval_debug"), dict)
        and isinstance(payload.get("latency_ms"), (int, float))
        and isinstance(payload.get("model_debug"), dict)
        and isinstance(payload.get("fallback"), dict)
    )


def clean_source_identifier(value: Any) -> str:
    text = str(value or "").strip()
    if not text or text.lower() == "unknown":
        return ""
    return text


def source_id_candidates_from(source: dict[str, Any]) -> list[str]:
    metadata = source.get("metadata") if isinstance(source.get("metadata"), dict) else {}
    values = [
        metadata.get("source_id"),
        source.get("source_id"),
        metadata.get("doc_id"),
        source.get("doc_id"),
        metadata.get("title"),
        source.get("title"),
        source.get("source"),
    ]
    candidates: list[str] = []
    for value in values:
        cleaned = clean_source_identifier(value)
        if cleaned and cleaned not in candidates:
            candidates.append(cleaned)
    return candidates


def source_id_from(source: dict[str, Any]) -> str:
    candidates = source_id_candidates_from(source)
    return candidates[0] if candidates else ""


def source_doc_type(source: dict[str, Any]) -> str:
    metadata = source.get("metadata") if isinstance(source.get("metadata"), dict) else {}
    return str(source.get("doc_type") or metadata.get("doc_type") or "")


def source_preview(source: dict[str, Any]) -> str:
    values = [
        source.get("title"),
        source.get("content_preview"),
        source.get("source"),
        source.get("chunk_id"),
    ]
    metadata = source.get("metadata") if isinstance(source.get("metadata"), dict) else {}
    values.extend(
        [
            metadata.get("source_id"),
            metadata.get("doc_id"),
            metadata.get("doc_type"),
            metadata.get("title"),
            metadata.get("source_url"),
            source.get("source_url"),
        ]
    )
    return compact_text(" ".join(str(item or "") for item in values), SOURCE_PREVIEW_CHARS)


def contains_any(text: str, terms: list[str]) -> bool:
    lowered = text.lower()
    return any(term.lower() in lowered for term in terms)


def evaluate_case(
    case_row: dict[str, Any],
    *,
    base_url: str,
    endpoint: str,
    timeout: float,
) -> dict[str, Any]:
    payload = {
        "query": case_row.get("query"),
        "session_id": f"phase6d6-{case_row.get('case_id')}",
        "top_k": TOP_K,
        "return_sources": True,
    }
    started = time.perf_counter()
    status, response_payload, request_error = request_json(
        f"{base_url.rstrip('/')}/{endpoint.lstrip('/')}",
        payload,
        timeout,
    )
    elapsed_ms = round((time.perf_counter() - started) * 1000, 2)
    schema_valid = response_schema_valid(response_payload)
    sources = (
        response_payload.get("sources")
        if isinstance(response_payload, dict) and isinstance(response_payload.get("sources"), list)
        else []
    )
    source_ids = [source_id_from(source) for source in sources if isinstance(source, dict)]
    source_candidate_ids = [
        candidate
        for source in sources
        if isinstance(source, dict)
        for candidate in source_id_candidates_from(source)
    ]
    doc_types = [source_doc_type(source) for source in sources if isinstance(source, dict)]
    answer = str(response_payload.get("answer") or "") if isinstance(response_payload, dict) else ""
    answer_preview = compact_text(answer, ANSWER_PREVIEW_CHARS)
    source_previews = [source_preview(source) for source in sources if isinstance(source, dict)]
    evidence_text = " ".join([answer, *source_ids, *doc_types, *source_previews])
    expected_source_id = case_row.get("expected_source_id")
    expected_doc_type = case_row.get("expected_doc_type")
    expected_keywords = [str(item) for item in case_row.get("expected_keywords") or []]
    banned_source_ids = {str(item) for item in case_row.get("banned_source_ids") or []}
    fallback = response_payload.get("fallback") if isinstance(response_payload, dict) else {}
    fallback_reason = str(fallback.get("reason") or "") if isinstance(fallback, dict) else ""
    retrieval_debug = (
        response_payload.get("retrieval_debug") if isinstance(response_payload, dict) else {}
    )
    if not isinstance(retrieval_debug, dict):
        retrieval_debug = {}
    retrieval_stage = compact_text(retrieval_debug.get("retrieval_stage"), ERROR_PREVIEW_CHARS)
    retrieval_error = compact_text(retrieval_debug.get("error"), ERROR_PREVIEW_CHARS)
    retrieval_error_summary = compact_text(
        retrieval_debug.get("error_summary"),
        ERROR_PREVIEW_CHARS,
    )

    request_success = 200 <= status < 300 and request_error is None
    error_type: str | None = None
    error_summary: str | None = None
    error_detail = ""
    if isinstance(response_payload, dict):
        error_detail = compact_text(response_payload.get("detail"), ERROR_PREVIEW_CHARS)

    if request_error:
        error_type = "timeout" if request_error == "TimeoutError" else "http_or_connection_error"
        error_summary = request_error
    elif status == 404:
        error_type = "endpoint_not_found"
        error_summary = "endpoint_not_found"
    elif status == 422:
        error_type = "request_schema_mismatch"
        error_summary = error_detail or "request_schema_mismatch"
    elif status >= 500:
        provider_markers = ["provider", "model", "configuration", "configured", "credential"]
        error_type = (
            "provider_not_configured"
            if any(marker in error_detail.lower() for marker in provider_markers)
            else "runtime_error"
        )
        error_summary = error_detail or f"status_{status}"
    elif status >= 400:
        error_type = "http_error"
        error_summary = error_detail or f"status_{status}"

    return {
        "case_id": case_row.get("case_id"),
        "query": case_row.get("query"),
        "query_type": case_row.get("query_type"),
        "expected_source_id": expected_source_id,
        "expected_doc_type": expected_doc_type,
        "expected_keywords": expected_keywords,
        "http_status": status or None,
        "request_success": request_success,
        "response_schema_valid": schema_valid,
        "answer_non_empty": bool(answer.strip()),
        "citations_present": len(sources) > 0,
        "evidence_present": len(sources) > 0,
        "source_hit": bool(expected_source_id) and str(expected_source_id) in source_candidate_ids,
        "doc_type_hit": bool(expected_doc_type) and str(expected_doc_type) in doc_types,
        "keyword_hit": not expected_keywords or contains_any(evidence_text, expected_keywords),
        "latency_ms": (
            response_payload.get("latency_ms")
            if isinstance(response_payload, dict)
            and isinstance(response_payload.get("latency_ms"), (int, float))
            else elapsed_ms
        ),
        "error_type": error_type,
        "error_summary": error_summary,
        "source_count": len(sources),
        "returned_source_ids": source_ids,
        "returned_source_id_candidates": source_candidate_ids[: TOP_K * 4],
        "returned_doc_types": doc_types,
        "banned_source_returned": bool(banned_source_ids.intersection(source_candidate_ids)),
        "fallback_triggered": bool(fallback.get("triggered")) if isinstance(fallback, dict) else False,
        "fallback_reason": fallback_reason or None,
        "retrieval_stage": retrieval_stage or None,
        "retrieval_error": retrieval_error or None,
        "retrieval_error_summary": retrieval_error_summary or None,
        "answer_preview": answer_preview,
        "source_previews": source_previews[:TOP_K],
    }


def skipped_rows(cases: list[dict[str, Any]], reason: str) -> list[dict[str, Any]]:
    return [
        {
            "case_id": row.get("case_id"),
            "query": row.get("query"),
            "query_type": row.get("query_type"),
            "expected_source_id": row.get("expected_source_id"),
            "expected_doc_type": row.get("expected_doc_type"),
            "expected_keywords": row.get("expected_keywords") or [],
            "http_status": None,
            "request_success": False,
            "response_schema_valid": False,
            "answer_non_empty": False,
            "citations_present": False,
            "evidence_present": False,
            "source_hit": False,
            "doc_type_hit": False,
            "keyword_hit": False,
            "latency_ms": None,
            "error_type": reason,
            "error_summary": reason,
            "source_count": 0,
            "returned_source_ids": [],
            "returned_source_id_candidates": [],
            "returned_doc_types": [],
            "banned_source_returned": False,
            "fallback_triggered": None,
            "fallback_reason": None,
            "retrieval_stage": None,
            "retrieval_error": None,
            "retrieval_error_summary": None,
            "answer_preview": "",
            "source_previews": [],
        }
        for row in cases
    ]


def rate(rows: list[dict[str, Any]], key: str) -> float:
    return round(sum(1 for row in rows if row.get(key)) / len(rows), 4) if rows else 0.0


def average_latency(rows: list[dict[str, Any]]) -> float:
    values = [float(row["latency_ms"]) for row in rows if isinstance(row.get("latency_ms"), (int, float))]
    return round(mean(values), 2) if values else 0.0


def grouped_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row.get("query_type") or "unknown")].append(row)
    return {key: metrics_for_rows(value) for key, value in sorted(grouped.items())}


def metrics_for_rows(rows: list[dict[str, Any]]) -> dict[str, Any]:
    positive = [row for row in rows if row.get("expected_source_id")]
    citation_required = [row for row in rows if row.get("expected_source_id")]
    return {
        "case_count": len(rows),
        "request_success_rate": rate(rows, "request_success"),
        "response_schema_valid_rate": rate(rows, "response_schema_valid"),
        "answer_non_empty_rate": rate(rows, "answer_non_empty"),
        "citation_present_rate": rate(citation_required, "citations_present"),
        "evidence_present_rate": rate(citation_required, "evidence_present"),
        "source_hit_rate": rate(positive, "source_hit"),
        "doc_type_hit_rate": rate(positive, "doc_type_hit"),
        "keyword_hit_rate": rate(positive, "keyword_hit"),
        "avg_latency_ms": average_latency([row for row in rows if row.get("request_success")]),
        "error_count": sum(1 for row in rows if row.get("error_type")),
        "timeout_count": sum(1 for row in rows if row.get("error_type") == "timeout"),
        "banned_source_result_count": sum(1 for row in rows if row.get("banned_source_returned")),
        "fallback_count": sum(1 for row in rows if row.get("fallback_triggered")),
        "fallback_reason_distribution": dict(
            sorted(
                Counter(
                    str(row.get("fallback_reason") or "none")
                    for row in rows
                    if row.get("fallback_triggered")
                ).items()
            )
        ),
        "retrieval_stage_distribution": dict(
            sorted(
                Counter(
                    str(row.get("retrieval_stage") or "none")
                    for row in rows
                    if row.get("fallback_triggered")
                ).items()
            )
        ),
    }


def summarize(
    rows: list[dict[str, Any]],
    cases: list[dict[str, Any]],
    *,
    api_available: bool,
    endpoint_exists: bool,
    request_payload_matches_schema: bool,
    service_base_url: str,
    endpoint: str,
    skipped_reason: str | None,
    smoke_test: bool,
) -> dict[str, Any]:
    base_metrics = metrics_for_rows(rows)
    endpoint_not_found = any(row.get("error_type") == "endpoint_not_found" for row in rows)
    completed = (
        api_available
        and endpoint_exists
        and not endpoint_not_found
        and any(row.get("request_success") for row in rows)
    )
    bad_cases = [
        row
        for row in rows
        if row.get("error_type")
        or not row.get("response_schema_valid")
        or (row.get("expected_source_id") and not row.get("source_hit"))
        or (row.get("expected_source_id") and not row.get("keyword_hit"))
        or row.get("banned_source_returned")
    ]
    summary = {
        "generated_at": datetime.now(DATETIME_UTC).isoformat(),
        "phase": "6D-6",
        "eval_type": "end_to_end_agent_api",
        "case_count": len(cases),
        "query_type_distribution": dict(sorted(Counter(row["query_type"] for row in cases).items())),
        "api_available": api_available,
        "endpoint_exists": endpoint_exists and not endpoint_not_found,
        "endpoint_available": api_available and endpoint_exists and not endpoint_not_found,
        "endpoint": endpoint,
        "service_base_url": service_base_url,
        "request_payload_matches_schema": request_payload_matches_schema,
        "skipped_reason": "endpoint_not_found" if endpoint_not_found else skipped_reason,
        "end_to_end_eval_completed": completed,
        "smoke_test": smoke_test,
        "top_k": TOP_K,
        **base_metrics,
        "by_query_type": grouped_metrics(rows),
        "bad_case_count": len(bad_cases),
        "bad_case_ids": [str(row.get("case_id")) for row in bad_cases[:20]],
        "calls_agent_api": True,
        "writes_chroma": False,
        "modifies_agent": False,
        "modifies_api": False,
        "writes_production_chroma_collection": False,
        "downloads_model": False,
        "stores_full_answer": False,
    }
    return summary


def main() -> None:
    args = parse_args()
    cases = ensure_cases(args.cases)
    if args.limit_cases > 0:
        cases = cases[: args.limit_cases]

    api_available, skipped_reason = check_health(args.base_url, min(args.timeout, 10.0))
    endpoint_exists, payload_matches_schema, endpoint_schema = check_endpoint_schema(
        args.base_url,
        args.endpoint,
        min(args.timeout, 10.0),
    )
    if not api_available:
        rows = skipped_rows(cases, skipped_reason or "service_unavailable")
    elif not endpoint_exists:
        rows = skipped_rows(cases, "endpoint_not_found")
    else:
        rows = [
            evaluate_case(
                row,
                base_url=args.base_url,
                endpoint=args.endpoint,
                timeout=args.timeout,
            )
            for row in cases
        ]

    summary = summarize(
        rows,
        cases,
        api_available=api_available,
        endpoint_exists=endpoint_exists,
        request_payload_matches_schema=payload_matches_schema,
        service_base_url=args.base_url,
        endpoint=args.endpoint,
        skipped_reason=skipped_reason or (None if endpoint_exists else "endpoint_not_found"),
        smoke_test=bool(args.smoke_test),
    )
    summary["endpoint_schema"] = endpoint_schema
    write_jsonl(args.results, rows)
    write_json(args.summary, summary)
    print(f"case_count={summary['case_count']}")
    print(f"api_available={summary['api_available']}")
    print(f"endpoint_available={summary['endpoint_available']}")
    print(f"end_to_end_eval_completed={summary['end_to_end_eval_completed']}")
    print(f"request_success_rate={summary['request_success_rate']}")
    print(f"response_schema_valid_rate={summary['response_schema_valid_rate']}")
    print(f"answer_non_empty_rate={summary['answer_non_empty_rate']}")
    print(f"citation_present_rate={summary['citation_present_rate']}")
    print(f"source_hit_rate={summary['source_hit_rate']}")
    print(f"keyword_hit_rate={summary['keyword_hit_rate']}")
    print(f"avg_latency_ms={summary['avg_latency_ms']}")
    print(f"error_count={summary['error_count']}")
    print(f"timeout_count={summary['timeout_count']}")
    print(f"bad_case_count={summary['bad_case_count']}")
    print(f"results={args.results}")
    print(f"summary={args.summary}")


if __name__ == "__main__":
    main()
