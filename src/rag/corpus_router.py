"""Phase 4F: Dual-corpus router — 关键词匹配，将 query 路由到正确的语料库。

规则引擎，不用 LLM。两个关键词表（中、英），OR 匹配。
命中任一 → internal_engineering_docs，否则 → official_docs（保守默认）。
"""

from typing import Literal

CorpusTarget = Literal["official_docs", "internal_engineering_docs"]

# ── 中文内部关键词 ───────────────────────────────────────────────────────
_INTERNAL_KEYWORDS_ZH: list[str] = [
    # 用户需求中指定的关键词
    "本项目", "Phase", "HPC", "bge-m3", "qwen3",
    "source_registry", "evidence audit", "trace",
    "repo hygiene", "评测", "失败案例",
    "chunk_size", "chunk_overlap", "runtime retrieval",
    "allowed_for_answer", "enabled=false", "为什么选择",
    # 项目治理/策略
    "知识库定位", "知识库准入", "文档状态策略",
    "评测标准", "ingestion pipeline", "legacy usage",
    # 架构
    "系统快照", "系统模块", "rag pipeline", "config reference",
    "agent graph", "项目扩展指南",
    # Phase 文档
    "phase3", "phase4", "语料库构建", "chunking",
    "embedding a/b", "retrieval eval", "索引构建", "hpc run",
    # 代码
    "config.py", "retriever.py", "service.py", "schema.py",
    "hpc_phase4", "runtime_retrieval", "api_retrieval",
    # 系统术语
    "本系统", "本知识库", "构建流程", "检索链路",
    "检索架构", "知识库策略", "代码摘要", "配置项",
    "语料库", "检索评测", "mrr", "hit@",
    "internal corpus", "内部语料", "内部文档",
    "embedding 选择", "embedding 模型", "索引构建",
    # Phase 4FH-RAG-ROUTING-FIX: routing 相关
    "auto corpus routing", "corpus routing", "routing 规则",
    "corpus_router", "route_corpus", "detect_corpus",
    "corpus 分类", "源文件类别", "source categories",
    "internal corpus overview", "内部语料概览",
]

# ── 英文内部关键词 ───────────────────────────────────────────────────────
_INTERNAL_KEYWORDS_EN: list[str] = [
    "this project", "this system", "internal corpus",
    "code summary", "hpc_phase4", "enterprise_kb",
    "ingestion pipeline", "source registry",
    "chunking strategy", "embedding model choice",
    "rag pipeline current", "agent graph current",
    "retrieval smoke", "api retrieval smoke",
    "corpus router", "traceable rag",
    "official_docs_retriever",
    "failure pattern", "repo hygiene",
    "hpc evaluation lesson", "retrieval debug",
]


def route_corpus(
    query: str,
    corpus: str = "auto",
) -> CorpusTarget:
    """根据 query 内容决定 target corpus。

    Args:
        query: 检索查询文本。
        corpus: "official_docs" | "internal_engineering_docs" | "auto"。

    Returns:
        "official_docs" 或 "internal_engineering_docs"。
    """
    # 用户显式指定 → 直接使用
    if corpus == "official_docs":
        return "official_docs"
    if corpus == "internal_engineering_docs":
        return "internal_engineering_docs"

    # auto routing
    q_lower = query.lower()

    # 中文关键词
    for kw in _INTERNAL_KEYWORDS_ZH:
        if kw.lower() in q_lower:
            return "internal_engineering_docs"

    # 英文关键词
    for kw in _INTERNAL_KEYWORDS_EN:
        if kw.lower() in q_lower:
            return "internal_engineering_docs"

    # 保守默认
    return "official_docs"


def detect_corpus(query: str) -> CorpusTarget:
    """route_corpus(query, corpus='auto') 的便捷别名。"""
    return route_corpus(query, "auto")


# Phase 4FH-RAG-ROUTING-FIX: Mixed query dual routing
_OFFICIAL_SIGNAL = [
    "chroma", "fastapi", "langgraph", "openai", "pydantic",
    "httpexception", "middleware", "dependency injection",
    "metadata filtering", "structured outputs", "stategraph",
    "collection", "embedding function", "request body",
    "streaming", "tool call", "field validator",
]
_INTERNAL_SIGNAL = [
    "structured retrieval", "检索设计", "本项目", "corpus_router",
    "route_corpus", "auto routing", "corpus routing",
    "trace", "检索链路", "rag pipeline", "agent graph",
    "internal corpus", "内部语料", "代码摘要",
    "retrieval eval", "评测", "hpc", "phase",
]


def detect_route_mode(query: str, corpus: str = "auto") -> str:
    """检测应使用的路由模式：official_only / internal_only / dual。

    当 query 同时包含官方技术术语和项目内部术语时，触发 dual routing。
    """
    if corpus in ("official_docs", "internal_engineering_docs"):
        return "official_only" if corpus == "official_docs" else "internal_only"

    ql = query.lower()
    off_hits = sum(1 for kw in _OFFICIAL_SIGNAL if kw.lower() in ql)
    int_hits = sum(1 for kw in _INTERNAL_SIGNAL + _INTERNAL_KEYWORDS_ZH + _INTERNAL_KEYWORDS_EN if kw.lower() in ql)

    if off_hits > 0 and int_hits > 0:
        return "dual"
    if int_hits > 0:
        return "internal_only"
    return "official_only"
