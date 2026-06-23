from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class JudgeResult:
    judge_mode: str
    verdict: str
    score: float
    reason: str
    answer_non_empty: bool
    source_count: int
    evidence_overlap: bool
    fallback_recommended: bool
    calls_llm: bool = False
    writes_chroma: bool = False

    def as_debug(self) -> dict[str, Any]:
        return {
            "judge_mode": self.judge_mode,
            "verdict": self.verdict,
            "score": self.score,
            "reason": self.reason,
            "answer_non_empty": self.answer_non_empty,
            "source_count": self.source_count,
            "evidence_overlap": self.evidence_overlap,
            "fallback_recommended": self.fallback_recommended,
            "calls_llm": self.calls_llm,
            "writes_chroma": self.writes_chroma,
        }


def _tokens(text: str) -> set[str]:
    normalized = str(text or "").casefold()
    words = set(re.findall(r"[a-zA-Z_][a-zA-Z0-9_./:-]*|\d+(?:\.\d+)?", normalized))
    cjk_bigrams = {
        normalized[index : index + 2]
        for index in range(max(0, len(normalized) - 1))
        if all("\u4e00" <= char <= "\u9fff" for char in normalized[index : index + 2])
    }
    return {token for token in words | cjk_bigrams if len(token) >= 2}


def _source_text(source: dict[str, Any]) -> str:
    metadata = source.get("metadata") if isinstance(source.get("metadata"), dict) else {}
    fields = (
        source.get("title"),
        source.get("section_path"),
        source.get("content_preview"),
        source.get("preview"),
        metadata.get("title"),
        metadata.get("section_path"),
        metadata.get("content_preview"),
    )
    return " ".join(str(value or "") for value in fields)


def judge_answer_rule_based(
    *,
    query: str,
    answer: str,
    sources: list[dict[str, Any]],
    verifier_debug: dict[str, Any] | None = None,
) -> JudgeResult:
    answer_non_empty = bool(str(answer or "").strip())
    source_count = len(sources)
    verifier = verifier_debug or {}
    grounding_status = str(verifier.get("grounding_status") or "")
    answer_tokens = _tokens(answer)
    evidence_tokens: set[str] = set()
    for source in sources:
        evidence_tokens.update(_tokens(_source_text(source)))
    evidence_overlap = bool(answer_tokens and evidence_tokens and answer_tokens & evidence_tokens)

    if not answer_non_empty:
        return JudgeResult(
            judge_mode="rule_based_fallback",
            verdict="fail",
            score=0.0,
            reason="empty answer",
            answer_non_empty=False,
            source_count=source_count,
            evidence_overlap=False,
            fallback_recommended=True,
        )
    if source_count == 0:
        return JudgeResult(
            judge_mode="rule_based_fallback",
            verdict="needs_review",
            score=0.35,
            reason="answer exists but no sources were returned",
            answer_non_empty=True,
            source_count=0,
            evidence_overlap=False,
            fallback_recommended=True,
        )

    if grounding_status == "low":
        score = 0.45 if evidence_overlap else 0.30
        return JudgeResult(
            judge_mode="rule_based_fallback",
            verdict="needs_review",
            score=score,
            reason="evidence verifier reported low grounding",
            answer_non_empty=True,
            source_count=source_count,
            evidence_overlap=evidence_overlap,
            fallback_recommended=True,
        )

    if evidence_overlap or grounding_status in {"high", "medium"}:
        return JudgeResult(
            judge_mode="rule_based_fallback",
            verdict="pass",
            score=0.85 if grounding_status == "high" else 0.70,
            reason="answer has sources and rule-based evidence support",
            answer_non_empty=True,
            source_count=source_count,
            evidence_overlap=evidence_overlap,
            fallback_recommended=False,
        )

    return JudgeResult(
        judge_mode="rule_based_fallback",
        verdict="needs_review",
        score=0.50,
        reason="sources exist but term overlap is weak",
        answer_non_empty=True,
        source_count=source_count,
        evidence_overlap=False,
        fallback_recommended=False,
    )
