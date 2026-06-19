from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

DEFAULT_SAFE_FALLBACK = (
    "根据当前知识库证据，无法高置信度确认该问题的答案。"
    "建议查看返回的相关来源，或补充更具体的问题。"
)
CITATION_TERMS = {"citation", "reference", "source", "引用", "出处", "来源", "证据"}
ENGLISH_STOP_WORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "that",
    "the",
    "this",
    "to",
    "with",
}
CHINESE_STOP_TERMS = {
    "一个",
    "一种",
    "什么",
    "以及",
    "使用",
    "可以",
    "如何",
    "它的",
    "用于",
    "这个",
    "进行",
    "通过",
}
PHRASE_PATTERN = re.compile(r"\b(?:Request\s+Body|Retrieval[- ]Augmented\s+Generation)\b", re.I)
SYMBOL_PATTERN = re.compile(
    r"(?:/[A-Za-z0-9_.{}-]+(?:/[A-Za-z0-9_.{}-]+)+|"
    r"[A-Z][A-Z0-9]+(?:_[A-Z0-9]+)+|"
    r"[A-Za-z][A-Za-z0-9]*_[A-Za-z0-9_]+|"
    r"[A-Za-z][A-Za-z0-9.:-]*\(\)|"
    r"\b(?:GET|POST|PUT|PATCH|DELETE)\b|"
    r"\b[1-5][0-9]{2}\b)"
)
ENGLISH_PATTERN = re.compile(r"\b[A-Za-z][A-Za-z0-9.+#-]{1,31}\b")
CHINESE_PATTERN = re.compile(r"[\u4e00-\u9fff]{2,}")


@dataclass(frozen=True, slots=True)
class EvidenceVerificationResult:
    verifier_mode: str
    grounding_status: str
    grounding_score: float
    answer_has_sources: bool
    citation_coverage: bool
    important_terms: list[str]
    matched_terms: list[str]
    unsupported_terms: list[str]
    source_count: int
    safe_fallback_triggered: bool
    calls_llm: bool = False
    writes_chroma: bool = False

    def as_debug(self) -> dict[str, Any]:
        return asdict(self)


def _deduplicate(terms: list[str], limit: int = 64) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for term in terms:
        normalized = term.casefold()
        if normalized in seen:
            continue
        seen.add(normalized)
        result.append(term)
        if len(result) >= limit:
            break
    return result


def _chinese_terms(text: str) -> list[str]:
    terms: list[str] = []
    for sequence in CHINESE_PATTERN.findall(text):
        if sequence in CHINESE_STOP_TERMS:
            continue
        if len(sequence) <= 8:
            terms.append(sequence)
        else:
            for width in (4, 3, 2):
                terms.extend(sequence[index : index + width] for index in range(len(sequence) - width + 1))
    return terms


def extract_evidence_terms(text: str) -> list[str]:
    """Extract bounded lexical, technical, and CJK evidence terms."""
    normalized_text = str(text or "")
    terms: list[str] = []
    terms.extend(match.group(0) for match in PHRASE_PATTERN.finditer(normalized_text))
    terms.extend(match.group(0) for match in SYMBOL_PATTERN.finditer(normalized_text))
    for match in ENGLISH_PATTERN.finditer(normalized_text):
        term = match.group(0)
        if term.casefold() not in ENGLISH_STOP_WORDS:
            terms.append(term)
    terms.extend(_chinese_terms(normalized_text))
    return _deduplicate(terms)


def _source_value(source: dict[str, Any], field: str) -> str:
    metadata = source.get("metadata") if isinstance(source.get("metadata"), dict) else {}
    value = source.get(field)
    if value in (None, "", "unknown"):
        value = metadata.get(field)
    return str(value or "").strip()


def summarize_sources_for_verifier(
    sources: list[dict[str, Any]],
    *,
    max_preview_chars: int = 1000,
) -> list[dict[str, Any]]:
    """Build bounded verifier-only source summaries without returning full chunks."""
    summaries: list[dict[str, Any]] = []
    for source in sources:
        preview = (
            _source_value(source, "content_preview")
            or _source_value(source, "preview")
            or _source_value(source, "text")
        )[:max_preview_chars]
        evidence_text = " ".join(
            part
            for part in (
                _source_value(source, "source_id"),
                _source_value(source, "title"),
                _source_value(source, "doc_type"),
                _source_value(source, "section_path"),
                _source_value(source, "source_url"),
                _source_value(source, "chunk_id"),
                preview,
            )
            if part
        )
        summaries.append(
            {
                "source_id": _source_value(source, "source_id"),
                "title": _source_value(source, "title"),
                "chunk_id": _source_value(source, "chunk_id"),
                "evidence_terms": extract_evidence_terms(evidence_text),
            }
        )
    return summaries


def calculate_grounding_score(
    important_terms: list[str],
    matched_terms: list[str],
) -> float:
    if not important_terms:
        return 0.0
    return round(len(matched_terms) / len(important_terms), 4)


def build_safe_fallback_answer(query: str = "") -> str:
    if any("a" <= character.lower() <= "z" for character in query) and not any(
        "\u4e00" <= character <= "\u9fff" for character in query
    ):
        return (
            "The current knowledge-base evidence is not sufficient to confirm this answer with "
            "high confidence. Review the returned sources or provide a more specific question."
        )
    return DEFAULT_SAFE_FALLBACK


def _is_citation_required(query: str, query_type: str | None) -> bool:
    if str(query_type or "").strip().lower() == "citation_required_query":
        return True
    normalized_query = query.casefold()
    return any(term in normalized_query for term in CITATION_TERMS)


def verify_answer_grounding(
    *,
    query: str,
    answer: str,
    sources: list[dict[str, Any]],
    query_type: str | None = None,
    mode: str = "rule_based",
    safe_fallback_enabled: bool = False,
    min_score: float = 0.30,
    high_score: float = 0.60,
) -> EvidenceVerificationResult:
    """Estimate answer support from bounded source metadata and previews without an LLM."""
    normalized_mode = str(mode or "off").strip().lower()
    if normalized_mode != "rule_based":
        return EvidenceVerificationResult(
            verifier_mode="off",
            grounding_status="not_checked",
            grounding_score=0.0,
            answer_has_sources=bool(answer.strip() and sources),
            citation_coverage=False,
            important_terms=[],
            matched_terms=[],
            unsupported_terms=[],
            source_count=len(sources),
            safe_fallback_triggered=False,
        )

    important_terms = extract_evidence_terms(answer)
    source_summaries = summarize_sources_for_verifier(sources)
    source_term_sets = [
        {term.casefold() for term in summary["evidence_terms"]} for summary in source_summaries
    ]
    all_source_terms = set().union(*source_term_sets) if source_term_sets else set()
    matched_terms = [term for term in important_terms if term.casefold() in all_source_terms]
    unsupported_terms = [term for term in important_terms if term.casefold() not in all_source_terms]
    score = calculate_grounding_score(important_terms, matched_terms)
    citation_required = _is_citation_required(query, query_type)

    if not answer.strip() or not sources:
        status = "low"
    elif not important_terms:
        status = "medium"
    elif citation_required:
        if score >= max(high_score, 0.70):
            status = "high"
        elif score < max(min_score, 0.50):
            status = "low"
        else:
            status = "medium"
    elif score >= high_score:
        status = "high"
    elif score < min_score:
        status = "low"
    else:
        status = "medium"

    citation_coverage = bool(
        sources
        and matched_terms
        and any(
            any(term.casefold() in source_terms for term in matched_terms)
            for source_terms in source_term_sets
        )
    )
    return EvidenceVerificationResult(
        verifier_mode="rule_based",
        grounding_status=status,
        grounding_score=score,
        answer_has_sources=bool(answer.strip() and sources),
        citation_coverage=citation_coverage,
        important_terms=important_terms,
        matched_terms=matched_terms,
        unsupported_terms=unsupported_terms,
        source_count=len(sources),
        safe_fallback_triggered=bool(safe_fallback_enabled and status == "low"),
    )
