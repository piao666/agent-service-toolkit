"""Phase 7: Memory Policy — 控制何时写入 memory candidate。

只对项目约束、阶段状态、用户明确偏好生成候选。普通知识问答不写入。
"""

from __future__ import annotations

from typing import Any

# ── 写入触发关键词 ───────────────────────────────────────────────────

_WRITE_TRIGGER_KEYWORDS = [
    # 项目约束
    "本项目", "当前项目", "enterprise_kb", "知识库",
    "默认", "禁止", "不允许", "必须", "只能",
    # 阶段/状态
    "Phase", "阶段", "已完成", "当前状态",
    # 用户偏好/约束
    "我要求", "我偏好", "我需要", "请记住", "记住",
    "以后都", "每次都", "不要", "避免",
    # 配置/策略变更
    "配置", "策略", "规则", "policy",
    "以后", "今后", "之后",
]

# ── 禁止写入关键词 (弱规则) ──────────────────────────────────────────

_NO_WRITE_KEYWORDS = [
    "什么是", "如何", "为什么",
    "介绍一下", "解释", "区别",
    "示例", "例子", "代码",
]

# ── 强约束关键词 (优先级最高，覆盖弱规则) ─────────────────────────────

_STRONG_CONSTRAINT_KEYWORDS = [
    "必须", "禁止", "不允许", "只能",
    "以后都", "今后都", "以后所有",
    "本项目", "当前项目",
    "请记住", "记住",
]


class MemoryPolicy:
    """判断当前 query+answer 是否应生成 memory candidate。

    优先级：强约束 > 触发 > 禁止。
    """

    @staticmethod
    def should_write_candidate(query: str, rewritten_query: str = "",
                                answer: str = "", intent: str = "") -> bool:
        text = query + " " + rewritten_query

        # Step 1: 强约束关键词优先 (覆盖弱禁止规则)
        for kw in _STRONG_CONSTRAINT_KEYWORDS:
            if kw in text:
                return True

        # Step 2: 弱禁止规则 (纯知识问答)
        for kw in _NO_WRITE_KEYWORDS:
            if kw in text:
                return False

        # Step 3: 普通触发
        for kw in _WRITE_TRIGGER_KEYWORDS:
            if kw in text:
                return True

        return False

    @staticmethod
    def extract_candidate(query: str, answer: str = "",
                           rewritten_query: str = "") -> list[dict[str, Any]]:
        """从 query+answer 中提取 memory candidate。"""
        candidates: list[dict[str, Any]] = []

        if MemoryPolicy.should_write_candidate(query, rewritten_query, answer):
            candidates.append({
                "type": "project_constraint",
                "source": "user_query",
                "query": query[:200],
                "key_point": rewritten_query or query[:200],
                "status": "candidate_only",
            })

        return candidates
