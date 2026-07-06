"""Phase 6B: 后处理函数 — 去重、归一化、语料平衡、citation 候选选择。

纯函数，无副作用，不依赖外部服务。
"""

from __future__ import annotations

from rag.search_channels.base import SearchHit


def dedup_by_chunk_id(hits: list[SearchHit]) -> list[SearchHit]:
    """按 chunk_id 去重，保留最高分的。"""
    seen: dict[str, SearchHit] = {}
    for hit in hits:
        if hit.chunk_id not in seen or hit.score > seen[hit.chunk_id].score:
            seen[hit.chunk_id] = hit
    return sorted(seen.values(), key=lambda h: h.score, reverse=True)


def dedup_by_source_id(hits: list[SearchHit], max_per_source: int = 3) -> list[SearchHit]:
    """每个 source_id 最多保留 N 条，取最高分的。"""
    groups: dict[str, list[SearchHit]] = {}
    for hit in hits:
        groups.setdefault(hit.source_id, []).append(hit)
    result: list[SearchHit] = []
    for source_hits in groups.values():
        source_hits.sort(key=lambda h: h.score, reverse=True)
        result.extend(source_hits[:max_per_source])
    return sorted(result, key=lambda h: h.score, reverse=True)


def normalize_scores(hits: list[SearchHit]) -> list[SearchHit]:
    """Min-max 归一化到 [0, 1]。"""
    if not hits:
        return hits
    scores = [h.score for h in hits]
    s_min, s_max = min(scores), max(scores)
    if s_max == s_min:
        for h in hits:
            h.score = 1.0
        return hits
    for h in hits:
        h.score = round((h.score - s_min) / (s_max - s_min), 4)
    return hits


def balance_corpora(
    hits: list[SearchHit],
    min_per_corpus: int = 1,
    total_max: int = 10,
) -> list[SearchHit]:
    """语料平衡：确保每个 corpus 至少 min_per_corpus 条。

    按 score 降序轮询分配，直到 total_max。
    """
    if not hits:
        return hits

    by_corpus: dict[str, list[SearchHit]] = {}
    for h in hits:
        by_corpus.setdefault(h.corpus, []).append(h)

    for corpus_hits in by_corpus.values():
        corpus_hits.sort(key=lambda x: x.score, reverse=True)

    corpora = list(by_corpus.keys())
    result: list[SearchHit] = []
    pointers = {c: 0 for c in corpora}

    # Round-robin: 每个 corpus 轮流取一条
    while len(result) < total_max:
        added = False
        for c in corpora:
            if pointers[c] < len(by_corpus[c]):
                result.append(by_corpus[c][pointers[c]])
                pointers[c] += 1
                added = True
            if len(result) >= total_max:
                break
        if not added:
            break

    # 确保每个 corpus 至少有 min_per_corpus 条
    for c in corpora:
        count = sum(1 for h in result if h.corpus == c)
        while count < min_per_corpus and pointers[c] < len(by_corpus[c]):
            result.append(by_corpus[c][pointers[c]])
            pointers[c] += 1
            count += 1

    return result[:total_max]


def select_citation_candidates(
    hits: list[SearchHit],
    max_candidates: int = 6,
    min_score: float = 0.0,
) -> list[SearchHit]:
    """从去重后 hits 中选择 citation 候选。

    要求 chunk_id 非空，score >= min_score。
    """
    candidates = [h for h in hits if h.chunk_id and h.score >= min_score]
    candidates.sort(key=lambda h: h.score, reverse=True)
    return candidates[:max_candidates]


def postprocess_pipeline(
    hits: list[SearchHit],
    max_total: int = 10,
    max_per_source: int = 3,
    min_per_corpus: int = 1,
    normalize: bool = True,
) -> dict:
    """一站式后处理：去重 → 归一化 → 源去重 → 语料平衡 → citation 候选。

    Returns:
        dict with: merged_hits, citation_candidates, stats
    """
    stats = {"raw_count": len(hits)}

    # Step 1: chunk_id 去重
    hits = dedup_by_chunk_id(hits)
    stats["after_chunk_dedup"] = len(hits)

    # Step 2: 归一化
    if normalize:
        hits = normalize_scores(hits)

    # Step 3: source_id 去重
    hits = dedup_by_source_id(hits, max_per_source=max_per_source)
    stats["after_source_dedup"] = len(hits)

    # Step 4: 语料平衡
    hits = balance_corpora(hits, min_per_corpus=min_per_corpus, total_max=max_total)
    stats["after_balance"] = len(hits)

    # Step 5: citation 候选
    citations = select_citation_candidates(hits)

    return {
        "merged_hits": hits,
        "citation_candidates": citations,
        "stats": stats,
    }
