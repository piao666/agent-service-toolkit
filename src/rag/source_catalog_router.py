"""Source Catalog Query Router — 独立模块，不修改现有 retriever。

当 query 命中 source_catalog 意图时，主动检索 patch collection，并将 patch context 前置。
默认关闭 (SOURCE_CATALOG_PATCH_ENABLED=false)，不影响现有检索链路。

用法 (测试):
  from rag.source_catalog_router import is_source_catalog_query, SourceCatalogRouter
  if is_source_catalog_query(query):
      router = SourceCatalogRouter()
      patch_hits = router.retrieve_patch(query)
"""

import os
import re
from pathlib import Path
from typing import Any

# ── 正向触发词 ──
_POSITIVE_PATTERNS = [
    r'source_catalog', r'source.catalog', r'source catalog',
    r'source_catalog\.yaml', r'source.catalog\.yaml',
    r'source_id', r'source\s*列表',
    r'每个\s*domain', r'domain\s*字段', r'domain\s*取值',
    r'domain\s*下有哪些\s*source', r'domain\s*有哪些\s*source',
    r'source_catalog\s*中有哪些\s*domain',
    r'domain\s*字段\s*有哪些\s*取值',
]

# ── 条件 B: domain + source/source_id 同时出现 ──
_CONDITION_B_DOMAIN = re.compile(r'domain', re.I)
_CONDITION_B_SOURCE = re.compile(r'source[_\s]*(?:id|列表|字段|取值|有哪些|每个)', re.I)

# ── 负例 (必须返回 false) ──
_NEGATIVE_PATTERNS = [
    r'domain\s*adaptation', r'领域知识', r'domain\s*model',
    r'source\s*tracing', r'source\s*code', r'source.target\s*attention',
    r'domain\s*modeling', r'source\s*文件', r'source\s*code\s*如何',
    r'FastAPI\s*domain', r'Python\s*source',
    r'Transformer.*source.target', r'数据库.*domain',
]


def is_source_catalog_query(query: str) -> bool:
    """判断 query 是否是 source_catalog 查询。不误伤普通问题。"""
    if not query or not query.strip():
        return False

    q = query.strip()

    # 先检查负例
    for pattern in _NEGATIVE_PATTERNS:
        if re.search(pattern, q, re.I):
            return False

    # 条件 A: 直接包含 source_catalog
    if re.search(r'source[_\.\s]?catalog', q, re.I):
        return True

    # 条件 B: domain + source/source_id 同时出现
    if _CONDITION_B_DOMAIN.search(q) and _CONDITION_B_SOURCE.search(q):
        return True

    # 条件 C: 明确询问 domain mapping
    if re.search(r'每个\s*domain.*source|domain.*映射', q, re.I):
        return True

    return False


class SourceCatalogRouter:
    """Source catalog patch 检索器。独立于 production retriever。"""

    def __init__(
        self,
        persist_dir: str | None = None,
        collection_name: str | None = None,
        embedding_model_path: str | None = None,
    ):
        self.enabled = os.environ.get("SOURCE_CATALOG_PATCH_ENABLED", "false").lower() == "true"
        self.persist_dir = persist_dir or os.environ.get(
            "SOURCE_CATALOG_PATCH_PERSIST_DIR",
            "./storage/chroma_source_catalog_kb_v1",
        )
        self.collection_name = collection_name or os.environ.get(
            "SOURCE_CATALOG_PATCH_COLLECTION",
            "source_catalog_kb_v1",
        )
        self.top_k = int(os.environ.get("SOURCE_CATALOG_PATCH_TOP_K", "5"))
        self.injection_mode = os.environ.get("SOURCE_CATALOG_PATCH_INJECTION_MODE", "patch_first")
        self._emb_model_path = embedding_model_path
        self._emb = None
        self._vs = None

    def _get_vs(self):
        if not self.enabled:
            return None
        persist_path = Path(self.persist_dir)
        if not persist_path.exists():
            return None
        if self._vs is None:
            from rag.embeddings import get_embedding_model
            from langchain_chroma import Chroma

            if self._emb is None:
                self._emb = get_embedding_model(model_path=self._emb_model_path)
            try:
                self._vs = Chroma(
                    persist_directory=str(persist_path.resolve()),
                    collection_name=self.collection_name,
                    embedding_function=self._emb,
                )
            except Exception:
                return None
        return self._vs

    def retrieve_patch(self, query: str) -> list[dict]:
        """检索 source_catalog patch collection。"""
        vs = self._get_vs()
        if vs is None:
            return []

        hits = vs.similarity_search_with_score(query, k=self.top_k)
        results = []
        for doc, score in hits:
            m = doc.metadata or {}
            results.append({
                "chunk_id": m.get("chunk_id", ""),
                "source_id": m.get("source_id", ""),
                "patch_doc_id": m.get("patch_doc_id", ""),
                "section_type": m.get("section_type", ""),
                "score": float(score),
                "page_content": doc.page_content,
            })
        return results

    def inject_context(
        self,
        base_hits: list[dict],
        patch_hits: list[dict],
        max_total: int = 10,
    ) -> tuple[list[dict], dict]:
        """将 patch context 注入 base hits。返回 (merged_hits, debug_info)。"""
        if not patch_hits:
            return base_hits, {
                "source_catalog_route_triggered": True,
                "source_catalog_patch_hit_count": 0,
                "source_catalog_patch_doc_ids": [],
                "source_catalog_injection_mode": self.injection_mode,
                "source_catalog_patch_context_chars": 0,
                "fallback_to_base": True,
            }

        # 去重
        seen_ids = {h.get("chunk_id", "") for h in base_hits}
        unique_patch = [h for h in patch_hits if h.get("chunk_id", "") not in seen_ids]

        patch_chars = sum(len(h.get("page_content", "")) for h in unique_patch)

        if self.injection_mode == "patch_first":
            merged = unique_patch + base_hits
        else:
            merged = base_hits[:max_total - len(unique_patch)] + unique_patch

        merged = merged[:max_total]

        debug = {
            "source_catalog_route_triggered": True,
            "source_catalog_patch_hit_count": len(patch_hits),
            "source_catalog_patch_doc_ids": [h.get("patch_doc_id", "") for h in unique_patch],
            "source_catalog_injection_mode": self.injection_mode,
            "source_catalog_patch_rank_before_injection": -1,  # not applicable offline
            "source_catalog_patch_context_chars": patch_chars,
            "fallback_to_base": False,
        }
        return merged, debug


# ── Structured Answer (non-LLM, authoritative data) ──


def build_source_catalog_structured_answer(query: str) -> dict | None:
    """从 authoritative source_catalog JSON 生成 structured answer。不依赖 LLM。

    返回 {"answer": str, "sources": list, "structured_answer_used": True} 或 None。
    """
    enabled = os.environ.get("SOURCE_CATALOG_STRUCTURED_ANSWER_ENABLED", "false").lower() == "true"
    if not enabled or not is_source_catalog_query(query):
        return None

    # 读取 authoritative source registry (KB v1: env-var only, no default path)
    source_path = os.environ.get("SOURCE_CATALOG_STRUCTURED_ANSWER_SOURCE")
    if not source_path:
        return None  # KB v1: no default source catalog data file; must be explicitly configured

    from pathlib import Path as _Path
    import json as _json

    sp = _Path(source_path)
    if not sp.is_absolute():
        for root_candidate in [_Path(__file__).parents[2], _Path(".")]:
            candidate = root_candidate / source_path
            if candidate.exists():
                sp = candidate
                break

    if not sp.exists():
        return None
    try:
        data = _json.loads(sp.read_text(encoding="utf-8"))
    except Exception:
        return None

    domains = data.get("domain_distribution", {})
    if not domains:
        return None

    # 生成答案
    ql = query.lower()
    is_list_domains = "domain 字段有哪些取值" in ql or "有哪些 domain" in ql or \
        ("domain" in ql and "取值" in ql)
    is_list_source_ids = "有哪些 source_id" in ql or "有哪些 source id" in ql or \
        "source_id.*列表" in ql or "列出.*source_id" in ql
    is_full_mapping = ("每个 domain" in ql and ("source" in ql or "source_id" in ql)) or \
        re.search(r"domain.*(?:有哪些|下有哪些).*source", ql, re.I) or \
        re.search(r"source.*哪些.*domain", ql, re.I) or \
        ("domain" in ql and "source" in ql and ("每个" in ql or "映射" in ql or "哪些" in ql)) or \
        is_list_source_ids  # 列出 source_id 本质上是 full mapping

    if is_list_domains or is_full_mapping:
        lines = ["根据 source_catalog_domain_index_v1_1 (derived_from source_catalog.yaml)：\n"]
        if is_list_domains and not is_list_source_ids:
            lines.append(f"source_catalog.yaml 中 domain 字段共有 {len(domains)} 个取值：\n")
            for domain in sorted(domains):
                lines.append(f"- {domain}")
            lines.append("")

        if is_full_mapping or is_list_source_ids:
            lines.append(f"\n每个 domain 下的 source_id 映射：\n")
            for domain in sorted(domains):
                sources = domains[domain]
                lines.append(f"- {domain}: {', '.join(sources)}")

        return {
            "answer": "\n".join(lines),
            "sources": [{
                "source_id": "source_catalog_structured",
                "chunk_id": "source_catalog_kb_v1_structured",
                "title": "Source Catalog Domain Index (KB v1)",
                "doc_type": "structured",
                "content": "\n".join(lines),
                "content_preview": "\n".join(lines)[:500],
                "metadata": {
                    "doc_id": "source_catalog_kb_v1",
                    "trust_level": "authoritative_derived",
                    "derived_from": source_path,
                },
            }],
            "structured_answer_used": True,
            "source_catalog_structured_answer_debug": {
                "total_domains": len(domains),
                "total_sources": data.get("total_sources", sum(len(v) for v in domains.values())),
                "source": "source_catalog_domain_index_v1_1",
            },
        }
    return None


# ── 手动测试 ──
def _self_test():
    """简单自检 — 正例和负例。"""
    positives = [
        "source_catalog.yaml 中 domain 字段有哪些取值？",
        "source_catalog 中哪些 domain，每个 domain 有哪些 source？",
        "source_catalog.yaml 里有哪些 source_id？",
        "每个 domain 下有哪些 source_id？",
    ]
    negatives = [
        "domain adaptation 是什么？",
        "FastAPI domain model 是什么？",
        "RAG source tracing 是什么？",
        "Python source code 如何组织？",
        "Transformer source-target attention 是什么？",
        "领域知识是什么？",
        "数据库 domain modeling 是什么？",
    ]

    pos_ok = all(is_source_catalog_query(q) for q in positives)
    neg_ok = all(not is_source_catalog_query(q) for q in negatives)

    print(f"source_catalog_router self-test: positives={'OK' if pos_ok else 'FAIL'}, negatives={'OK' if neg_ok else 'FAIL'}")
    if not pos_ok:
        for q in positives:
            print(f"  [+] {is_source_catalog_query(q)}: {q[:60]}")
    if not neg_ok:
        for q in negatives:
            print(f"  [-] {is_source_catalog_query(q)}: {q[:60]}")
    return pos_ok and neg_ok


if __name__ == "__main__":
    _self_test()
