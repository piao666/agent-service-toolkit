from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Any


class QueryType(str, Enum):
    EXACT_METADATA_LOOKUP = "exact_metadata_lookup"
    CODE_API_CONFIG = "code_api_config"
    SHORT_KEYWORD = "short_keyword"
    ZH_KNOWLEDGE = "zh_knowledge"
    EN_API_DOC = "en_api_doc"
    MIXED_ZH_EN_API = "mixed_zh_en_api"
    AGENT_RAG_CONCEPT = "agent_rag_concept"
    AMBIGUOUS_QUERY = "ambiguous_query"
    MULTI_HOP_LOOKUP = "multi_hop_lookup"
    CITATION_REQUIRED_QUERY = "citation_required_query"
    NEGATIVE_BANNED_SOURCE = "negative_banned_source"
    PHASE6C_BAD_CASE_REGRESSION = "phase6c_bad_case_regression"
    UNKNOWN = "unknown"


class RetrievalPolicyName(str, Enum):
    METADATA_FIRST = "metadata_first"
    SPARSE_FIRST_BM25 = "sparse_first_bm25"
    DENSE_SPARSE_FUSION = "dense_sparse_fusion"
    CLARIFICATION_FIRST = "clarification_first"
    MULTI_QUERY_RETRIEVAL = "multi_query_retrieval"
    CITATION_AWARE_EVIDENCE = "citation_aware_evidence"
    BANNED_SOURCE_GUARD_FIRST = "banned_source_guard_first"


METADATA_FIELDS = (
    "source_id",
    "doc_type",
    "domain",
    "title",
    "section_path",
    "heading_path",
    "chunk_id",
    "source_url",
    "normalized_id",
)

CODE_API_TERMS = (
    "api",
    "endpoint",
    "path",
    "route",
    "function",
    "class",
    "config",
    "parameter",
    "error",
    "exception",
    "filename",
    "import",
    "method",
)


@dataclass(frozen=True)
class RetrievalPolicy:
    name: RetrievalPolicyName
    description: str
    metadata_fields: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    requires_production_change: bool = True


def _normalize_query_type(value: str | QueryType | None) -> QueryType:
    if isinstance(value, QueryType):
        return value
    if not value:
        return QueryType.UNKNOWN
    try:
        return QueryType(str(value))
    except ValueError:
        return QueryType.UNKNOWN


def infer_query_type(query: str, case_metadata: dict[str, Any] | None = None) -> QueryType:
    """Infer a query type using case metadata first and conservative text rules second."""

    metadata = case_metadata or {}
    metadata_type = _normalize_query_type(metadata.get("query_type"))
    if metadata_type is not QueryType.UNKNOWN:
        return metadata_type

    normalized_query = query.lower()
    if any(field in normalized_query for field in METADATA_FIELDS):
        return QueryType.EXACT_METADATA_LOOKUP
    if any(term in normalized_query for term in CODE_API_TERMS) or re.search(
        r"\b[A-Za-z_][A-Za-z0-9_]*\(", query
    ):
        return QueryType.CODE_API_CONFIG
    if any(term in query for term in ("对比", "区别", "同时", "以及", "和", "并且", "分别")):
        return QueryType.MULTI_HOP_LOOKUP
    if any(term in query for term in ("引用", "来源", "出处", "证据", "citation", "source")):
        return QueryType.CITATION_REQUIRED_QUERY
    if len(query.strip()) <= 12:
        return QueryType.SHORT_KEYWORD
    return QueryType.ZH_KNOWLEDGE


def select_retrieval_policy(query_type: str | QueryType) -> RetrievalPolicy:
    normalized_type = _normalize_query_type(query_type)
    if normalized_type is QueryType.EXACT_METADATA_LOOKUP:
        return RetrievalPolicy(
            name=RetrievalPolicyName.METADATA_FIRST,
            description="Prioritize exact metadata field matches before dense retrieval.",
            metadata_fields=METADATA_FIELDS,
            notes=("promote matched metadata chunks", "do not rely on dense embedding only"),
        )
    if normalized_type in {QueryType.CODE_API_CONFIG, QueryType.SHORT_KEYWORD}:
        return RetrievalPolicy(
            name=RetrievalPolicyName.SPARSE_FIRST_BM25,
            description="Use sparse or BM25-first retrieval for code, API, config, and exact terms.",
            notes=("match symbols and config keys", "preserve exact token coverage"),
        )
    if normalized_type is QueryType.AMBIGUOUS_QUERY:
        return RetrievalPolicy(
            name=RetrievalPolicyName.CLARIFICATION_FIRST,
            description="Avoid forcing a single source and return clarification or candidates.",
            notes=("multi_candidate_answer", "do_not_force_single_source"),
        )
    if normalized_type is QueryType.MULTI_HOP_LOOKUP:
        return RetrievalPolicy(
            name=RetrievalPolicyName.MULTI_QUERY_RETRIEVAL,
            description="Split the query into rule-based subqueries and merge candidates.",
            notes=("split comparative or conjunctive queries", "merge candidate evidence"),
        )
    if normalized_type is QueryType.CITATION_REQUIRED_QUERY:
        return RetrievalPolicy(
            name=RetrievalPolicyName.CITATION_AWARE_EVIDENCE,
            description="Verify returned evidence contains traceable source metadata.",
            notes=("require source_id", "require source_url/title/section path when available"),
        )
    if normalized_type is QueryType.NEGATIVE_BANNED_SOURCE:
        return RetrievalPolicy(
            name=RetrievalPolicyName.BANNED_SOURCE_GUARD_FIRST,
            description="Filter banned sources before scoring and do not optimize for source hit.",
            notes=("banned_source_result_count must stay zero",),
            requires_production_change=False,
        )
    return RetrievalPolicy(
        name=RetrievalPolicyName.DENSE_SPARSE_FUSION,
        description="Use dense semantic retrieval with sparse keyword coverage.",
        notes=("ordinary knowledge query", "combine semantic and lexical signals"),
    )


def _tokens(text: str) -> set[str]:
    normalized = text.lower()
    words = set(re.findall(r"[a-zA-Z_][a-zA-Z0-9_./:-]*|\d+(?:\.\d+)?", normalized))
    cjk_terms = {char for char in normalized if "\u4e00" <= char <= "\u9fff"}
    return words | cjk_terms


def metadata_first_score(query: str, metadata: dict[str, Any]) -> float:
    query_text = query.lower()
    score = 0.0
    for field in METADATA_FIELDS:
        value = metadata.get(field)
        if value is None:
            continue
        normalized_value = str(value).lower()
        if normalized_value and normalized_value in query_text:
            score += 2.0
        elif field in query_text:
            score += 0.5
    return score


def sparse_first_score(query: str, text: str) -> float:
    query_tokens = _tokens(query)
    text_tokens = _tokens(text)
    if not query_tokens or not text_tokens:
        return 0.0
    overlap = query_tokens & text_tokens
    return len(overlap) / len(query_tokens)


def dense_sparse_fusion_score(
    dense_score: float,
    sparse_score: float,
    dense_weight: float = 0.6,
    sparse_weight: float = 0.4,
) -> float:
    return dense_score * dense_weight + sparse_score * sparse_weight


def split_multi_hop_query(query: str) -> list[str]:
    parts = re.split(r"(?:对比|区别|同时|以及|并且|分别| 和 | and | versus | vs\.?)", query)
    cleaned = [part.strip(" ，,。?？") for part in parts if part.strip(" ，,。?？")]
    return cleaned or [query.strip()]


def citation_evidence_check(
    query: str,
    source: dict[str, Any],
    answer: str | None = None,
) -> dict[str, Any]:
    metadata = dict(source.get("metadata") or {})
    source_id = metadata.get("source_id") or source.get("source_id")
    title = metadata.get("title") or source.get("title")
    source_url = metadata.get("source_url") or source.get("source_url")
    section_path = metadata.get("section_path") or metadata.get("heading_path") or source.get(
        "section_path"
    )
    preview = source.get("content_preview") or metadata.get("content_preview") or ""
    compared_text = " ".join(str(part or "") for part in (preview, answer))
    keyword_overlap = bool(_tokens(query) & _tokens(compared_text))
    return {
        "has_source_id": bool(source_id),
        "has_traceable_location": bool(source_url or title or section_path),
        "keyword_overlap": keyword_overlap,
        "citation_ready": bool(source_id and (source_url or title or section_path)),
    }
