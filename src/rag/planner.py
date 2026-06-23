from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

MULTI_HOP_CONNECTORS = (
    "compare",
    "difference",
    "versus",
    " vs ",
    "both",
    "and",
    "multi-hop",
)
AMBIGUOUS_TERMS = (
    "it",
    "that",
    "this",
    "continue",
    "above",
    "previous",
)
UNSUPPORTED_TERMS = (
    "weather",
    "stock price",
    "lottery",
    "love letter",
)
CITATION_TERMS = (
    "citation",
    "source",
    "reference",
    "evidence",
)
CODE_CONFIG_PATTERNS = (
    r"/[A-Za-z0-9_./{}:-]+",
    r"\b[A-Za-z_][A-Za-z0-9_]*\(",
    r"\b[A-Z][A-Z0-9]+_[A-Z0-9_]+\b",
    r"\b(?:GET|POST|PUT|PATCH|DELETE)\b",
    r"\b[1-5]\d{2}\b",
    r"\.(?:py|json|ya?ml|toml)\b",
)


@dataclass(frozen=True)
class PlannerResult:
    planner_type: str
    requires_multi_hop: bool
    sub_queries: list[str]
    reason: str
    calls_llm: bool = False
    writes_chroma: bool = False

    def as_debug(self) -> dict[str, Any]:
        return {
            "planner_mode": "rule_based",
            "planner_type": self.planner_type,
            "requires_multi_hop": self.requires_multi_hop,
            "sub_queries": self.sub_queries,
            "reason": self.reason,
            "calls_llm": self.calls_llm,
            "writes_chroma": self.writes_chroma,
        }


def _contains_cjk(text: str) -> bool:
    return any("\u4e00" <= character <= "\u9fff" for character in text)


def split_multi_hop_query(query: str, *, max_parts: int = 3) -> list[str]:
    normalized = " ".join(str(query or "").split())
    if not normalized:
        return []

    if _contains_cjk(normalized):
        parts = re.split(r"(?:对比|比较|区别|以及|并且|同时|分别|和)", normalized)
    else:
        parts = re.split(
            r"(?:\bcompare\b|\bdifference\b|\bversus\b|\bvs\.?\b|\band\b|\bboth\b)",
            normalized,
            flags=re.IGNORECASE,
        )
    cleaned = [part.strip(" ,;:?!.，。；：？！") for part in parts]
    cleaned = [part for part in cleaned if len(part) >= 2]
    if len(cleaned) < 2:
        return [normalized]
    return cleaned[:max_parts]


def _has_multi_hop_signal(query: str) -> bool:
    lowered = query.casefold()
    if any(term in lowered for term in MULTI_HOP_CONNECTORS):
        return True
    return bool(re.search(r"(对比|比较|区别|以及|并且|同时|分别|和)", query))


def _has_code_config_signal(query: str) -> bool:
    lowered = query.casefold()
    if any(term in lowered for term in ("config", "schema", "endpoint", "parameter")):
        return True
    return any(re.search(pattern, query, flags=re.IGNORECASE) for pattern in CODE_CONFIG_PATTERNS)


def _has_citation_signal(query: str) -> bool:
    lowered = query.casefold()
    return any(term in lowered for term in CITATION_TERMS) or bool(
        re.search(r"(引用|出处|来源|证据)", query)
    )


def _has_ambiguous_signal(query: str) -> bool:
    lowered = query.casefold().strip(" ?!.，。？！")
    if lowered in AMBIGUOUS_TERMS:
        return True
    return bool(re.search(r"^(它|这个|那个|上面|刚才|继续)", query.strip()))


def _has_unsupported_signal(query: str) -> bool:
    lowered = query.casefold()
    return any(term in lowered for term in UNSUPPORTED_TERMS) or bool(
        re.search(r"(天气|股票|彩票|情书)", query)
    )


def plan_query(
    query: str,
    *,
    query_type_hint: str | None = None,
) -> PlannerResult:
    normalized = " ".join(str(query or "").split())
    if not normalized:
        return PlannerResult(
            planner_type="ambiguous",
            requires_multi_hop=False,
            sub_queries=[],
            reason="empty query",
        )

    hinted_type = str(query_type_hint or "")
    if hinted_type == "unsupported_query" or _has_unsupported_signal(normalized):
        return PlannerResult(
            planner_type="unsupported",
            requires_multi_hop=False,
            sub_queries=[],
            reason="unsupported query signal detected",
        )
    if hinted_type == "memory_follow_up":
        return PlannerResult(
            planner_type="simple",
            requires_multi_hop=False,
            sub_queries=[],
            reason="memory follow-up should continue through memory rewriting",
        )
    if hinted_type == "ambiguous_query" or _has_ambiguous_signal(normalized):
        return PlannerResult(
            planner_type="ambiguous",
            requires_multi_hop=False,
            sub_queries=[],
            reason="ambiguous or context-dependent query",
        )
    if hinted_type == "multi_hop_lookup" or _has_multi_hop_signal(normalized):
        sub_queries = split_multi_hop_query(normalized)
        return PlannerResult(
            planner_type="multi_hop" if len(sub_queries) > 1 else "complex",
            requires_multi_hop=len(sub_queries) > 1,
            sub_queries=sub_queries,
            reason="multi-hop connector detected",
        )
    if hinted_type in {"code_api_config", "citation_required_query"}:
        return PlannerResult(
            planner_type="complex",
            requires_multi_hop=False,
            sub_queries=[],
            reason=f"{hinted_type} requires specialized evidence handling",
        )
    if _has_code_config_signal(normalized) or _has_citation_signal(normalized):
        return PlannerResult(
            planner_type="complex",
            requires_multi_hop=False,
            sub_queries=[],
            reason="code/config or citation signal detected",
        )
    return PlannerResult(
        planner_type="simple",
        requires_multi_hop=False,
        sub_queries=[],
        reason="no complex planning signal detected",
    )
