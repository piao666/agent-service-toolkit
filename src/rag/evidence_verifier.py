"""Evidence verifier V2: weighted rule-based answer grounding estimation.

V2 改进 (2026-06-25):
- 文本归一化：全角半角、标点统一、token 归一
- 三级 term 分类：critical / support / example
- 加权覆盖率评分代替简单比率
- Source quality gate：来源正确时不因代码变量/中文碎片误判
- Corpus gap guardrail：LoRA 等语料缺口强制 LOW
- 使用更完整的 source text
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import asdict, dataclass
from typing import Any

DEFAULT_SAFE_FALLBACK = (
    "根据当前知识库证据，无法高置信度确认该问题的答案。"
    "建议查看返回的相关来源，或补充更具体的问题。"
)
CITATION_TERMS = {"citation", "reference", "source", "引用", "出处", "来源", "证据"}

# ============================================================================
# V2: 文本归一化
# ============================================================================

_SYMBOL_NORM = re.compile(r"[()\[\]{}.,;:!?\"'`@#$%^&*+=<>/\\|~]+")
_SPACE_PATTERN = re.compile(r"\s+")


def _normalize_evidence_text(text: str) -> str:
    """文本归一化：全角->半角、lowercase、标点统一、合并空白。"""
    if not text:
        return ""
    # NFKC normalization handles most fullwidth -> halfwidth conversions
    result = unicodedata.normalize("NFKC", text)
    result = result.lower()
    result = _SYMBOL_NORM.sub(" ", result)
    result = _SPACE_PATTERN.sub(" ", result)
    return result.strip()


# ============================================================================
# V2: 停用词与碎片过滤
# ============================================================================

_STOP_PHRASES_CN = {
    "根据检索", "检索到的", "检索结果", "当前上下文", "当前资料",
    "的步骤如下", "定义一个继承自", "并在其中", "其中声明",
    "声明字段", "创建数据模型", "因此", "没有足够依据",
    "根据", "当前", "内容", "资料", "来源", "没有", "不足",
    "可以", "需要", "能够", "进行", "通过", "使用", "一个",
    "什么", "如何在", "其", "该", "这些", "那些", "这个", "那个",
    "基于", "来看", "认为", "推测", "无法", "可能",
}

_STOP_TOKENS_EN = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from",
    "in", "is", "it", "of", "on", "or", "that", "the", "this", "to",
    "with", "not", "but", "if", "so", "we", "he", "she", "they", "you",
    "me", "us", "can", "will", "may", "also", "has", "had", "was", "were",
    "been", "have", "do", "does", "did", "get", "got", "its",
}

# 代码变量级别 token (example_terms 权重)
_EXAMPLE_VARIABLE_TOKENS = {
    "app", "app.post", "item", "name", "price", "str", "float", "int",
    "async", "def", "return", "class", "import", "self", "none",
    "true", "false", "create_item", "update_item", "delete_item",
    "read_item", "read_items", "get", "post", "put", "delete",
    "request", "response", "data", "type", "field", "fields",
    "body", "param", "params", "path", "query", "header",
}

# 不携带业务语义的短中文词
_CN_FRAGMENT_STOP = {
    "继承自", "的方法", "的参数", "的步骤", "声明一",
    "定义一个", "如下所", "所示", "以下", "上述",
    "其中", "并在", "声明", "创建", "提供", "包含",
    "所有", "其他", "这个", "那个", "这些", "那些",
    "上面", "下面", "前面", "后面", "里面", "外面",
}


# ============================================================================
# V2: 技术词汇提取
# ============================================================================

# 多词短语 (优先匹配)
_PHRASE_PATTERN = re.compile(
    r"\b(?:"
    r"Request\s+Body|Retrieval[- ]Augmented\s+Generation|"
    r"Fast\s*API|Path\s+Parameters?|Query\s+Parameters?|"
    r"Swagger\s+UI|Open\s*API|Base\s*Model|"
    r"Vector\s+Store|Knowledge\s+Base|"
    r"enterprise_rag_pipeline|enterprise_agent_overview|"
    r"enterprise_prompt_guidelines|enterprise_model_provider_policy|"
    r"fastapi_docs|local_deep_learning|local_nlp_course|"
    r"检索增强生成|知识库|向量库|向量存储|"
    r"请求体|路径参数|查询参数|"
    r"参数高效微调|低秩适配|"
    r")",
    re.I,
)

# 技术符号
_SYMBOL_PATTERN = re.compile(
    r"(?:/[A-Za-z0-9_.{}-]+(?:/[A-Za-z0-9_.{}-]+)+|"
    r"[A-Z][A-Z0-9]+(?:_[A-Z0-9]+)+|"
    r"[A-Za-z][A-Za-z0-9]*_[A-Za-z0-9_]+|"
    r"[A-Za-z][A-Za-z0-9.:-]*\(\)|"
    r"\b(?:GET|POST|PUT|PATCH|DELETE)\b|"
    r"\b[1-5][0-9]{2}\b)"
)

# 英文/技术词 (2 字符以上, 排除停用词和示例变量)
_TECH_EN_PATTERN = re.compile(r"\b[A-Za-z][A-Za-z0-9.+#-]{1,31}\b")

# 中文词 (2-8 字, 排除碎片停用词)
_CN_TERM_PATTERN = re.compile(r"[一-鿿]{2,8}")


def _is_cn_fragment(term: str) -> bool:
    """判断中文词是否是碎片。"""
    if term in _CN_FRAGMENT_STOP:
        return True
    if len(term) <= 2 and not any(
        kw in term for kw in ("rag", "api", "检索", "生成", "模型", "向量", "知识", "文档")
    ):
        return True
    return False


def _extract_raw_terms(text: str) -> list[str]:
    """从文本中提取所有原始候选词。"""
    normalized = str(text or "")
    terms: list[str] = []

    # 1. 多词短语优先
    for match in _PHRASE_PATTERN.finditer(normalized):
        terms.append(match.group(0))

    # 2. 技术符号
    for match in _SYMBOL_PATTERN.finditer(normalized):
        terms.append(match.group(0))

    # 3. 英文技术词
    for match in _TECH_EN_PATTERN.finditer(normalized):
        term = match.group(0)
        lowered = term.casefold()
        if lowered not in _STOP_TOKENS_EN and lowered not in _EXAMPLE_VARIABLE_TOKENS:
            terms.append(term)

    # 4. 中文词 (2-8 字)
    for match in _CN_TERM_PATTERN.finditer(normalized):
        term = match.group(0)
        if term not in _STOP_PHRASES_CN and not _is_cn_fragment(term):
            terms.append(term)

    return terms


# ============================================================================
# V2: 三级 term 分类
# ============================================================================

# critical 关键词 (来自 query 核心技术词或 source 标识)
_CRITICAL_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"fast\s*api", re.I), "FastAPI"),
    (re.compile(r"request\s*body", re.I), "Request Body"),
    (re.compile(r"pydantic", re.I), "Pydantic"),
    (re.compile(r"basemodel", re.I), "BaseModel"),
    (re.compile(r"\brag\b", re.I), "RAG"),
    (re.compile(r"retrieval[ -]augmented\s*generation", re.I), "Retrieval-Augmented Generation"),
    (re.compile(r"retrieval", re.I), "retrieval"),
    (re.compile(r"\blora\b", re.I), "LoRA"),
    (re.compile(r"\bpeft\b", re.I), "PEFT"),
    (re.compile(r"\bqlora\b", re.I), "QLoRA"),
    (re.compile(r"low[ -]?rank", re.I), "low-rank"),
    (re.compile(r"finetune|fine[ -]?tune", re.I), "fine-tune"),
    (re.compile(r"embedding", re.I), "embedding"),
    (re.compile(r"chunk", re.I), "chunk"),
    (re.compile(r"document", re.I), "document"),
    (re.compile(r"vector\s*store", re.I), "vector store"),
    (re.compile(r"enterprise_rag_pipeline"), "enterprise_rag_pipeline"),
    (re.compile(r"enterprise_agent_overview"), "enterprise_agent_overview"),
    (re.compile(r"fastapi_docs"), "fastapi_docs"),
    (re.compile(r"检索增强生成"), "Retrieval-Augmented Generation"),
    (re.compile(r"检索"), "retrieval"),
    (re.compile(r"生成"), "generation"),
    (re.compile(r"低秩"), "low-rank"),
    (re.compile(r"微调"), "fine-tune"),
    (re.compile(r"参数高效"), "parameter-efficient"),
    (re.compile(r"知识库"), "knowledge-base"),
    (re.compile(r"向量库"), "vector-store"),
    (re.compile(r"上下文"), "context"),
    (re.compile(r"请求体"), "request-body"),
]


def _classify_terms(
    raw_terms: list[str],
    query: str,
    source_ids: list[str],
    source_titles: list[str],
) -> tuple[list[str], list[str], list[str]]:
    """把术语分成 critical / support / example 三类。"""
    query_norm = _normalize_evidence_text(query)
    sid_text = " ".join(source_ids).lower()
    title_text = " ".join(source_titles).lower()

    critical: list[str] = []
    support: list[str] = []
    example: list[str] = []

    seen_critical: set[str] = set()
    seen_all: set[str] = set()

    for term in raw_terms:
        term_norm = _normalize_evidence_text(term)
        if not term_norm or term_norm in seen_all:
            continue
        seen_all.add(term_norm)

        # Example: 代码变量
        if term_norm in _EXAMPLE_VARIABLE_TOKENS | {"create_item"}:
            example.append(term)
            continue

        # Check critical patterns
        is_critical = False
        for pattern, label in _CRITICAL_PATTERNS:
            if pattern.search(term_norm) or pattern.search(term):
                if label not in seen_critical:
                    critical.append(label if pattern.search(term_norm) else term)
                    seen_critical.add(label if pattern.search(term_norm) else term)
                is_critical = True
                break

        if is_critical:
            continue

        # 短于 3 字符的普通词放 support
        if len(term_norm) <= 3:
            support.append(term)
        else:
            # 仅出现在 query 中的词 -> critical
            if term_norm in query_norm:
                critical.append(term)
            # 出现在 source 标识中的词 -> critical
            elif term_norm in sid_text or term_norm in title_text:
                critical.append(term)
            else:
                support.append(term)

    return critical, support, example


# ============================================================================
# V2: Source quality gate
# ============================================================================

def _source_quality_gate(
    query: str,
    answer: str,
    source_id_sequence: list[str],
    source_titles: list[str],
    source_relevance_scores: list[float],
    critical_terms: list[str],
    matched_critical: list[str],
) -> tuple[str, bool, str]:
    """评估来源质量, 返回 (gate_result, corpus_gap_detected, diagnosis)。"""
    qa_text = _normalize_evidence_text(f"{query} {answer}")
    sid_text = " ".join(source_id_sequence).lower()
    title_text = " ".join(source_titles).lower()
    max_relevance = max(source_relevance_scores) if source_relevance_scores else 0.0
    critical_set = {t.casefold() for t in critical_terms}
    matched_set = {t.casefold() for t in matched_critical}

    # ── LoRA corpus gap guardrail ──
    lora_signals = {"lora", "peft", "qlora", "low-rank", "low rank",
                    "低秩", "参数高效微调", "parameter efficient"}
    lora_in_query = any(sig in qa_text for sig in lora_signals)
    if lora_in_query:
        source_has_lora = any(
            sig in sid_text or sig in title_text for sig in lora_signals
        )
        if not source_has_lora:
            return "low", True, "corpus_gap: LoRA/PEFT/QLoRA/低秩来源缺失"

    # ── FastAPI gate ──
    fastapi_signals = {"fastapi", "request body", "pydantic", "basemodel"}
    fastapi_in_query = sum(1 for sig in fastapi_signals if sig in qa_text)
    if fastapi_in_query >= 2:
        has_fastapi_source = "fastapi_docs" in sid_text or any(
            "fastapi" in t for t in source_titles
        )
        if has_fastapi_source and max_relevance >= 0.60:
            fastapi_critical_hits = sum(
                1 for sig in fastapi_signals if sig in critical_set and sig in matched_set
            )
            if fastapi_critical_hits >= 3:
                return "high", False, "fastapi_source_quality_gate: 来源正确且关键术语全部命中"
            elif fastapi_critical_hits >= 2:
                return "medium", False, "fastapi_source_quality_gate: 来源正确且多数关键术语命中"
            else:
                return "medium", False, "fastapi_source_quality_gate: 来源正确"
        elif has_fastapi_source:
            return "medium", False, "fastapi_source_quality_gate: 来源正确但相关度不足"

    # ── RAG gate ──
    if "rag" in sid_text or "enterprise_rag_pipeline" in sid_text:
        rag_critical_hits = sum(
            1 for t in ("rag", "retrieval", "generation", "检索", "生成")
            if t in critical_set and t in matched_set
        )
        if rag_critical_hits >= 3:
            return "high", False, "rag_source_quality_gate: 来源包含 enterprise_rag_pipeline 且关键术语高度命中"
        elif rag_critical_hits >= 2:
            return "medium", False, "rag_source_quality_gate: 来源包含 enterprise_rag_pipeline"
        else:
            return "medium", False, "rag_source_quality_gate: 来源包含 RAG 定义但术语命中不足"

    # ── System retrieval gate ──
    if "enterprise_rag_pipeline" in sid_text or "enterprise_agent_overview" in sid_text:
        system_hits = sum(
            1 for t in ("document", "chunk", "embedding", "vector store",
                       "retrieval", "context", "answer", "检索", "rag")
            if t in critical_set and t in matched_set
        )
        if system_hits >= 3:
            return "high", False, "system_retrieval_gate: 来源包含项目说明且关键术语命中"
        elif system_hits >= 1:
            return "medium", False, "system_retrieval_gate: 来源包含项目说明"
        else:
            return "medium", False, "system_retrieval_gate: 来源包含项目说明但术语命中不足"

    return "none", False, "no_quality_gate_triggered"


# ============================================================================
# V2: 加权评分
# ============================================================================

def _weighted_grounding_score(
    critical: list[str],
    support: list[str],
    example: list[str],
    matched_critical: list[str],
    matched_support: list[str],
    matched_example: list[str],
) -> float:
    """加权覆盖率评分.

    critical: 0.65, support: 0.25, example: 0.10
    example 为 0 时不惩罚.
    """
    total_weight = 0.0
    matched_weight = 0.0

    if critical:
        w = 0.65
        total_weight += w
        matched_weight += w * len(matched_critical) / len(critical)

    if support:
        w = 0.25
        total_weight += w
        matched_weight += w * len(matched_support) / len(support)

    if example:
        w = 0.10
        total_weight += w
        matched_weight += w * len(matched_example) / len(example)
    # example 为 0 时不惩罚

    if total_weight == 0:
        return 0.0
    return round(matched_weight / total_weight, 4)

_HIGH_GROUNDING_THRESHOLD = 0.70
_MEDIUM_GROUNDING_THRESHOLD = 0.35
_GATE_HIGH_SCORE_FLOOR = 0.72
_GATE_MEDIUM_SCORE_FLOOR = 0.45
_CORPUS_GAP_SCORE_CEILING = 0.20


def _calibrate_grounding_score_and_status(
    raw_score: float,
    status_before_calibration: str,
    *,
    source_quality_gate: str,
    corpus_gap_detected: bool,
) -> tuple[float, str, dict[str, Any]]:
    """Align UI-facing grounding_score with grounding_status.

    raw_score is the pure weighted term-overlap score.
    grounding_score is the calibrated UI-facing score after source-quality gates.
    Corpus-gap guardrail has the highest priority and cannot be elevated.
    """
    raw = round(float(raw_score or 0.0), 4)
    gate = str(source_quality_gate or "none").strip().lower()
    status_before = str(status_before_calibration or "low").strip().lower()

    score_floor_applied: float | None = None
    calibrated_by_gate = False
    reason = "raw_score_threshold"

    if corpus_gap_detected:
        calibrated = round(min(raw, _CORPUS_GAP_SCORE_CEILING), 4)
        return calibrated, "low", {
            "score_floor_applied": None,
            "calibrated_by_source_quality_gate": False,
            "score_calibration_reason": "corpus_gap_guardrail",
        }

    if gate == "high":
        score_floor_applied = _GATE_HIGH_SCORE_FLOOR
        calibrated = round(max(raw, score_floor_applied), 4)
        calibrated_by_gate = True
        status = "high"
        reason = "source_quality_gate_high_floor"
    elif gate == "medium":
        score_floor_applied = _GATE_MEDIUM_SCORE_FLOOR
        calibrated = round(max(raw, score_floor_applied), 4)
        calibrated_by_gate = True
        status = "high" if calibrated >= _HIGH_GROUNDING_THRESHOLD else "medium"
        reason = "source_quality_gate_medium_floor"
    elif status_before == "high":
        score_floor_applied = _HIGH_GROUNDING_THRESHOLD if raw < _HIGH_GROUNDING_THRESHOLD else None
        calibrated = round(max(raw, _HIGH_GROUNDING_THRESHOLD), 4)
        status = "high"
        reason = "status_high_score_floor" if score_floor_applied is not None else "raw_score_threshold"
    elif status_before == "medium":
        score_floor_applied = _MEDIUM_GROUNDING_THRESHOLD if raw < _MEDIUM_GROUNDING_THRESHOLD else None
        calibrated = round(max(raw, _MEDIUM_GROUNDING_THRESHOLD), 4)
        status = "high" if calibrated >= _HIGH_GROUNDING_THRESHOLD else "medium"
        reason = "status_medium_score_floor" if score_floor_applied is not None else "raw_score_threshold"
    else:
        calibrated = round(min(raw, _MEDIUM_GROUNDING_THRESHOLD - 0.0001), 4)
        status = "low"
        reason = "status_low_score_ceiling" if raw >= _MEDIUM_GROUNDING_THRESHOLD else "raw_score_threshold"

    return calibrated, status, {
        "score_floor_applied": score_floor_applied,
        "calibrated_by_source_quality_gate": calibrated_by_gate,
        "score_calibration_reason": reason,
    }

# ============================================================================
# V2: 主入口
# ============================================================================

@dataclass(frozen=True, slots=True)
class EvidenceVerificationResult:
    verifier_mode: str
    grounding_status: str
    grounding_score: float
    answer_has_sources: bool
    citation_coverage: bool
    # V1 fields (保留兼容)
    important_terms: list[str]
    matched_terms: list[str]
    unsupported_terms: list[str]
    source_count: int
    safe_fallback_triggered: bool
    calls_llm: bool = False
    writes_chroma: bool = False
    # V2 fields
    verifier_version: str = "v2_weighted_rule_based"
    critical_terms: list[str] = ()
    support_terms: list[str] = ()
    example_terms: list[str] = ()
    matched_critical_terms: list[str] = ()
    matched_support_terms: list[str] = ()
    matched_example_terms: list[str] = ()
    unsupported_critical_terms: list[str] = ()
    unsupported_support_terms: list[str] = ()
    unsupported_example_terms: list[str] = ()
    source_quality_gate: str = "none"
    corpus_gap_detected: bool = False
    diagnosis: str = ""
    raw_grounding_score: float = 0.0
    calibrated_grounding_score: float = 0.0
    grounding_status_before_calibration: str = ""
    score_floor_applied: float | None = None
    calibrated_by_source_quality_gate: bool = False
    score_calibration_reason: str = ""
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


def _source_value(source: dict[str, Any], field: str) -> str:
    metadata = source.get("metadata") if isinstance(source.get("metadata"), dict) else {}
    value = source.get(field)
    if value in (None, "", "unknown"):
        value = metadata.get(field)
    return str(value or "").strip()


def _source_full_text(source: dict[str, Any]) -> str:
    """获取 source 的完整文本 (优先 page_content/content, 其次 preview)。"""
    for field in ("content", "page_content", "text"):
        val = _source_value(source, field)
        if val and len(val) > 200:
            return val
    val = _source_value(source, "content_preview")
    if val:
        return val
    val = _source_value(source, "preview")
    return val


def summarize_sources_for_verifier(
    sources: list[dict[str, Any]],
    *,
    max_preview_chars: int = 2000,
) -> list[dict[str, Any]]:
    """Build bounded verifier-only source summaries (V2: 使用更完整文本)。"""
    summaries: list[dict[str, Any]] = []
    for source in sources:
        full_text = _source_full_text(source)[:max_preview_chars]
        evidence_text = " ".join(
            part
            for part in (
                _source_value(source, "source_id"),
                _source_value(source, "title"),
                _source_value(source, "doc_type"),
                _source_value(source, "section_path"),
                _source_value(source, "source_url"),
                _source_value(source, "chunk_id"),
                full_text,
            )
            if part
        )
        summaries.append(
            {
                "source_id": _source_value(source, "source_id"),
                "title": _source_value(source, "title"),
                "chunk_id": _source_value(source, "chunk_id"),
                "evidence_terms": _extract_raw_terms(evidence_text),
                "evidence_text": evidence_text,
            }
        )
    return summaries


def build_safe_fallback_answer(query: str = "") -> str:
    if any("a" <= c.lower() <= "z" for c in query) and not any(
        "一" <= c <= "鿿" for c in query
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
    """V2 weighted rule-based evidence verifier."""
    normalized_mode = str(mode or "off").strip().lower()
    has_answer = bool(answer.strip())
    has_sources = bool(sources)

    if normalized_mode != "rule_based":
        return EvidenceVerificationResult(
            verifier_mode="off",
            grounding_status="not_checked",
            grounding_score=0.0,
            answer_has_sources=has_answer and has_sources,
            citation_coverage=False,
            important_terms=[],
            matched_terms=[],
            unsupported_terms=[],
            source_count=len(sources),
            safe_fallback_triggered=False,
        )

    # 无回答或无来源 -> LOW
    if not has_answer or not has_sources:
        return EvidenceVerificationResult(
            verifier_mode="rule_based",
            grounding_status="low",
            grounding_score=0.0,
            answer_has_sources=has_answer and has_sources,
            citation_coverage=False,
            important_terms=[],
            matched_terms=[],
            unsupported_terms=[],
            source_count=len(sources),
            safe_fallback_triggered=bool(safe_fallback_enabled),
            diagnosis="no_answer_or_no_sources",
        )

    # ── Step 1: 提取原始术语和 source 文本 ──
    answer_terms = _extract_raw_terms(answer)
    source_summaries = summarize_sources_for_verifier(sources)

    # 合并所有 source 文本用于匹配
    all_source_text = " ".join(s["evidence_text"] for s in source_summaries)
    all_source_norm = _normalize_evidence_text(all_source_text)

    # ── Step 2: 三级分类 ──
    source_ids = [s["source_id"] for s in source_summaries]
    source_titles = [s["title"] for s in source_summaries]
    source_relevance = [
        float(_source_value(src, "relevance_score") or _source_value(src, "score") or 0.5)
        for src in sources
    ]

    critical, support, example = _classify_terms(
        answer_terms, query, source_ids, source_titles
    )

    # ── Step 3: 匹配 ──
    def _matches(term: str) -> bool:
        tn = _normalize_evidence_text(term)
        return bool(tn and tn in all_source_norm)

    matched_critical = [t for t in critical if _matches(t)]
    matched_support = [t for t in support if _matches(t)]
    matched_example = [t for t in example if _matches(t)]

    unsupported_critical = [t for t in critical if not _matches(t)]
    unsupported_support = [t for t in support if not _matches(t)]
    unsupported_example = [t for t in example if not _matches(t)]

    # ── Step 4: 加权评分 ──
    wscore = _weighted_grounding_score(
        critical, support, example,
        matched_critical, matched_support, matched_example,
    )

    # ── Step 5: Source quality gate ──
    gate_result, corpus_gap, diagnosis = _source_quality_gate(
        query, answer, source_ids, source_titles, source_relevance,
        critical, matched_critical,
    )

    # ── Step 6: 确定最终 status ──
    citation_required = _is_citation_required(query, query_type)

    if corpus_gap:
        status = "low"
    elif gate_result == "high":
        status = "high"
    elif gate_result == "medium":
        if wscore >= 0.80:
            status = "high"
        else:
            status = "medium"
    elif citation_required:
        if wscore >= max(high_score, 0.70):
            status = "high"
        elif wscore < max(min_score, 0.50):
            status = "low"
        else:
            status = "medium"
    elif wscore >= high_score:
        status = "high"
    elif wscore < min_score:
        status = "low"
    else:
        status = "medium"

    # ── Step 7: Citation coverage ──
    all_matched = matched_critical + matched_support + matched_example
    status_before_calibration = status
    grounding_score, status, calibration_debug = _calibrate_grounding_score_and_status(
        wscore,
        status_before_calibration,
        source_quality_gate=gate_result,
        corpus_gap_detected=corpus_gap,
    )
    citation_coverage = bool(
        sources and all_matched and len(all_matched) >= 1
    )

    # ── Step 8: 构建兼容旧字段 ──
    important_terms = critical + support + example
    matched_terms = matched_critical + matched_support + matched_example
    unsupported_terms = unsupported_critical + unsupported_support + unsupported_example

    return EvidenceVerificationResult(
        verifier_mode="rule_based",
        grounding_status=status,
        grounding_score=grounding_score,
        answer_has_sources=has_answer and has_sources,
        citation_coverage=citation_coverage,
        # V1
        important_terms=important_terms,
        matched_terms=matched_terms,
        unsupported_terms=unsupported_terms,
        source_count=len(sources),
        safe_fallback_triggered=bool(safe_fallback_enabled and status == "low"),
        # V2
        verifier_version="v2_weighted_rule_based",
        critical_terms=critical,
        support_terms=support,
        example_terms=example,
        matched_critical_terms=matched_critical,
        matched_support_terms=matched_support,
        matched_example_terms=matched_example,
        unsupported_critical_terms=unsupported_critical,
        unsupported_support_terms=unsupported_support,
        unsupported_example_terms=unsupported_example,
        source_quality_gate=gate_result,
        corpus_gap_detected=corpus_gap,
        diagnosis=diagnosis,
        raw_grounding_score=wscore,
        calibrated_grounding_score=grounding_score,
        grounding_status_before_calibration=status_before_calibration,
        score_floor_applied=calibration_debug["score_floor_applied"],
        calibrated_by_source_quality_gate=calibration_debug["calibrated_by_source_quality_gate"],
        score_calibration_reason=calibration_debug["score_calibration_reason"],
    )
