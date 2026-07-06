"""Phase 6C: 增强后处理模块 — 去重、归一化、语料平衡、citation 候选选择。

纯函数 + trace，无副作用，不依赖外部服务。
Phase 6A-6B 旧函数名保留为兼容别名。
"""

from __future__ import annotations

from rag.search_channels.base import SearchHit


# ── 1. Chunk-ID 去重 ──────────────────────────────────────────────────

def deduplicate_by_chunk_id(hits: list[SearchHit]) -> tuple[list[SearchHit], dict]:
    """按 chunk_id 去重，保留最高分。返回 (deduped, trace)。"""
    removed = 0
    seen: dict[str, SearchHit] = {}
    for hit in hits:
        if hit.chunk_id not in seen:
            seen[hit.chunk_id] = hit
        elif hit.score > seen[hit.chunk_id].score:
            seen[hit.chunk_id] = hit
            removed += 1
        else:
            removed += 1
    result = sorted(seen.values(), key=lambda h: h.score, reverse=True)
    trace = {
        "step": "deduplicate_by_chunk_id",
        "input_count": len(hits),
        "output_count": len(result),
        "removed_duplicates_count": removed,
        "policy": "keep_highest_score",
    }
    return result, trace


# ── 2. Source-ID 去重 ─────────────────────────────────────────────────

def deduplicate_by_source_id(
    hits: list[SearchHit],
    max_per_source: int = 3,
) -> tuple[list[SearchHit], dict]:
    """每个 source_id 最多保留 max_per_source 条，取最高分。返回 (deduped, trace)。"""
    groups: dict[str, list[SearchHit]] = {}
    for hit in hits:
        groups.setdefault(hit.source_id, []).append(hit)

    result: list[SearchHit] = []
    removed = 0
    for sid, source_hits in groups.items():
        source_hits.sort(key=lambda h: h.score, reverse=True)
        kept = source_hits[:max_per_source]
        removed += len(source_hits) - len(kept)
        result.extend(kept)

    result.sort(key=lambda h: h.score, reverse=True)
    trace = {
        "step": "deduplicate_by_source_id",
        "input_count": len(hits),
        "output_count": len(result),
        "removed_duplicates_count": removed,
        "source_dedup_policy": f"max_{max_per_source}_per_source",
        "sources_before": len(groups),
        "sources_after": len(set(h.source_id for h in result)),
    }
    return result, trace


# ── 3. 分数归一化 ─────────────────────────────────────────────────────

def normalize_scores(hits: list[SearchHit]) -> tuple[list[SearchHit], dict]:
    """Min-max 归一化到 [0, 1]，保留 original_score 在 metadata 中。"""
    if not hits:
        return hits, {"step": "normalize_scores", "method": "min_max", "input_count": 0, "output_count": 0}

    scores = [h.score for h in hits]
    s_min, s_max = min(scores), max(scores)

    for h in hits:
        # 保留原始分数
        h.metadata["original_score"] = h.score

    if s_max == s_min:
        for h in hits:
            h.score = 1.0
    else:
        for h in hits:
            h.score = round((h.score - s_min) / (s_max - s_min), 4)

    trace = {
        "step": "normalize_scores",
        "method": "min_max",
        "normalize_method": "min_max",
        "input_count": len(hits),
        "output_count": len(hits),
        "score_range_before": [s_min, s_max],
        "score_range_after": [0.0, 1.0],
    }
    return hits, trace


# ── 4. 语料平衡 ───────────────────────────────────────────────────────

def balance_corpora(
    hits: list[SearchHit],
    min_per_corpus: int = 1,
    total_max: int = 10,
) -> tuple[list[SearchHit], dict]:
    """Round-robin 语料平衡。返回 (balanced, trace)。"""
    input_n = len(hits)
    if not hits:
        trace = {
            "step": "balance_corpora",
            "input_count": 0,
            "output_count": 0,
            "corpus_distribution_before": {},
            "corpus_distribution_after": {},
            "policy": "round_robin",
        }
        return hits, trace

    # 分布 before
    dist_before: dict[str, int] = {}
    for h in hits:
        dist_before[h.corpus] = dist_before.get(h.corpus, 0) + 1

    by_corpus: dict[str, list[SearchHit]] = {}
    for h in hits:
        by_corpus.setdefault(h.corpus, []).append(h)

    for corpus_hits in by_corpus.values():
        corpus_hits.sort(key=lambda x: x.score, reverse=True)

    corpora = list(by_corpus.keys())
    result: list[SearchHit] = []
    pointers = {c: 0 for c in corpora}

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

    for c in corpora:
        count = sum(1 for h in result if h.corpus == c)
        while count < min_per_corpus and pointers[c] < len(by_corpus[c]):
            result.append(by_corpus[c][pointers[c]])
            pointers[c] += 1
            count += 1

    result = result[:total_max]

    # 分布 after
    dist_after: dict[str, int] = {}
    for h in result:
        dist_after[h.corpus] = dist_after.get(h.corpus, 0) + 1

    trace = {
        "step": "balance_corpora",
        "input_count": input_n,
        "output_count": len(result),
        "corpus_distribution_before": dist_before,
        "corpus_distribution_after": dist_after,
        "policy": "round_robin",
        "min_per_corpus": min_per_corpus,
        "total_max": total_max,
    }
    return result, trace


# ── 5. Citation 候选选择 ──────────────────────────────────────────────

def select_citation_candidates(
    hits: list[SearchHit],
    max_candidates: int = 6,
    min_score: float = 0.0,
) -> tuple[list[SearchHit], dict]:
    """从 hits 中选择 citation 候选。每个 candidate 必须字段完整。

    验证：chunk_id 非空，且来自输入 hits。
    """
    valid_hits = [h for h in hits if h.chunk_id and h.score >= min_score]
    candidates = sorted(valid_hits, key=lambda h: h.score, reverse=True)[:max_candidates]

    # 构建精简 candidate dict
    candidate_dicts = []
    for h in candidates:
        candidate_dicts.append({
            "chunk_id": h.chunk_id,
            "source_id": h.source_id,
            "corpus": h.corpus,
            "score": h.score,
            "text_preview": h.text_preview[:200] if h.text_preview else "",
            "heading_path": h.heading_path,
            "channel": h.channel,
        })

    trace = {
        "step": "select_citation_candidates",
        "citation_candidate_count": len(candidates),
        "input_hits_count": len(hits),
        "max_candidates": max_candidates,
        "all_from_merged_hits": all(
            any(c.chunk_id == h.chunk_id for h in hits)
            for c in candidates
        ),
    }
    return candidates, trace


# ── 6. 完整后处理管道 ─────────────────────────────────────────────────

def run_postprocess_pipeline(
    hits: list[SearchHit],
    max_total: int = 10,
    max_per_source: int = 3,
    min_per_corpus: int = 1,
    do_normalize: bool = True,
) -> dict:
    """一站式后处理管道：去重 → 归一化 → 源去重 → 语料平衡 → citation。

    Returns:
        dict with:
          - merged_hits: list[SearchHit]
          - citation_candidates: list[dict] (轻量 dict，非 SearchHit)
          - postprocess_trace: dict (含全部步骤 trace)
          - errors: list[str]
    """
    errors: list[str] = []
    trace_steps: list[dict] = []
    input_count = len(hits)

    # 过滤畸形 hits (空 chunk_id)
    malformed = [h for h in hits if not h.chunk_id]
    if malformed:
        errors.append(f"filtered {len(malformed)} hits with empty chunk_id")
        hits = [h for h in hits if h.chunk_id]

    # 复制，避免修改输入
    hits = [SearchHit(
        chunk_id=h.chunk_id, source_id=h.source_id,
        heading_path=h.heading_path, text_preview=h.text_preview,
        score=h.score, corpus=h.corpus, origin_url=h.origin_url,
        channel=h.channel, metadata=dict(h.metadata),
    ) for h in hits]

    # Step 1: chunk_id 去重
    hits, t1 = _deduplicate_by_chunk_id_new(hits)
    trace_steps.append(t1)

    # Step 2: 归一化
    if do_normalize:
        hits, t2 = _normalize_scores_new(hits)
        trace_steps.append(t2)

    # Step 3: source_id 去重
    hits, t3 = _deduplicate_by_source_id_new(hits, max_per_source=max_per_source)
    trace_steps.append(t3)

    # Step 4: 语料平衡
    hits, t4 = _balance_corpora_new(hits, min_per_corpus=min_per_corpus, total_max=max_total)
    trace_steps.append(t4)

    # Step 5: citation 候选
    _, t5 = _select_citation_candidates_new(hits)
    trace_steps.append(t5)

    # 构建 citation candidates (轻量 dict)
    citation_candidates = []
    for h in hits[:max_total]:
        if h.chunk_id:
            citation_candidates.append({
                "chunk_id": h.chunk_id,
                "source_id": h.source_id,
                "corpus": h.corpus,
                "score": h.score,
                "text_preview": h.text_preview[:200],
                "heading_path": h.heading_path,
                "channel": h.channel,
            })

    return {
        "merged_hits": hits,
        "citation_candidates": citation_candidates,
        "postprocess_trace": {
            "input_count": input_count,
            "output_count": len(hits),
            "steps": trace_steps,
            "citation_candidate_count": len(citation_candidates),
        },
        "errors": errors,
    }


# ── Phase 6A-6B 兼容层 ─────────────────────────────────────────────────
# 新函数返回 tuple[list, dict]（含 trace），旧调用方期望只返回 list。
# 保存新函数引用后，用旧签名覆盖模块级名称，保证向后兼容。

# 保存新函数（供 Phase 6C 直接调用）
_deduplicate_by_chunk_id_new = deduplicate_by_chunk_id
_deduplicate_by_source_id_new = deduplicate_by_source_id
_normalize_scores_new = normalize_scores
_balance_corpora_new = balance_corpora
_select_citation_candidates_new = select_citation_candidates


def _list_wrapper(fn):
    """适配器: (hits, **kw) -> list (丢弃 trace)。"""
    def wrapper(hits, **kwargs):
        result, _trace = fn(hits, **kwargs)
        return result
    return wrapper


# 覆盖模块级名称 — 旧 smoke / orchestrator 调用这些名字时得到 list 返回值
dedup_by_chunk_id = _list_wrapper(_deduplicate_by_chunk_id_new)
dedup_by_source_id = _list_wrapper(_deduplicate_by_source_id_new)
normalize_scores = _list_wrapper(_normalize_scores_new)
balance_corpora = _list_wrapper(_balance_corpora_new)
select_citation_candidates = _list_wrapper(_select_citation_candidates_new)


def postprocess_pipeline(
    hits, max_total=10, max_per_source=3, min_per_corpus=1, normalize=True,
):
    """Phase 6A-6B 兼容：返回 {merged_hits, citation_candidates, stats}。"""
    result = run_postprocess_pipeline(
        hits, max_total=max_total, max_per_source=max_per_source,
        min_per_corpus=min_per_corpus, do_normalize=normalize,
    )
    return {
        "merged_hits": result["merged_hits"],
        "citation_candidates": [
            SearchHit(
                chunk_id=c["chunk_id"], source_id=c["source_id"],
                heading_path=c["heading_path"], text_preview=c.get("text_preview", ""),
                score=c["score"], corpus=c["corpus"],
                channel=c.get("channel", ""),
            ) for c in result["citation_candidates"]
        ],
        "stats": {
            "raw_count": result["postprocess_trace"]["input_count"],
            "after_chunk_dedup": result["postprocess_trace"]["steps"][0]["output_count"] if result["postprocess_trace"]["steps"] else 0,
            "after_source_dedup": result["postprocess_trace"]["steps"][2]["output_count"] if len(result["postprocess_trace"]["steps"]) > 2 else 0,
            "after_balance": result["postprocess_trace"]["steps"][3]["output_count"] if len(result["postprocess_trace"]["steps"]) > 3 else 0,
        },
    }
